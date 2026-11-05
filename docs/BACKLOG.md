# Roadmap

Implemented prototype: local chat, curated memory, source retrieval, document upload, calendar,
read-only Google ingestion, to-dos, contacts and bounded local agents. Optional connector exchange
publishes approved calendar/task projections and accepts generic availability. A separate company
knowledge service demonstrates reviewed contribution and retrieval using local synthetic data.

Next work:

- Validate installation, sleep/offline recovery and sustained use on additional physical Macs.
- Signed/notarized distribution, dependency review and managed deployment guidance.
- Production company-memory deployment with employee identities, access controls and retention.
- Safer credential rotation and multi-device connector administration.
- Bidirectional task proposals: explicit target pairing, stable shared IDs, minimal approved fields,
  origin tracking, version/conflict handling and acknowledgements. Keep local notes private and
  never interpret a shared task title as an execution instruction. Not implemented in protocol v1.
- Minimal reviewed notifications without message bodies or source credentials.
- Optional bounded remote task dispatch with separate local permission and result-release review.
- Additional providers, recurring to-dos and Windows support.

No planned integration should require either side to expose its full database or raw conversation.
