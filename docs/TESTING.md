# Testing

Use synthetic data and an isolated database. Never point test fixtures at an existing workspace.

After local setup, run `./scripts/test.sh` for the Python suite and
`node --test tests/ui_*.test.cjs` for browser logic tests (Node.js required).
The Python runner creates and uses exactly `airlock_test` within the local development database
container. Tests refuse another database name. The suite covers local records/memory, Google
transport, release rules, signatures, revisions, expiry, company research and packaging.

For the visible first-run test, follow [work-laptop setup](WORK_LAPTOP_START.md).
For bidirectional connector acceptance, follow [connector setup](CONNECTOR.md). Test title updates,
completion/reopening, withdrawal, pause, stale sources, retries, tampering and returning generic
availability. Verify private notes and document markers never appear in an external projection.

A passing automated suite does not establish workplace authorization, OAuth production verification,
performance on another computer or correctness on an organization's network. Test sleep/offline,
login startup, revocation, source lifecycle and actual recipient behavior separately.
