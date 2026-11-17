# Roadmap

Implemented prototype: local chat, curated memory, source retrieval, document upload, calendar,
read-only Google ingestion, to-dos, contacts and bounded local agents. Optional connector exchange
publishes approved calendar/task projections and accepts generic availability. Connector 0.6.0 also
accepts automatic calendar/to-do mirrors from the recipient’s bound domain under the same type
ceilings, with source-owned edits, signed permissions and replay-safe replacement. The task board now supports source-confirmed category moves from either side. A separate company
knowledge service demonstrates reviewed contribution and retrieval using local synthetic data.

Calendar includes day/week/month views with stable source colors and local context windows.
Context is soft scheduling guidance, not busy time; it stays local and is excluded from the
current connector contract. Outbound indicators show policy eligibility, not delivery receipts.

Next work:

- Validate installation, sleep/offline recovery and sustained use on additional physical Macs.
- Signed/notarized distribution, dependency review and managed deployment guidance.
- Production company-memory deployment with employee identities, access controls and retention.
- Safer credential rotation and multi-device connector administration.
- Optional editing of additional permitted mirror fields. Task column moves are implemented;
  titles, dates and private details remain source-owned.
- Minimal reviewed notifications without message bodies or source credentials.
- Optional bounded remote task dispatch with separate local permission and result-release review.
- Optional context-window exchange with a separate reviewed disclosure policy and wire contract.
- Additional providers, recurring to-dos and Windows support.

No planned integration should require either side to expose its full database or raw conversation.
