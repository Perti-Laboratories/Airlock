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
- HTTPS validates the remote host. Ed25519 signatures, pinned keys, distinct device/recipient tokens,
  monotonic revisions and leases guard the exchange. Signatures do not encrypt stored plaintext.
- The laptop only makes outbound requests to its explicitly paired connector. No remote shell,
  arbitrary query interface or remote policy-editing endpoint is exposed.
- The return channel accepts only typed generic availability. It cannot modify source calendars,
  create canonical memory, run tools or return original event titles. Incoming tasks are not implemented.
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
