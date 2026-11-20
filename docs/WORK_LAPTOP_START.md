# Install the work-laptop pilot

This is a testable macOS pilot, not a signed desktop installer. Use a new, permanent folder such
as `~/Applications/Airlock`; do not run it from Downloads, a synced folder, or a temporary directory.
The Python app and Ollama run on the Mac. Only the local PostgreSQL database runs in Docker.

## Before installation

Install approved Git, Python 3.13, Docker Desktop (including Compose), and Ollama. Start Docker
Desktop, complete its first-run setup, and enable its startup at login. The installer does not
install system software or accept software licenses. It downloads Python dependencies, a database
image and local model weights, so allow network access, several GB of disk space and time.

Use the tested `work-pilot` branch (recommended for updates), or the source-only archive.
The archive includes `AIRLOCK_BUILD.json` with its commit and per-file checksums. Its adjacent
`.sha256` verifies transfer integrity; it is not a publisher signature. Never transfer the personal
Mac's `.env`, data folder, Keychain, database, logs or existing pairing invitation.

Fresh installation with a privately supplied, single-use setup code (valid for up to 24 hours):

```sh
mkdir -p ~/Applications
cd ~/Applications
git clone --branch work-pilot --single-branch https://github.com/Perti-Laboratories/Airlock.git
cd Airlock
python3.13 scripts/work_laptop.py --check
python3.13 scripts/work_laptop.py --setup-code
```

The installer asks for the code in a hidden terminal prompt and shows the connector destination
before retrieval. Paste the code only there, never into the command line or a public issue.
It downloads an encrypted package over HTTPS, configures the Google Desktop registration in
Keychain and pairs this fresh workspace. No Downloads files are needed. It does not import account
tokens or personal workspace data, and does not enable sharing. You still sign into Google locally.
A code is a bearer secret: anyone holding it can redeem it first. Its deadline also applies to initial
pairing, including a configuration already downloaded into Keychain. Ask for a new code if it expires.
This release uses v2 codes; older codes must be reissued.

If retrieval succeeded but pairing was interrupted, the pending configuration stays in Keychain.
Retry before the deadline from this same installation with `.venv/bin/airlock setup`; do not reinstall
or delete data. To abandon pending setup, run `.venv/bin/airlock setup-cancel`. It confirms cancellation
with the connector before removing the pending Keychain entry. If offline, retry when online.
Cancellation does not delete Google settings, local data or an already established pairing; revoke an
established connection separately. After expiry, cancel pending setup and obtain a fresh code.
If the network failed after server consumption but before local storage, ask the operator to issue
a replacement. The server cannot return a consumed package a second time.

Without a code, omit `--setup-code` for local-only installation. A separately supplied Desktop JSON
can still be provisioned with `--google-client /absolute/path/to/client.json` instead.

The default timezone is America/New_York; use `--timezone Europe/London` (or another IANA name)
if needed. Add `--no-login` to skip automatic startup. Installation generates fresh local secrets,
creates a Work workspace, downloads qwen3:8b and nomic-embed-text, checks readiness, and installs
startup after login. It never enables sharing, signs into Google, or installs company memory. The setup-code option
pairs only the connector identified in the code; the Google-file option only prepares sign-in.
It refuses existing local state/volumes and occupied ports rather than reusing them.

Open **http://127.0.0.1:8741**. Keep this folder in place: background startup refers to it.
You can close Terminal. Airlock restarts after login and retries if Docker is still starting.
Under **Settings & Activity → General**, optionally enable **Keep syncing while plugged in**.
This uses an AC-only macOS sleep assertion while Airlock runs, without changing system preferences,
screen lock or display sleep. It defaults off and is preserved across normal updates. Battery mode
keeps normal sleep behavior. Leave the lid open and power connected for continuous operation.
Explicit sleep, closing the lid, shutdown, logout, network loss or organizational power rules can
still interrupt processing. Airlock catches up after waking; it cannot process while actually asleep.

## First local test (before real work data)

1. Confirm the workspace is empty and Sharing is paused. With a setup code it is paired but the connection is off.
2. Ask: “Remember that my test notebook is called Juniper.” Acknowledge the reply, then ask its name.
3. Upload a small synthetic document through **+** and ask a question about it.
4. Create a synthetic calendar event and a to-do with private notes. Verify both local records.
5. Restart with `./scripts/restart.sh`; verify memory and records remain.
6. Log out and back in, wait for Docker, and open Airlock without starting it in Terminal.
7. Run `.venv/bin/python scripts/pilot.py check`. It exits unsuccessfully if the app, database,
   local models or required tools are unavailable. Also try a real chat to check inference speed.

## Connect Google separately

This source package deliberately contains no Google app configuration or account tokens.
If setup-code enrollment succeeded, skip provisioning and click Connect Google. Otherwise, provision
the chosen Desktop OAuth app registration once using its separately supplied JSON:

```sh
.venv/bin/airlock google-provision /absolute/path/to/desktop-client.json
```

Then use **Settings & Activity → Connections → Connect Google**, sign into the intended work
account and choose calendars. Credentials stay in this Mac's Keychain. Google access is read-only.
Verify an event appears, a moved event updates, and a deleted event disappears. Selecting a calendar
does not authorize external release. See [Google setup](GOOGLE_SETUP.md) for registration details.

## Enable connected planner sharing later

Use a fresh connector identity for each node. Do not reuse another node’s invitation.
Provision a **new work-node connector identity and route it to an existing or new connected planner domain**; the current
connector pilot holds one pairing per deployment. Give this laptop only its node invitation, and
keep the separate harness credential with connected planner. This is still an operator setup step.

With setup-code enrollment the invitation is already imported. Otherwise import it in Sharing.
Check the destination, enable the connection, choose the
calendar/to-do rules, review a synthetic example, then unpause sharing. Verify the approved item
arrives in the correct connected planner domain and that pausing removes it. Return availability is optional
and must be explicitly enabled; it never writes to Google. Company memory stays disconnected for
this first work pilot: its existing prototype only supports a separate local demo service.

## Recovery and updates

From an installed Git checkout on `work-pilot`:

```sh
cd ~/Applications/Airlock
python3.13 scripts/update_work_laptop.py --check
python3.13 scripts/update_work_laptop.py
```

Do not pull new code before invoking the updater: it backs up the installed version before changing
the checkout. It requires the exact official HTTPS origin shown in the clone command, rejects Git URL
rewrites and HTTP redirects, refuses dirty or divergent source history, pins the fetched commit, removes this
installation's login supervision, stops its app/model processes, backs up the database to
`data/backups`, installs dependencies and migrations, and checks readiness before restoring login
startup. `.env`, Google Keychain entries, source selection and pairing counters are preserved.
Python dependencies install only from wheels matching the committed SHA-256 hashes, with locked
build tools and no additional build dependency downloads. The database image is pinned to a manifest
digest. These are integrity checks, not a publisher signature.
Use `--backup-dir /approved/encrypted/location` to choose another backup parent directory.

If an update fails, leave the workspace and backup in place. The updater does not roll code back
over an upgraded database. Fix the reported prerequisite, then run `./scripts/setup.sh`,
`./scripts/start.sh`, `.venv/bin/python scripts/pilot.py check`, and finally
`.venv/bin/python scripts/pilot.py login-install` if login startup was previously enabled.
For data recovery, restore into an empty workspace using `pilot.py restore-empty --path <backup>`;
external connections start disabled and pairing/cursors require reconciliation. A source-only archive
has no Git tracking branch: use a Git installation for the managed update flow.

Older pilots without the updater must first remove login supervision, stop the app, and make a backup
with `pilot.py backup --path <new-backup-folder>`, then use `git pull --ff-only origin work-pilot`,
`./scripts/setup.sh`, `./scripts/start.sh`, and the readiness/login commands above.

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

## Plugged-in acceptance check

Enable the General setting, plug in the Mac and confirm the status says it is keeping the Mac awake.
Lock the screen normally and leave the lid open. After the next polling interval, confirm the
connector's last receipt advances. Unplug and confirm Airlock reports normal battery sleep behavior.
Disable the setting and verify normal sleep resumes. Also test explicit sleep/wake: no sync is
expected during actual sleep, and data should catch up afterward. Do not change workplace lock rules.

## Local 0.12 follow-up checks

Use the managed updater above; no new setup code or Google sign-in is needed for an existing
paired installation. Refresh the browser after updating.

- A new task should say **Private — approve a title to sync**. Open **Sharing & actions → Review
  release**, review the prefilled title, and save. Notes are never included. Connection enablement,
  unpaused sharing and the To-dos type level must also allow it. “Released to connector” is a
  connector receipt, not proof that a separate planner has rendered the task.
- Enable incoming availability and confirm the red **External** legend and **Unavailable** blocks.
  The receiving planner selects other source domains; exclude the node's own domain and all
  returned projections to avoid echoing them.
- Upload a synthetic note with a durable fact. Sources shows extraction progress; Memory shows
  a candidate with an exact quotation and source link. Approve it and ask about the fact in chat.
- Import a synthetic Google event with a participant email. After background processing, check
  Contacts. Sync again to confirm no duplicate. Existing contact notes must remain intact.
- **Settings & Activity → General → Process local context automatically** pauses/resumes the
  extraction and attendee-routing worker. Background catch-up is gradual, especially on large calendars.


## Local 0.13 acceptance checks

After the normal update, reload the app and confirm version 0.13.0. Existing pairing and Google
sign-in stay in place. Ask chat to use **bold text**, bullets and inline code. “Skip company search”
only skips the optional company-memory service for that turn; local models remain the only models.
On To-dos, confirm the connected-task count and turn on Show finished to inspect Done/Archive.
Add a synthetic contact, then add the same email with a new note: one contact should contain both
notes. A plausible nickname may use local semantic matching; unclear identity should request details.
Remove the synthetic contact when finished. No new sharing permissions are required by this update.
