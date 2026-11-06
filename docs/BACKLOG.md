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
- [Automatic domain-scoped calendar and to-do sync](https://github.com/Perti-Laboratories/Airlock/issues/1):
  eligible records created or updated in the connected planning domain flow back automatically,
  without a per-item send action. Apply the same per-type sharing ceilings in both directions;
  keep local notes private. Use stable shared IDs, origin tracking, version/conflict handling and
  acknowledgements. See the planned extension in [the exchange contract](EXCHANGE_CONTRACT.md).
  Not implemented in protocol v1; task synchronization never authorizes remote execution.
- Minimal reviewed notifications without message bodies or source credentials.
- Optional bounded remote task dispatch with separate local permission and result-release review.
- Additional providers, recurring to-dos and Windows support.

No planned integration should require either side to expose its full database or raw conversation.
