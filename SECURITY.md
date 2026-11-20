# Security model and limitations

Airlock minimizes approved disclosure between separate workspaces. It is not a mechanism for
bypassing organizational controls, a certified security boundary, or an automatic guarantee that
natural-language content is safe to disclose. Obtain the appropriate installation, source-access
and outbound-sharing permissions for the environment where it runs.

## Current controls

- Local app, PostgreSQL and Ollama listen on loopback. Browser writes require the local session,
  same-origin checks and CSRF protection. macOS Keychain holds provider and device credentials.
- The source-only distribution includes no user data, credentials or preconfigured remote pairing.
- External sharing starts paused. Device pairing and connection enablement do not approve release.
- Calendar and task fields pass deterministic schemas and local type/source/item rules before signing.
  A model cannot grant release permission. Notes, documents, contacts and memory are not in the
  external protocol. Reviewed titles still need human judgment about their content.
- Google-derived released fields remain subject to Limited Use restrictions. Recipient operators
  must not use them, or transfer them to AI services that use them, for generalized model training.
  Review the destination's terms and training opt-ins before enabling sharing. Field minimization
  cannot enforce an independent recipient's behavior or recall its retained copies.
- HTTPS validates the remote host. Ed25519 signatures, pinned keys, distinct device/recipient tokens,
  monotonic revisions and leases guard the exchange. Signatures do not encrypt stored plaintext.
- The laptop only makes outbound requests to its explicitly paired connector. No remote shell,
  arbitrary query interface or remote policy-editing endpoint is exposed.
- The v2 record channel requires a fresh node-signed permission and strict calendar/to-do schemas.
  Both the recipient adapter and connector enforce its type levels before delivery. Airlock checks
  the signature, permission, replay cursor and lease, and reapplies current levels on every read.
  Notes and details are excluded. Incoming mirrors cannot edit source calendars, become canonical
  memory automatically, execute tools, or enter the local outbound source list. Titles and details remain editable only at their source.
  Connector-informed responses are excluded from subsequent model history and automatic indexing.
  The exact text of a user-authored message may be indexed independently, with explicit provenance
  and no connector excerpts or response text; explicitly requested writes follow local permissions.
- Legacy incoming availability remains a separate optional channel with generic titles only.
- Optional company-memory contribution uses selected sources and reviewed candidates. Automatic
  company research sends bounded queries built from company topics rather than full private chat.
  Company-informed chat turns are read-only and excluded from normal reusable chat memory.

## Limits operators must understand

The local release engine can access private records and the outbound transport; it is not a separate
OS sandbox. Code execution as the same user, a compromised device, malicious dependencies or an
authorized recipient retaining released content are outside this application's guarantees.
Use appropriate disk encryption, device management, backups, identity controls and updates.
Local records/logs and connector storage are sensitive. Keychain storage is not encryption of the
whole database. Retention and backup policy remain the operator's responsibility.

Pause sends withdrawal when connected. Expiry prevents compliant clients from treating old data as
current; it does not erase copies from recipient databases or backups. Offline or sleeping laptops
cannot sync. Receivers must treat stale availability as unknown, never as free time.
OAuth permissions can cover more calendars than the local selection ingests. Read-only access still
requires authorization. No production OAuth application or company SSO configuration is bundled.
The company-memory service is a local prototype, without production employee ACLs or SSO.

## Reporting a vulnerability

Do not post credentials, private documents or exploit details in a public issue. Use this repository's
GitHub private vulnerability reporting feature when available. If it is unavailable, open an issue
requesting a private reporting channel without including the sensitive details. No response SLA or
independent security audit is claimed for this prototype.

## Task board moves (optional v3 channel)

Board sharing adds only a neutral column, opaque conflict token and already released task ID.
The source still owns the task. A mirror action queues a short-lived move intent; the source
checks current task permission, identity and expected token before committing the category
and a durable operation receipt together. Retried operations do not repeat the mutation.
Both device and recipient channels require their distinct bearer. Device publications and
moves are device-signed; responses are connector-signed and checked against the pinned key.

Titles, notes, descriptions, owners, workflow IDs and arbitrary instructions are absent from
this channel. Moving into Agent Action is categorization only: it grants no execution authority.
Active agent work on a recipient can reject a move. Expired, withdrawn, paused, disabled or
changed tasks cannot be silently overwritten. A pause cannot undo a move already applied.
Requests expire after at most 15 minutes; a permission renewal can reject a pending request
so the user must refresh and retry. Old clients retain coarse status sync and read-only mirrors.


Context-window exchange is separately off by default. Even generic context can disclose
scheduling preferences or a category such as childcare or location; those enums require
explicit opt-in, and titles require a higher disclosure level. Only the strict context
projection crosses the planning boundary. Private notes, literal locations, attendees
and source metadata are never included. Context is enforced as nonblocking in storage,
wire validation and adapters. See `docs/EXCHANGE_CONTRACT.md` for version requirements
and withdrawal/retention limits.

## Setup codes and power

An operator can issue a single-use setup code with a maximum 24-hour lifetime. The code contains a
256-bit random key and a connector origin. The host receives only an AES-GCM encrypted package and
a hash of a separately derived redemption proof. The client sends the proof in an HTTPS Authorization
header, never a URL; it does not send the decryption key. Atomic redemption removes the ciphertext
from the active record, rejects expiry/replay, and is disabled for bound or revoked connectors.
No enrollment-creation API is exposed to a recipient or the public. Host backups may retain encrypted
copies; compromise of both the package and its code reveals the setup registration and invitation.
Keep codes private. A stolen code can enroll an attacker's node first. This is secret-based enrollment,
not device attestation. Reissue after interrupted delivery requires operator action.

The installer uses a hidden interactive prompt, validates the embedded destination, rejects redirects,
disables ambient proxies, bounds responses and verifies authenticated encryption before applying data.
A retrieved but incomplete setup is retained in macOS Keychain for retry before its deadline.
Both the client and server enforce expiry at first binding. Each v2 grant has a distinct pairing secret;
replacement invalidates the old secret and legacy configuration invitations cannot bypass the grant.
An already bound identical device key can recover its receipt after expiry without changing identity.
Pending cancellation requires that invitation secret and server confirmation; it cannot revoke a
bound node. Consumed, cancelled and retired grants cannot be revived by reinstalling them. Existing OAuth registrations
and connector identities cannot be silently replaced. Enrollment never grants release permission and
never bypasses Google consent or workspace OAuth policies.

Keep-awake is default-off and requests only macOS's AC-only `caffeinate -s` assertion, tied to the
Airlock process lifetime. It does not alter screen lock, display sleep, login policy or persistent
system power preferences, and does not enable syncing during actual sleep. Workspace restore resets
this preference to off. Physical battery, lid-close and lock-screen checks remain installation tests.

## Release integrity

The pilot targets Python 3.13. Committed dependency locks include SHA-256 wheel hashes and build
tools; installs reject mismatched hashes, source distributions and unlisted dependencies. Local
packages build from the checkout without downloading isolated build dependencies. The database
and hosted Python base images are pinned to manifest digests. The updater verifies the exact official
HTTPS Git origin, rejects URL rewrites and fetch redirects, and backs up before changing the checkout.
These checks do not protect against compromise of the trusted repository or replace signed releases.
Maintainers refresh locks with `scripts/lock_dependencies.py`, which checks the dependency closure
and rejects versions with advisories listed by PyPI. This is a point-in-time check, not a guarantee
against undiscovered vulnerabilities.

## Automatic local context processing

Local 0.12 processes eligible user messages, uploaded documents and contact interaction notes
with local Ollama only. Source passages are embedded for retrieval. Extraction is bounded to one
passage per worker cycle, requires exact supporting quotations and creates reviewable proposals.
Only the local Memory Curator may promote a proposal into canonical memory and embed that memory,
after the user approves it. The source must still be available, unchanged and eligible at approval.
Deleting/excluding a source withdraws its pending candidates. Rejected candidates do not reappear
just because a job retries. Assistant-generated text is not evidence. Company-restricted sources
and connector-derived response/context text remain excluded from this general memory pipeline.
The exact original user message can be processed separately, even when the answer uses connector
context. Its source must match the stored user message byte-for-byte and carry direct-input provenance;
this exception never applies to company-restricted turns or assistant-generated text.

Calendar attendee routing uses provider fields, not model-generated identities. It ignores self
and resource attendees, uses the same local identity matching as manual/chat additions, preserves existing names/notes and respects
deleted-contact tombstones. It records invitation provenance; an invitation does not prove attendance
or authorize creating a meeting interaction. Contacts, candidates and source text never enter the
external planning protocol. Inferred to-dos/events are not silently executed from source documents;
chat's existing explicit-action validation remains in force. Disable processing under Settings &
Activity → General; existing memory and record data remain. This option does not enable sharing.


## Chat rendering and contact hygiene (local 0.13)

The Markdown renderer builds text nodes and allowlisted elements. Raw HTML is inert; images and
embedded media never load. Links allow only HTTP(S)/mailto and open without an opener or referrer.
Clicking a link still navigates outside the local app. Chat supports basic formatting, not all CommonMark.
The model transport revalidates the loopback Ollama endpoint per request, ignores HTTP proxy
environment variables and rejects redirects. There is no hosted-model fallback. “Skip company search”
only suppresses company-memory retrieval for that turn; it does not control model hosting or sync.

New contacts from the editor, chat and calendar attendee intake use email/phone (including aliases),
then a unique normalized full name, then a bounded local model comparison of up to eight similar
candidates. Conflicting known identities are excluded from fuzzy matching. Semantic enrichment
requires a model score of at least 0.80 and a 0.15 margin over another plausible match. These scores
are model judgments, not calibrated probabilities. Ambiguous matches or model failures stop creation;
calendar ingestion records them for review in the action report without blocking other attendees.
Deleted identities are not resurrected. Matching is bounded to 5,000 contacts and refuses unchecked
creation beyond that limit. Nicknames with no similarity to the stored name may miss the shortlist.

Enrichment preserves primary fields, stores alternate identifiers as local provenance, appends new
notes, retains source references, logs the match method and reindexes changed content locally.
Full notes refuse enrichment rather than truncate history. No contact field enters the external
planning protocol. Existing duplicates are not bulk merged, and imported review cases currently
require manually editing the intended contact; a dedicated merge/review screen remains future work.
