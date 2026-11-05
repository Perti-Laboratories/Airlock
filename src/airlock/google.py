"""Read-only Google Calendar transport, OAuth PKCE, and macOS Keychain credentials."""

import base64
import hashlib
import http.client
import json
import secrets
import threading
import time
from urllib.parse import urlencode, quote
from .memory import ActionError
from .config import DOMAIN_ID

SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    }
)


class GoogleError(ActionError):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class Keychain:
    service = "Airlock.GoogleCalendar.v1"

    def _backend(self):
        from keyring.backends.macOS import Keyring

        return Keyring()

    def get(self, key):
        try:
            value = self._backend().get_password(self.service, key)
            return json.loads(value) if value else None
        except Exception as exc:
            raise GoogleError(
                "macOS Keychain is unavailable. Unlock it and try again."
            ) from exc

    def set(self, key, value):
        try:
            self._backend().set_password(self.service, key, json.dumps(value))
        except Exception as exc:
            raise GoogleError(
                "Could not store Google credentials in macOS Keychain."
            ) from exc

    def delete(self, key):
        if self.get(key) is not None:
            try:
                self._backend().delete_password(self.service, key)
            except Exception as exc:
                raise GoogleError(
                    "Could not remove the local Google credential."
                ) from exc


def request_google(host, path, *, form=None, token=None):
    if host not in {"oauth2.googleapis.com", "www.googleapis.com"}:
        raise GoogleError("Unexpected Google endpoint.")
    connection = http.client.HTTPSConnection(host, timeout=25)
    try:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None
        if form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request("POST" if form is not None else "GET", path, data, headers)
        response = connection.getresponse()
        raw = response.read(10_000_001)
        if response.status != 200:
            messages = {
                400: ("Google authorization could not be renewed. Reconnect the account."
                      if host == "oauth2.googleapis.com" else "Google rejected the calendar request."),
                401: "Google authorization expired. Reconnect the account.",
                403: "Google denied access to this calendar.",
                410: "Google requires a fresh calendar sync.",
                429: "Google rate limit reached; sync will retry.",
            }
            raise GoogleError(
                messages.get(
                    response.status, "Google request failed; sync will retry."
                ),
                response.status,
            )
        if len(raw) > 10_000_000:
            raise GoogleError("Google response exceeded the local size limit.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise GoogleError("Google returned an invalid response.")
        return value
    except GoogleError:
        # ActionError inherits ValueError: preserve safe HTTP messages and status codes
        # so expired grants and incremental-sync resets reach their recovery paths.
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise GoogleError(
            "Google is unavailable. Local calendar data remains available."
        ) from exc
    finally:
        connection.close()


class GoogleCalendar:
    def __init__(self, settings, *, vault=None, transport=None, browser_opener=None):
        self.settings = settings
        self.vault = vault or Keychain()
        self.transport = transport or request_google
        self.browser_opener = browser_opener
        self.lock = threading.RLock()
        self.pending = {}

    def configure(self, document):
        client = document.get("installed", {})
        if (
            not isinstance(client, dict)
            or not str(client.get("client_id", "")).endswith(
                ".apps.googleusercontent.com"
            )
            or not client.get("client_secret")
        ):
            raise GoogleError("Choose a Google OAuth Desktop app client JSON file.")
        if (
            not isinstance(client["client_id"], str)
            or not isinstance(client["client_secret"], str)
            or len(client["client_id"]) > 500
            or len(client["client_secret"]) > 500
        ):
            raise GoogleError("Invalid Google client configuration.")
        with self.lock:
            if self.vault.get("tokens") or self.vault.get("account"):
                raise GoogleError(
                    "Disconnect Google before replacing the app configuration."
                )
            self.pending.clear()
            self.vault.set(
                "client",
                {
                    "client_id": client["client_id"],
                    "client_secret": client["client_secret"],
                },
            )

    def provision(self, document):
        """Provision once; upgrades never replace a locally selected client."""
        with self.lock:
            if self.vault.get("client"):
                return
            self.configure(document)

    def status(self):
        with self.lock:
            tokens = self.vault.get("tokens")
            account = self.vault.get("account") or {}
            return {
                "configured": bool(self.vault.get("client")),
                "connected": bool(tokens),
                "account_label": account.get("label")
                or (tokens.get("account_label") if tokens else None),
                "connected_at": tokens.get("connected_at") if tokens else None,
                "domain_id": DOMAIN_ID,
                "scopes": sorted(SCOPES),
                "sharing_enabled": False,
            }

    def begin(self):
        with self.lock:
            client = self.vault.get("client")
            if not client:
                raise GoogleError(
                    "Configure a Google Desktop OAuth client first. See Google setup instructions."
                )
            verifier = secrets.token_urlsafe(64)
            state = secrets.token_urlsafe(32)
            self.pending = {state: (time.time() + 600, verifier)}
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
                {
                    "client_id": client["client_id"],
                    "redirect_uri": self.settings.origin + "/oauth/google/callback",
                    "response_type": "code",
                    "scope": " ".join(sorted(SCOPES)),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "access_type": "offline",
                    "prompt": "consent select_account",
                    "include_granted_scopes": "false",
                }
            )

    def complete(self, state, code):
        with self.lock:
            pending = self.pending.pop(state, None)
            if not pending or pending[0] < time.time():
                raise GoogleError("Google sign-in expired. Start again from Airlock.")
            client = self.vault.get("client")
            result = self.transport(
                "oauth2.googleapis.com",
                "/token",
                form={
                    **client,
                    "code": code,
                    "code_verifier": pending[1],
                    "grant_type": "authorization_code",
                    "redirect_uri": self.settings.origin + "/oauth/google/callback",
                },
            )
            if set(result.get("scope", "").split()) != SCOPES or not result.get(
                "refresh_token"
            ):
                raise GoogleError(
                    "Google did not grant exactly the requested read-only scopes. No account was connected."
                )
            if not isinstance(result.get("access_token"), str):
                raise GoogleError("Google did not return usable credentials.")
            page = None
            account_label = None
            for _ in range(100):
                params = {"maxResults": 250}
                if page:
                    params["pageToken"] = page
                data = self.transport(
                    "www.googleapis.com",
                    "/calendar/v3/users/me/calendarList?" + urlencode(params),
                    token=result["access_token"],
                )
                account_label = next(
                    (
                        item.get("id")
                        for item in data.get("items", [])
                        if item.get("primary")
                    ),
                    None,
                )
                if account_label:
                    break
                page = data.get("nextPageToken")
                if not page:
                    break
            if (
                not isinstance(account_label, str)
                or not account_label
                or len(account_label) > 320
            ):
                raise GoogleError(
                    "Could not identify this Google calendar account. No connection was saved."
                )
            previous = self.vault.get("tokens")
            bound_account = self.vault.get("account")
            previous_label = (
                bound_account.get("label")
                if bound_account
                else (previous.get("account_label") if previous else None)
            )
            if previous_label and previous_label != account_label:
                raise GoogleError(
                    "Reconnect with the same Google account. To change accounts, disconnect first."
                )
            result["account_label"] = account_label
            result["connected_at"] = time.time()
            result["expires_at"] = time.time() + int(result.get("expires_in", 3600))
            self.vault.set("account", {"label": account_label})
            self.vault.set("tokens", result)

    def open_sign_in(self):
        url = self.begin()
        import webbrowser

        try:
            opened = bool((self.browser_opener or webbrowser.open)(url))
        except Exception:
            opened = False
        return {"authorization_url": url, "browser_opened": opened}

    def reject_callback(self, state):
        with self.lock:
            self.pending.pop(state, None)

    def disconnect(self):
        # Explicit disconnect releases the account binding; refresh failures do not.
        with self.lock:
            self.vault.delete("tokens")
            self.vault.delete("account")
            self.pending.clear()

    def _token(self):
        with self.lock:
            value = self.vault.get("tokens")
            if not value:
                raise GoogleError(
                    "Connect a Google account to synchronize calendars.", 401
                )
            if set(value.get("scope", "").split()) != SCOPES:
                raise GoogleError(
                    "Unexpected Google scopes. Reconnect the account.", 401
                )
            if value.get("expires_at", 0) < time.time() + 60:
                try:
                    refreshed = self.transport(
                        "oauth2.googleapis.com",
                        "/token",
                        form={
                            **self.vault.get("client"),
                            "refresh_token": value["refresh_token"],
                            "grant_type": "refresh_token",
                        },
                    )
                except GoogleError as exc:
                    if exc.status in {400, 401}:
                        self.vault.delete("tokens")
                    raise
                if "scope" in refreshed and set(refreshed["scope"].split()) != SCOPES:
                    raise GoogleError(
                        "Google scopes changed; reconnect with read-only access.", 401
                    )
                value.update(refreshed)
                value["expires_at"] = time.time() + int(
                    refreshed.get("expires_in", 3600)
                )
                self.vault.set("tokens", value)
            return value["access_token"]

    def get(self, path, params):
        return self.transport(
            "www.googleapis.com",
            "/calendar/v3/" + path + "?" + urlencode(params),
            token=self._token(),
        )

    def calendars(self):
        result = []
        page = None
        for _ in range(100):
            params = {"maxResults": 250}
            if page:
                params["pageToken"] = page
            data = self.get("users/me/calendarList", params)
            for c in data.get("items", []):
                if c.get("accessRole") in {"reader", "writer", "owner"}:
                    result.append(
                        {
                            "id": c["id"],
                            "name": c.get("summary", "Calendar")[:240],
                            "timezone": c.get("timeZone", "UTC"),
                        }
                    )
            page = data.get("nextPageToken")
            if not page:
                return result
        raise GoogleError("Too many calendars; choose a smaller test account.")

    def event_page(self, calendar_id, params):
        return self.get("calendars/" + quote(calendar_id, safe="") + "/events", params)
