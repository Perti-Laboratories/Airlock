# Install the work-laptop pilot

This is a testable macOS pilot, not a signed desktop installer. Use a new, permanent folder such
as `~/Applications/Airlock`; do not run it from Downloads, a synced folder, or a temporary directory.
The Python app and Ollama run on the Mac. Only the local PostgreSQL database runs in Docker.

## Before installation

Install approved Git, Python 3.13, Docker Desktop (including Compose), and Ollama. Start Docker
Desktop, complete its first-run setup, and enable its startup at login. The installer does not
install system software or accept software licenses. It downloads Python dependencies, a database
image and local model weights, so allow network access, several GB of disk space and time.

Use either the Git checkout at the supplied commit SHA, or the source-only archive.
The archive includes `AIRLOCK_BUILD.json` with its commit and per-file checksums. Its adjacent
`.sha256` verifies transfer integrity; it is not a publisher signature. Never transfer the personal
Mac's `.env`, data folder, Keychain, database, logs or existing pairing invitation.

From the new Airlock folder:

```sh
python3.13 scripts/work_laptop.py --check
python3.13 scripts/work_laptop.py
```

The default timezone is America/New_York; use `--timezone Europe/London` (or another IANA name)
if needed. Add `--no-login` to skip automatic startup. Installation generates fresh local secrets,
creates a Work workspace, downloads qwen3:8b and nomic-embed-text, checks readiness, and installs
startup after login. It never enables sharing, pairs a recipient, connects Google, or installs
company memory. It refuses existing local state/volumes and occupied ports rather than reusing them.

Open **http://127.0.0.1:8741**. Keep this folder in place: background startup refers to it.
You can close Terminal. Airlock restarts after login and retries if Docker is still starting.
It cannot run while the Mac is actually asleep, and it does not change sleep settings.

## First local test (before real work data)

1. Confirm the workspace is empty and Sharing is paused/unpaired.
2. Ask: “Remember that my test notebook is called Juniper.” Acknowledge the reply, then ask its name.
3. Upload a small synthetic document through **+** and ask a question about it.
4. Create a synthetic calendar event and a to-do with private notes. Verify both local records.
5. Restart with `./scripts/restart.sh`; verify memory and records remain.
6. Log out and back in, wait for Docker, and open Airlock without starting it in Terminal.
7. Run `.venv/bin/python scripts/pilot.py check`. It exits unsuccessfully if the app, database,
   local models or required tools are unavailable. Also try a real chat to check inference speed.

## Connect Google separately

This source package deliberately contains no Google app configuration or account tokens.
Provision the chosen Desktop OAuth app registration once using its separately supplied JSON:

```sh
.venv/bin/airlock google-provision /absolute/path/to/desktop-client.json
```

Then use **Settings & Activity → Connections → Connect Google**, sign into the intended work
account and choose calendars. Credentials stay in this Mac's Keychain. Google access is read-only.
Verify an event appears, a moved event updates, and a deleted event disappears. Selecting a calendar
does not authorize external release. See [Google setup](GOOGLE_SETUP.md) for registration details.

## Enable connected planner sharing later

Use a fresh connector identity for each node. Do not reuse another node’s invitation.
Provision a **new work-node connector identity and a corresponding connected planner domain**; the current
connector pilot holds one pairing per deployment. Give this laptop only its node invitation, and
keep the separate harness credential with connected planner. This is still an operator setup step.

Import the new invitation in Sharing, check the destination, enable the connection, choose the
calendar/to-do rules, review a synthetic example, then unpause sharing. Verify the approved item
arrives in the correct connected planner domain and that pausing removes it. Return availability is optional
and must be explicitly enabled; it never writes to Google. Company memory stays disconnected for
this first work pilot: its existing prototype only supports a separate local demo service.

## Recovery and updates

If setup stops after creating `.env`, do not delete it or the database to retry. Complete the missing
prerequisite, run `./scripts/setup.sh` and `./scripts/start.sh`, then finish model download/readiness:

```sh
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NO_CLOUD=1 ollama pull qwen3:8b
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NO_CLOUD=1 ollama pull nomic-embed-text:latest
.venv/bin/python scripts/pilot.py check
.venv/bin/python scripts/pilot.py login-install
```

For a deliberate stop with login supervision installed, first run
`.venv/bin/python scripts/pilot.py login-remove`, then `./scripts/stop.sh`.
The database and all stored content remain. Install login startup again when ready.
Backups, reviewed updates, revocation and remaining acceptance gates are in the
[security model](../SECURITY.md). Before updates, remove login supervision so it cannot restart
the app during migrations. This package does not transfer personal data or automatically deploy
a new hosted connector, change Google publication status, or complete the physical work-Mac test.
