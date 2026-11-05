import json
from types import SimpleNamespace

import pytest

from airlock.google import GoogleCalendar, GoogleError
from airlock.provisioning import provision_google
from test_calendar_workspace import Vault


def client(vault=None):
    return GoogleCalendar(SimpleNamespace(origin="http://127.0.0.1:8741"), vault=vault or Vault())


def test_provisioning_installs_only_client_and_preserves_existing_account(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {
        "client_id": "test.apps.googleusercontent.com", "client_secret": "test-only"
    }}))
    google = client()
    assert provision_google(google, path) == "configured"
    assert google.status()["configured"] and not google.status()["connected"]
    assert google.vault.get("tokens") is None
    google.vault.set("account", {"label": "synthetic@example.com"})
    google.vault.set("tokens", {"refresh_token": "test-refresh"})
    before = {key: google.vault.get(key).copy() for key in ("client", "account", "tokens")}
    path.write_text("An invalid replacement must not override the installed client")
    assert provision_google(google, path) == "already_configured"
    assert {key: google.vault.get(key) for key in before} == before


@pytest.mark.parametrize("document", ["[]", "bad json", "x" * 20_001,
    '{"web":{"client_id":"web.apps.googleusercontent.com","client_secret":"test"}}'])
def test_provisioning_rejects_invalid_configuration_without_storing_it(tmp_path, document):
    path = tmp_path / "client.json"
    path.write_text(document)
    google = client()
    with pytest.raises(GoogleError):
        provision_google(google, path)
    assert not google.status()["configured"]


def test_optional_packaged_registration_and_explicit_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("airlock.provisioning.files", lambda name: tmp_path)
    google = client()
    assert provision_google(google) == "not_supplied"
    with pytest.raises(GoogleError):
        provision_google(google, tmp_path / "missing.json")
    (tmp_path / "google_desktop_client.json").write_text(json.dumps({"installed": {
        "client_id": "package.apps.googleusercontent.com", "client_secret": "test-only"
    }}))
    assert provision_google(google) == "configured"
    assert google.vault.get("client")["client_id"] == "package.apps.googleusercontent.com"
