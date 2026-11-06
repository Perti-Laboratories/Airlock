# Roadmap

Implemented prototype: local chat, curated memory, source retrieval, document upload, calendar,
read-only Google ingestion, to-dos, contacts and bounded local agents. Optional connector exchange
publishes approved calendar/task projections and accepts generic availability. Connector 0.5.0 also
accepts automatic calendar/to-do mirrors from the recipient’s bound domain under the same type
ceilings, with source-owned edits, signed permissions and replay-safe replacement. A separate company
knowledge service demonstrates reviewed contribution and retrieval using local synthetic data.

Next work:

- Validate installation, sleep/offline recovery and sustained use on additional physical Macs.
- Signed/notarized distribution, dependency review and managed deployment guidance.
- Production company-memory deployment with employee identities, access controls and retention.
- Safer credential rotation and multi-device connector administration.
- Optional editing of permitted mirror fields, with per-object expected revisions and conflict UI.
  Current records have one authoritative source and read-only mirrors.
- Minimal reviewed notifications without message bodies or source credentials.
- Optional bounded remote task dispatch with separate local permission and result-release review.
- Additional providers, recurring to-dos and Windows support.

No planned integration should require either side to expose its full database or raw conversation.
