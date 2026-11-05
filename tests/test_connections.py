import json
from urllib.parse import urlsplit, parse_qs
from fastapi.testclient import TestClient
from sqlalchemy import select
from airlock.api import create_app
from airlock.google import GoogleCalendar, SCOPES
from airlock.models import ToolCall
from test_calendar_workspace import Vault


def google_client(workspace):
    _, llm, sessions, settings = workspace
    vault = Vault()
    opened = []
    transport_calls = []
    identity = {"account": "test@example.com"}

    def transport(host, path, **kwargs):
        transport_calls.append((host, path))
        if host == "www.googleapis.com":
            return {"items": [{"id": identity["account"], "primary": True}]}
        return {
            "scope": " ".join(SCOPES),
            "access_token": "PRIVATE_ACCESS",
            "refresh_token": "PRIVATE_REFRESH",
            "expires_in": 3600,
        }

    google = GoogleCalendar(
        settings,
        vault=vault,
        transport=transport,
        browser_opener=lambda url: opened.append(url) or True,
    )
    c = TestClient(
        create_app(settings, llm=llm, sessions=sessions, google=google),
        base_url=settings.origin,
    )
    c.get("/")
    c.headers.update(
        {
            "Origin": settings.origin,
            "X-Airlock-CSRF": c.get("/api/session").json()["csrf"],
        }
    )
    return c, google, opened, identity, transport_calls


def configure(c):
    return c.post(
        "/api/google/configure",
        json={
            "document": {
                "installed": {
                    "client_id": "test.apps.googleusercontent.com",
                    "client_secret": "PRIVATE_CLIENT",
                }
            }
        },
    )


def test_one_click_uses_system_browser_local_domain_pkce_and_no_logged_credentials(
    workspace,
):
    c, google, opened, _, _ = google_client(workspace)
    with c:
        assert configure(c).status_code == 200
        result = c.post("/api/google/connect", json={}).json()
        assert result["browser_opened"] and len(opened) == 1
        query = parse_qs(urlsplit(opened[0]).query)
        assert query["redirect_uri"] == [workspace[3].origin + "/oauth/google/callback"]
        assert set(query["scope"][0].split()) == SCOPES
        assert query["code_challenge_method"] == ["S256"]
        callback = c.get(
            "/oauth/google/callback",
            params={"state": query["state"][0], "code": "PRIVATE_CODE"},
            follow_redirects=False,
        )
        assert (
            callback.status_code == 303
            and callback.headers["location"] == "/?view=connections&google=connected"
        )
        status = c.get("/api/google/status").json()
        assert status["account_label"] == "test@example.com"
        assert status["domain_id"] == c.get("/api/workspace").json()["id"]
        assert "PRIVATE" not in json.dumps(status)
        assert configure(c).status_code == 409
        assert c.post("/api/google/connect", json={}).status_code == 409
    with workspace[2]() as db:
        calls = db.scalars(select(ToolCall)).all()
        assert all(
            "PRIVATE" not in json.dumps([x.input_payload, x.output_payload])
            for x in calls
        )


def test_reauthorization_cannot_silently_switch_local_domain_account(workspace):
    c, google, opened, identity, _ = google_client(workspace)
    configure(c)
    c.post("/api/google/connect", json={})

    def callback():
        query = parse_qs(urlsplit(opened[-1]).query)
        return c.get(
            "/oauth/google/callback",
            params={"state": query["state"][0], "code": "code"},
            follow_redirects=False,
        )

    callback()
    previous = google.vault.get("tokens").copy()
    identity["account"] = "other-organization@example.org"
    c.post("/api/google/reauthorize", json={})
    assert "not_connected" in callback().headers["location"]
    assert google.vault.get("tokens") == previous
    c.post("/api/google/disconnect", json={})
    assert not google.status()["connected"]


def test_denied_callback_consumes_state_without_echoing_provider_error(workspace):
    c, google, opened, _, calls = google_client(workspace)
    configure(c)
    c.post("/api/google/connect", json={})
    state = parse_qs(urlsplit(opened[0]).query)["state"][0]
    r = c.get(
        "/oauth/google/callback",
        params={"state": state, "error": "PRIVATE_PROVIDER_DETAIL"},
        follow_redirects=False,
    )
    assert "PRIVATE" not in r.text + r.headers["location"]
    assert state not in google.pending and calls == []
    assert not google.status()["connected"]


def test_web_client_rejected_and_domain_name_is_local_only(workspace):
    c, google, _, _, _ = google_client(workspace)
    assert (
        c.post(
            "/api/google/configure",
            json={"document": {"web": {"client_id": "id", "client_secret": "secret"}}},
        ).status_code
        == 409
    )
    assert not google.status()["configured"]
    assert (
        c.put("/api/workspace", json={"name": "Synthetic work domain"}).status_code
        == 200
    )
    assert c.get("/api/workspace").json()["name"] == "Synthetic work domain"
    assert (
        c.put("/api/workspace", json={"name": "x", "domain_id": "other"}).status_code
        == 422
    )


def test_revoked_refresh_retains_account_binding_until_explicit_disconnect(workspace):
    from airlock.google import GoogleError
    import pytest

    c, google, opened, identity, _ = google_client(workspace)
    configure(c)
    c.post("/api/google/connect", json={})
    state = parse_qs(urlsplit(opened[-1]).query)["state"][0]
    google.complete(state, "code")
    tokens = google.vault.get("tokens")
    tokens["expires_at"] = 0
    transport = google.transport

    def revoked(host, path, **kwargs):
        raise GoogleError("Authorization expired", 400)

    google.transport = revoked
    with pytest.raises(GoogleError):
        google._token()
    assert not google.status()["connected"]
    assert google.status()["account_label"] == "test@example.com"
    google.transport = transport
    identity["account"] = "another@example.org"
    state = parse_qs(urlsplit(google.begin()).query)["state"][0]
    with pytest.raises(GoogleError, match="same Google account"):
        google.complete(state, "code")
    google.disconnect()
    state = parse_qs(urlsplit(google.begin()).query)["state"][0]
    google.complete(state, "code")
    assert google.status()["account_label"] == "another@example.org"
