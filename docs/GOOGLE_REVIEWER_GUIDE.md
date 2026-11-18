# Google Calendar review guide

Airlock is a standalone macOS desktop service, not an online account portal. The public website
provides product information and privacy disclosures; the Google integration runs on the reviewer's
Mac. No Airlock account, payment, phone verification, external planner or company-memory service
is required. Sign into Google with a reviewer-controlled account and synthetic calendar data.

## Install and connect

Prerequisites: Git, Python 3.13, Docker Desktop with Compose running, and Ollama installed.
Installation downloads Python dependencies, the PostgreSQL image and local model weights.
Use a fresh Mac installation folder with no existing Airlock instance or database volume.

The developer supplies the existing project's Desktop OAuth registration separately through the
verification correspondence. It identifies the application; it contains no Google user access or
refresh tokens. Do not publish that registration, use a different OAuth project for this review,
or import another user's database, `.env`, Keychain or connector invitation.

Save the supplied registration as `~/Downloads/airlock-desktop-client.json`, then:

```sh
mkdir -p ~/Applications
cd ~/Applications
git clone --branch work-pilot --single-branch https://github.com/Perti-Laboratories/Airlock.git
cd Airlock
python3.13 scripts/work_laptop.py --check
python3.13 scripts/work_laptop.py --no-login --google-client "$HOME/Downloads/airlock-desktop-client.json"
```

1. Open `http://127.0.0.1:8741` on that Mac.
2. Open **Settings & Activity → Connections → Google Calendar**. Read the disclosure next to
   **Connect Google**, then click it. The system browser performs Google consent with PKCE and a
   loopback callback. Expand both permission descriptions. The pending-verification warning may
   appear until this review is approved; this is not an Airlock login or paywall.
3. After consent, return to Airlock and click **Choose calendars**. Select a reviewer-controlled
   synthetic calendar, then **Sync now** for that source.
4. Open **Calendar** and locate the synthetic event in day/week/month view. Event details show
   Google provenance. Airlock cannot edit the source Google event.
5. Change the event's time in Google Calendar; synchronize again and verify the same local event
   updates. Cancel it in Google and verify it disappears after synchronization.
6. Ask a question about a synthetic imported event in chat. Reasoning is performed by local Ollama;
   no external AI API is needed. Model weights are not trained or fine-tuned on calendar data.
7. Confirm **Sharing** starts paused/unpaired. Google connection alone does not authorize an
   external release. Optional connector tests require a separately provisioned test connector;
   never use a user's live invitation.
8. Disconnect Google, then follow [data deletion](DATA_DELETION.md) for cleanup.

## Exact scopes and why they are needed

| Scope suffix (`https://www.googleapis.com/auth/`) | Feature | Why narrower access is insufficient |
| --- | --- | --- |
| `calendar.calendarlist.readonly` | List available calendars so the user can select sources; identify the connected account through its primary calendar | A single-calendar assumption cannot support the source selector or subscribed/shared calendars |
| `calendar.events.readonly` | Display selected events locally, refresh updates/cancellations and answer local schedule questions | Free/busy lacks event titles and event-level details; owned-only excludes subscribed/shared calendars selected by the user |

Cloud Console checked on 2026-11-18: calendar-list access is non-sensitive, event access is sensitive,
and no restricted scopes are configured. Runtime scopes match. No write, Gmail, Drive, Contacts,
Photos, Data Portability or YouTube API scopes are requested by Airlock.

Demo: https://youtu.be/xk6j8ZvAW2k (Unlisted). It shows Google consent with both permissions expanded,
calendar selection, read-only import of a synthetic event, sharing defaults and local model settings.
The demo uses a reconnect flow for the same Desktop client; no broader permission is requested.

## Optional recipients

The standard Airlock application invokes no hosted AI provider. Its separate optional connector
can deliver user-approved calendar fields to a user-selected planning application. Those fields
remain Google-derived data; minimization does not remove Limited Use obligations. Recipients must
use them only for the consented planning feature and must not send them to AI services that train
generalized models on the data. Review recipient terms, training opt-ins, storage and deletion before
enabling a connection. This is an operator requirement, not a claim that Airlock controls arbitrary
third-party software or can recall copies already received.

Privacy: https://airlock.perti.io/privacy
