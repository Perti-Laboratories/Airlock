# Airlock

**Share only the planning information you choose. Keep the underlying domains separate.**

Airlock is a standalone, locally running assistant for a single workspace. It helps with chat,
calendar, to-dos, contacts and local document search. An optional, independently hosted connector
lets a planning application receive the minimum approved information needed for daily productivity
across otherwise separate domains. Each side keeps its own database, credentials and detailed context.

For example, a work calendar can release **busy times without meeting details**, and a selected task
can release a **reviewed title and completion status without its notes**. The receiving planner can
automatically return eligible **calendar events and to-dos from its connected domain**, using the
same saved type levels. Generic **Unavailable** blocks from separately selected calendars remain optional. Connecting the two does not grant access to either side's
full workspace.

## What can cross the boundary?

| Information | Current external-sharing behavior |
| --- | --- |
| Calendar | Off by default; approved busy blocks, or explicitly approved titles and times |
| To-dos | Off by default; individually reviewed titles/status, optionally approved due dates |
| Notes, documents, chat, saved memory, contacts and company knowledge | No external connector export |
| Incoming availability | Optional generic time blocks; no original titles or details |
| Incoming calendar events and to-dos | Automatic domain-scoped mirrors under the saved type levels; task columns can move from either side |
| Remote agent instructions | Not implemented; no remote execution API |

Local type levels constrain both directions. Source/item reviews additionally constrain local outbound release. Notes stay on their source side, and mirrors cannot be re-exported as new records.
Local rules determine what leaves. Pairing does not enable sharing. Pause withdraws the active
projection on the next successful exchange; leases limit how long disconnected recipients should
use it. These controls cannot recall information a recipient has already copied.

## How it works

```text
Local sources → Airlock's private workspace → explicit release rules
                                                ↓ outbound HTTPS
                                       Independent connector
                                                ↕
                                      Your planning application

Return: permitted domain records / optional availability → connector → Airlock polls and verifies
```

The laptop initiates the connection: no public laptop port, inbound webhook, tunnel or remote shell.
Live transport uses HTTPS with certificate verification. Separate device and recipient credentials,
signed snapshots, revision checks and expiring records constrain the exchange. Source credentials
remain on the local machine. With connector 0.6.0, an enabled, unpaused connection automatically
exchanges permitted domain records; no per-item send action is needed on the recipient side.
The task board has Backlog, Working, Agent Action and In Review, with Done and Archive available under Show finished. Moving a connected task queues a source-confirmed update; details remain editable only at source. Agent Action is categorization only across the connection and never starts remote work.
Updates normally converge within two polling cycles while both sides are awake and online. Local model inference and embeddings use Ollama, with no hosted-model
fallback. See [the exchange contract](docs/EXCHANGE_CONTRACT.md) and [security model](SECURITY.md).

**This is an early prototype, not a security certification or a data-loss-prevention guarantee.**
Approved titles can still contain sensitive information. Local software remains subject to the
organization's installation, source-access and data-release policies. Airlock does not bypass SSO,
OAuth restrictions, endpoint controls or workplace rules. A compromised host or authorized recipient
is outside the protection offered by this application-level boundary.

## Run locally on macOS

Install Git, Python 3.13, Docker Desktop with Compose, and Ollama. Start Docker Desktop first.
Use a permanent folder outside cloud-synced storage:

```sh
mkdir -p ~/Applications
cd ~/Applications
git clone --branch work-pilot --single-branch https://github.com/Perti-Laboratories/Airlock.git
cd Airlock
python3.13 scripts/work_laptop.py --check
python3.13 scripts/work_laptop.py --setup-code
```

Open **http://127.0.0.1:8741**. Setup creates an empty workspace with fresh local secrets,
downloads the local models, and configures startup after login. Docker must also start at login.
The app, model service and database bind to loopback. The Python app and Ollama run natively;
PostgreSQL/pgvector runs in Docker. The computer must be awake to process or sync. An optional **Keep syncing while plugged in**
setting prevents automatic AC sleep while Airlock runs; display sleep and screen lock remain intact.
Lid closure and explicit sleep can still pause processing.

Imported Google events with identical start and end times retain their exact timestamps as
nonblocking entries. They remain available locally and are excluded from planning releases.

With `--setup-code`, paste the privately issued expiring code at the hidden prompt. This retrieves
the Google registration and connector invitation without manually moving files; pairing remains
disabled and sharing paused. Omit the option for local-only installation. Setup does not sign into
an account or enable sharing. Google Calendar is optional and read-only;
[register/provision your OAuth client](docs/GOOGLE_SETUP.md), then sign in through the browser.
The source package contains no shared OAuth client, tokens or pairing credentials.
See [installation and first-run tests](docs/WORK_LAPTOP_START.md).

If supplied with a Desktop OAuth registration, pass
`--google-client /absolute/path/to/airlock-desktop-client.json` to the installer.
It provisions this Mac's Keychain so **Connect Google** is ready; account sign-in still happens locally.
The registration file is separate from the public source and contains no account tokens.

For an existing `work-pilot` checkout, run `python3.13 scripts/update_work_laptop.py --check`,
then `python3.13 scripts/update_work_laptop.py`. The updater backs up the database, stops login
supervision and owned processes, applies only a fast-forward release, migrates, checks readiness,
and restores login startup if previously enabled. Keep backups on an approved local encrypted disk.

## Automatic local context

Eligible messages, documents and contact notes are indexed with local embeddings. A background
Ollama process proposes durable memories with supporting quotations; review them in Memory before
they become canonical facts. Google calendar participants with valid emails become local contacts
without replacing your edits. Pause this processing in Settings & Activity → General. Restricted
company/connector context stays outside general memory extraction; only your exact original input
can be indexed separately when a reply uses connector context. None of this enables sharing.

Chat renders basic Markdown, including bold, lists and code. **Skip company search** skips
only company-memory retrieval for that message; every model and embedding still runs locally.
It does not pause connector or calendar synchronization. The task board shows connected and hidden
finished-task counts; enable **Show finished** to see Done and Archive.

Every new contact intake checks existing identities first, then uses local semantic matching for
similar names. A confident match enriches the existing contact, retaining primary details and
appending notes. Ambiguous identities require clarification. Calendar imports record unresolved
matches in Activity action details. This is matching assistance, not guaranteed identity resolution.

## Optional company knowledge prototype

A separate, opt-in company-memory connection can contribute reviewed memory candidates and retrieve
published knowledge for local chat reasoning. It is independent of external planning exchange.
Only selected local sources are eligible for contribution; there is no bulk upload of personal memory.
This build supports a local demonstration service backed by a separate PostgreSQL database.
Production company hosting, employee authentication and access controls remain future work.
See [company memory](docs/COMPANY_MEMORY_PROTOTYPE.md).

## Develop and integrate

- [Connector setup and reference client](docs/CONNECTOR.md)
- [Versioned exchange contract](docs/EXCHANGE_CONTRACT.md)
- [Testing](docs/TESTING.md) and [roadmap](docs/BACKLOG.md)
- [Security and limitations](SECURITY.md)

The bundled `airlock_core` package supplies local model, memory and calendar helpers. Its source is
included here; no other product or private repository is required. The connector can be built and
installed independently with `scripts/build_connector.py`.

## License

[MIT](LICENSE). You may use, modify and redistribute this project, including commercially, under
that license. Dependencies retain their own licenses. No warranty or fitness guarantee is provided.
