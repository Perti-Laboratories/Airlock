# Agent instructions

- Airlock is a standalone, single-domain local assistant; keep integrations product-neutral.
- Read README.md, SECURITY.md, docs/EXCHANGE_CONTRACT.md and docs/BACKLOG.md for scope.
- Keep local features useful without either optional connection.
- Use local Ollama; never silently fall back to a hosted model.
- Only the Memory Curator writes canonical memory; high-impact changes require review.
- Preserve provenance, stable identities, audit records and structured action reports.
- External recipients cannot alter release policy, access sources or execute arbitrary instructions.
- Keep outbound projections strictly allowlisted. Do not add new fields without contract and privacy tests.
- Use isolated test databases and synthetic data. Never commit credentials, logs, models or user data.
- Keep changes scoped, work against issues, and use draft pull requests until acceptance testing.
- State limitations plainly; do not claim security certification or zero risk.
