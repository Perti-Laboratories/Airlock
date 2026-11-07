# Airlock exchange contract — v1 releases and v2 return records

Status: implemented prototype. The executable schemas live
in `src/airlock_contracts`; the standalone receiver is `src/airlock_connector`. These packages do
not import the local assistant, its ORM or its model runtime. See `CONNECTOR.md` for setup.

## Product boundary

Airlock is a standalone local, single-domain service. The optional Airlock Connector is a separate
service with separate storage and credentials. Any harness can consume the connector API; local
Airlock neither identifies nor invokes that harness. Connecting a harness does not give it source access, Google credentials,
local memory/history, policy-editing authority, or an execution tool.

Local Airlock initiates all network calls. No incoming laptop webhook, database tunnel, shared
volume or direct source connector is used. Live deployment requires HTTPS. HTTP is permitted only
at literal 127.0.0.1 when explicit local-test mode is enabled. Calls do not follow redirects or use
ambient proxies. The personal test runs two processes under the same Mac user: this proves API and
storage separation, **not OS isolation against that user or a compromised host**. A work deployment
still needs separate deployment identities/permissions and review of the local release engine,
which currently has access to both private records and the outbound transport.

## Pairing and authority

One connector instance binds to one local Airlock and one harness credential. Run separate instances
for additional protected domains in this first version. A connector administrator initializes the
instance and supplies a private invitation containing its origin, pairing UUID, public signing key
and a random pairing code. The local owner imports it; Airlock creates an Ed25519 key in macOS
Keychain. Claiming the invitation binds the instance to that public key. Retry with the same key is
idempotent; a different key cannot replace it. The resulting device bearer stays in Keychain.

The harness gets a distinct bearer credential with projection reads, availability writes, and permission-constrained v2 record writes.
It never gets the device bearer, pairing invitation, or signing private keys. The connector admin's
configuration belongs only on the connector host. Revocation is an admin CLI operation and disables
both sides of that pairing. Replacing/rotating a pairing in place is not implemented: use a fresh
instance/workspace after deliberate migration. Restoring old database backups requires operator
reconciliation, not resetting revision counters silently.

## Signed snapshots and convergence

Version 1 intentionally uses complete bounded snapshots rather than per-record deltas. Each signed
release contains an opaque pairing ID, random message ID, monotonically increasing snapshot revision,
issue/expiry times, policy revision, aggregate source freshness and at most 2,000 released records.
Calendar coverage is the next 30 days; to-dos are the current explicitly approved local records.
A snapshot's lease is at most 15 minutes. No source names, source IDs or private record IDs cross.
An optional earliest source-observation timestamp describes approved source ingestion separately
from transmission. Fresh transport cannot make an old source observation fresh.

Each record has a random stable export UUID from a local-only mapping. Nonrecurring event moves keep
that ID; local recurring occurrences use separate IDs. A new snapshot atomically replaces the
connector's current set. Missing objects are withdrawn, covering cancellation, deletion, release
revocation, pause, stale sources and horizon rollover. The stored highest revision prevents an old
snapshot from restoring a withdrawn object. Same revision and exact signed document digest is an
idempotent retry; conflicting or older revisions are rejected.

Airlock commits an immutable signed outbox before transmission. It re-evaluates the current policy
and source state under the local mutation lock before sending; changed input replaces obsolete
unsent content with a higher revision. A lost receipt retries the identical package. The connector
atomically persists and applies the snapshot before returning an applied receipt bound to message
ID and revision. This receipt means applied to **connector storage**, not to a downstream harness.
The harness must implement and report its own successful application to its data model.

Airlock checks exchange about every 30 seconds while running, renews unchanged leases about every
two minutes, and retries errors with bounded backoff. Google ingestion is separately about every
five minutes; exchange runs independently of local model inference. There is no real-time SLA. Offline/sleep prevents
updates. Once a release expires, the connector feed returns no items and marks itself stale;
harnesses must honor expiry even while their own connection is down. Keep stale availability
visible as uncertainty, never as proof of free time.

## Allowed content

Calendar records contain only `kind=calendar`, export UUID, released title, busy=true, all-day flag,
start/end and IANA timezone. Timed values require UTC offsets; all-day dates use an exclusive end.
Intervals must be ordered and at most 366 days. Titles are at most 160 characters. Local calendar
rules remain private by default, with busy-only, explicitly authorized original titles and reviewed
replacement titles. Event exceptions bind to event/policy revisions. Free/declined or stale-source
events are not published. Preview wrappers contain local review information and never enter the wire.

Todo records contain only `kind=todo`, export UUID, reviewed fixed title, status and optional due time.
Shared statuses are: `open`, `done`, `archived`. There is no workflow execution authority.
A per-to-do review approves a fixed public title and ongoing status updates; optional due-time
permission includes future due changes. Local title/detail changes invalidate review and withdraw
until reviewed again. Descriptions, owner, priority, source references and private metadata stay local.
The master release pause covers both calendar and to-do content.

All levels reject additional fields. Signatures cover the exact UTF-8 document bytes carried in the
wrapper, using Ed25519 via cryptography. Receivers verify before parsing the inner document, reject
duplicate JSON keys, enforce direction/pairing/lifetime/revision and bound HTTP bodies at 1 MB.
Do not interpret released titles as agent instructions. A harness still needs normal untrusted-data
handling; the release gate is a disclosure boundary, not a claim to solve prompt injection.

## Minimal incoming availability

A harness may replace a set of up to 500 typed availability blocks through its own credential.
Only opaque ID, the literal title **Unavailable**, start/end, all-day flag and timezone are accepted.
No personal titles, attendee lists, instructions, URLs or arbitrary metadata are accepted. Optimistic
revision checks prevent concurrent harness updates overwriting each other accidentally. The connector
signs the inbox snapshot with its own key, independently from the local Airlock signing key.

Local incoming availability is disabled by default. If the owner enables this standing class,
Airlock polls, verifies, applies and acknowledges it. It is a separate expiring overlay: it cannot
edit/cancel a local event, write Google, create canonical memory, grant execution or be re-exported.
The harness must renew its snapshots within 15 minutes. Disabling inbound hides/clears local overlay
content. Empty snapshots withdraw the layer. Expired content is omitted from active calendar context.
Conflicts remain visible; neither side automatically moves source-owned meetings.

## HTTP API

| Endpoint | Credential | Meaning |
| --- | --- | --- |
| POST /v1/pair | Private invitation | Bind device public key; return device bearer |
| POST /v1/releases | Device | Validate/apply signed release snapshot; durable applied receipt |
| GET /v1/inbox | Device | Current signed availability snapshot |
| POST /v1/inbox/ack | Device | Acknowledge locally applied inbound revision |
| GET /v1/harness/projections | Harness | Full released set, revision, expiry and freshness |
| GET /v1/harness/availability | Harness | Current outbound overlay revision and device acknowledgement |
| PUT /v1/harness/availability | Harness | Replace availability with expected_revision and typed items |

No API grants remote execution, arbitrary queries, policy changes, source access or connector admin
rights. Browser cross-origin access is rejected; bearer credentials belong in the harness backend.
A minimal Python client is included. MCP is optional future harness-side packaging, not required for
this HTTP interface and not a replacement for authentication.

## Retention and limits

The connector retains only its latest active release/inbound documents and revision/hash cursors;
replacements remove older application-visible content. SQLite secure_delete is enabled, but backups,
OS storage and a harness's own copies are separate retention obligations. Expired current snapshots
remain in connector storage until replacement/revocation, although the feed hides them. Local audit,
source records and signed outbox are retained locally. No guarantee can recall plaintext already
received by another party. Disabling exchange stops connections; use the master release pause while
connected to send a withdrawal first. Otherwise the current receiver view expires within 15 minutes.

Production TLS hosting, managed installation, key rotation, multi-pair hosting, stronger process
isolation for the local publisher, recipient application/withdrawal hooks and workplace approval
remain separate work. Remote agent dispatch, notifications, Gmail, contacts, external calendar writes
and recurring to-dos are not implemented by this slice.

## Type-level release controls (0.5.3)

Sharing now has a local disclosure ceiling for each record type. These controls affect only
external harness exchange; company-memory candidate submission remains a separate reviewed path.

| Type | Choices | Additional approval required |
| --- | --- | --- |
| Calendar | Off; time blocks only; titles + time blocks | Source rule or current event exception |
| To-dos | Off; reviewed title + status; reviewed title + status + due dates | Current per-to-do title review; due date also needs individual permission |
| Contacts | Always private | No outbound format implemented |
| Saved memories | Always private | No outbound format implemented |
| Company memory | Always private | Never included in harness exchange |

A calendar time block retains the literal title `Busy`, interval, timezone and all-day flag.
The title level permits the source's approved title mode or a reviewed replacement, never details.
Type off wins over all item approvals; time-only wins over even a fresh reviewed title exception.
To-do notes remain local at every level. To-do status is part of the minimum task projection, so
there is no title-only status-free task format. A due-date ceiling does not grant a due-date review.
Turning a type back on reuses valid source/item approvals; it does not approve all its records.
As before, saving a policy revision requires event exceptions to be reviewed again.

`GET/PUT /api/release-policy` includes `type_rules` with fixed keys `calendar`, `todo`, `contacts`,
`memory`, `company_memory`. Calendar accepts `private|busy|original`; to-do accepts
`private|title|title_due`; the remaining types accept only `private`. Unknown types and levels
are rejected. Omitted keys within a supplied `type_rules` object default to private.
The receiver contract remains version 1: filtering occurs locally before signing.

Migration 0009 preserves existing source rules, per-item reviews, pause state and policy revision.
Existing policies receive the historical calendar/title and reviewed-task/due ceilings; these
ceilings do not broaden the underlying approvals. New UI workspaces start with all types off.
Older API clients omitting `type_rules` retain saved ceilings; only their first policy save uses
the historical ceilings for compatibility. Downgrading the schema pauses outbound sharing.

Turning a type off withdraws its active records on the next successful snapshot, normally within
30 seconds while awake. Offline delivery cannot revoke already received data: the active receiver
view expires within 15 minutes, and downstream copies cannot be recalled.

### Personal acceptance test

1. In Sharing, turn Calendar on with **Time blocks only**, and allow a synthetic calendar source
   under **Calendar sources & limits**. Turn To-dos on with **Reviewed titles + status**. Save rules.
2. Review one synthetic to-do for sharing, with private notes and an optional due date. Resume
   outbound sharing if paused; choose **Sync now** under connection options.
3. Open the reference harness: events read `Busy`, the reviewed task title/status is present, and
   its due date and private notes are absent. Contacts and both memory types never appear.
4. Change To-dos to include due dates, save and sync. Only individually approved due dates appear.
5. Turn To-dos off, save and sync. Tasks disappear from the receiver while eligible calendar
   blocks remain. Then turn Calendar off and confirm its blocks disappear too.
6. Select the desired final policy and save. Restoring a type does not restore stale event reviews.

Automated coverage verifies these projections at the separately instantiated receiver, including
lost-receipt retries, stable identities, incompatible levels, legacy-client preservation and migration.


## Connector 0.4.0 signed harness read

`GET /v1/harness/release` requires the separate harness credential and returns exactly
`{"snapshot": <Signed ReleaseSnapshot or null>}`. The connector signs its admitted, unchanged
projection document with the connector key pinned by the harness. The device identity is still
verified when admitting the original release. The harness trusts the paired connector, not a
self-described key in the response. An expired signed document may be returned so the harness
can advance its cursor and withdraw its records; it must never display expired items.

Recipient adapters must implement atomic replacement, replay/conflict rejection, stable domain-scoped
IDs, and lease checks in their UI/API/model retrieval. Reconcile only connector-owned records, never
unrelated records in an existing domain. The optional return channel
contains only generic availability, not commands. TLS protects transport confidentiality; signing
does not encrypt approved plaintext stored by the connector or recipient.


## Automatic domain synchronization — connector 0.5.0

Tracking: [automatic domain-scoped calendar and to-do synchronization](https://github.com/Perti-Laboratories/Airlock/issues/1).
The v1 endpoints remain compatible. The v2 channel returns typed calendar/to-do records without
changing v1 availability. Upgrade the connector and recipient adapter before updating the node.
Older connectors continue serving v1; the node shows an upgrade-required return status.

Once a connection is enabled and sharing is unpaused, eligible native records in the bound recipient
domain automatically queue for Airlock under the saved type ceilings. No per-item send instruction.
The initial snapshot includes existing eligible records in that domain; later changes reconcile it.
Only calendar time blocks/title and to-do title/status/optional due date can cross. Other types,
notes, descriptions, attendees, source credentials and raw source IDs are excluded.

| Local type level | Recipient-to-node projection |
| --- | --- |
| Calendar private | No calendar records |
| Calendar busy | Times and literal Busy |
| Calendar original | Title (up to 160 characters) and times |
| To-do private | No to-dos |
| To-do title | Title (up to 160 characters) and open/done/archived status |
| To-do title_due | The same plus due date |

Local source/item reviews additionally constrain outbound release; an incoming item never grants
broader export authority. Pause or disabling a type hides its mirrors immediately on local reads.
Restoring permission requires a fresh snapshot rather than reviving withdrawn records.

### Permission, delivery and application

- `POST /v2/record-policy` (device credential): node-signed `RecordPolicy`, schema 2, direction
  `record_policy`, monotonic revision, message ID, pairing, issue/expiry and `rules`. No content.
- `GET /v2/harness/records` (harness credential): connector-signed attestation of that policy,
  current return revision and acknowledged revision. The adapter verifies its pinned key/audience.
- `PUT /v2/harness/records` (harness credential): `expected_revision`, `policy_message_id`, and up to
  2,000 strict calendar/to-do projections. The adapter filters before transport; the connector
  rejects fields/records exceeding permission, expired grants, duplicate IDs and stale revisions.
- `GET /v2/records` (device credential): connector-signed `RecordSnapshot` with direction `records`,
  schema 2, monotonic revision, permission message ID and a lease no longer than the permission.
- `POST /v2/records/ack` (device credential): acknowledges the durably applied revision. The connector
  separately reports queued and node-acknowledged revisions; delivery is not mistaken for application.

Every permission/record envelope has at most a 15-minute lease. New permissions invalidate queued
packages; unchanged permission renewals may retain the already admitted local mirror until its
original lease expires. A null inbox means awaiting a snapshot, not deletion; an explicit empty
snapshot withdraws all mirrors. Old/conflicting revisions cannot restore withdrawn records.
The node persists its cursor before acknowledgement and retries after lost receipts. Unchanged
recipient snapshots renew roughly every two minutes; changed records are checked every 30 seconds.
Two polling cycles is a typical convergence time, not an SLA. Offline/sleep means stale, never free.

### Ownership and isolation

Each record has one authoritative source. Updates, completion and deletion happen at that source;
titles and details on its mirror are read-only. Optional v3 board moves request a source-owned category change. A full snapshot atomically replaces only that connection's mirror set.
Expected snapshot revisions reject concurrent writers; no LLM or last-write-wins merge is used.
Recipient adapters derive opaque stable export IDs scoped to pairing, domain, type and source
record; recurring occurrences have distinct identities. Imported node projections are excluded
from return selection. Local return mirrors are stored separately from source/release tables and
are available to the calendar, to-do list and chat without being eligible for re-export.

Reassigning the recipient domain replaces the next snapshot with the new domain's eligible set.
The adapter serializes source selection and transmission with route changes; old in-flight data
may remain visible until reconciliation or lease expiry, but is never relabeled as new-domain data.
Native records and private notes in either domain are preserved. The recipient must not retain an
independent stale outbox after rebinding. Calendar coverage is the next 30 days, including bounded
recurrence expansion; unsupported recurrence must fail explicitly rather than guess occurrences.

Incoming calendar records exist only in Airlock. There are no Google writes, source-calendar edits,
remote execution instructions or database tunnels. Only the optional v3 task-column operation can change a mirror’s source; arbitrary mirror editing is unsupported.

### End-to-end acceptance

1. Bind an upgraded recipient adapter to a domain with only synthetic records for this test.
2. Pair the node, enable the connection, choose Calendar time blocks and To-dos title/status, and
   resume sharing. Create a recipient-domain event and task with a unique private phrase in notes.
3. Within two polling cycles, Airlock shows Busy and the task title/status. No private phrase,
   original meeting title or due date appears in the wire, mirror, calendar, to-do list or chat.
4. Edit the source event time, complete the source task, then cancel/delete them. Verify stable
   mirror identities followed by withdrawal. Native Airlock records remain unchanged.
5. Switch levels, pause/resume, disconnect/reconnect and move the recipient binding to another
   synthetic domain. Verify field minimization, stale state, fresh reconciliation and no duplicates.
6. Review/release one native Airlock task and calendar item. Confirm the recipient receives them
   and does not send them back as new records. Mirror titles/details cannot be edited or approved for release.

## Optional task board protocol — connector 0.6.0 / local 0.8.0

The v1/v2 wire documents remain unchanged. `/v3/{role}/board` (GET/POST),
`/v3/{role}/moves` (POST) and `/v3/{role}/receipts` (POST) form a separate sidecar;
role is `device` or `harness`, authenticated with that role’s existing bearer.
Device board publications and move requests use signed envelopes. Harness writes use its
backend credential; the connector signs all inbox responses for the receiving peer.

A board snapshot contains only already permitted task export IDs, a neutral column and a
64-character opaque version token. `basis_revision` ties it to the current v1 release or v2
return snapshot. It has its own monotonically increasing revision and at most a 15-minute
lease. Unknown fields, unshared IDs, wrong roles, duplicate IDs, stale revisions and conflicting
same-revision bodies are rejected. Columns are `backlog`, `working`, `agent_action`,
`in_review`, `done`, `archive`. Legacy coarse statuses still travel in v1/v2 for old clients.

A move contains an operation UUID, export ID, destination column, expected source token,
current permission revision and expiry. At most 100 uncompleted live requests are accepted.
The receiver validates its current source and permission, commits the task change with a
local deduplication receipt atomically, then acknowledges `applied`, `conflict`, `rejected`
or `expired`. A lost acknowledgement retries the receipt without repeating the source edit.
The mirror stays in its confirmed column while pending. Subsequent snapshots provide the
confirmed new column. There is no last-write-wins merge and no echo as a new task.

The connector keeps operation receipts for a bounded one-day retry window (pruned on new
moves) and returns at most 200 recent receipts. Peers retain processed operation receipts for
one day beyond the original request lease. A replay after pruning fails its expired envelope.
Permission changes or renewals can invalidate a queued request; refresh and retry deliberately.
Pause/type-off/disconnect immediately disable local mirror actions and cancel unsent intents.
A disconnected recipient cannot instantly learn a policy change; the node rechecks current
permission before applying, and every permission expires. Moves already applied cannot be recalled.

Agent Action is a board category across the boundary, never a workflow dispatch. A recipient
must not interpret the column or a released title as permission to execute. Source-specific
active workflow protections still apply. No task notes, descriptions, source IDs, credentials,
contacts or memory enter this channel.

Acceptance: create and review a synthetic local task with private notes; verify each column
arrives at the recipient. Move its mirror back through Working, Review, Done and Archive,
verify source confirmation and preserved notes. Repeat with a recipient-created task. Interrupt
receipt delivery, make a concurrent source edit, withdraw a task and pause sharing. Confirm
exactly one application, explicit conflicts/rejections, no duplicates and no private notes on wire.
