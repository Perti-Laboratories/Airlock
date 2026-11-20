# Roadmap

Implemented prototype: local chat, curated memory, source retrieval, document upload, calendar,
read-only Google ingestion, to-dos, contacts and bounded local agents. Optional connector exchange
publishes approved calendar/task projections and accepts generic availability. Connector 0.6.0 also
accepts automatic calendar/to-do mirrors from the recipient’s bound domain under the same type
ceilings, with source-owned edits, signed permissions and replay-safe replacement. The task board now supports source-confirmed category moves from either side. A separate company
knowledge service demonstrates reviewed contribution and retrieval using local synthetic data.

Calendar includes day/week/month views with stable source colors and local context windows.
Context is soft scheduling guidance, not busy time. Connector 0.7 adds independently opt-in
context projections, with titles optional and private details excluded. Outbound indicators show policy eligibility, not delivery receipts.

Setup-code enrollment now retrieves an encrypted, expiring Google registration and fresh connector
invitation without file transfer, leaving sharing paused. General settings include default-off
AC-only keep-awake without screen-lock changes. Local 0.11 / connector 0.9 harden enrollment
expiry and cancellation, patch dependency advisories, verify package hashes, pin the database image
and require the official HTTPS update origin (issue #21).

Local 0.12 adds evidence-backed local memory proposals and source embeddings, automatic Google
attendee contact routing, explicit task release/delivery status, and red External availability
(issue #23). Proposals need user review; existing explicit chat actions still route calendar, task
and contact changes. Company/connector restrictions and external allowlists are unchanged.

Next work:

- Validate installation, sleep/offline recovery and sustained use on additional physical Macs.
- Signed/notarized distribution, dependency review and managed deployment guidance.
- Production company-memory deployment with employee identities, access controls and retention.
- Safer credential rotation and multi-device connector administration.
- Optional editing of additional permitted mirror fields. Task column moves are implemented;
  titles, dates and private details remain source-owned.
- Minimal reviewed notifications without message bodies or source credentials.
- Optional bounded remote task dispatch with separate local permission and result-release review.
- Additional providers, recurring to-dos and Windows support.

No planned integration should require either side to expose its full database or raw conversation.
