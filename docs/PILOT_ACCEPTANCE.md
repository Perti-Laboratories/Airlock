# Work-pilot 0.9 acceptance

Validated on the development Mac on 2026-11-18. This records observed prototype behavior,
not a security certification or a substitute for testing the destination laptop.

- Python regression suite: 170 passed; the additional successful-update ordering test also passed.
- Browser interface tests: 32 passed.
- Fresh source installation into a separate PostgreSQL container: dependency install, migrations,
  empty workspace, paused/unpaired defaults, real local Ollama embedding, memory and task creation passed.
- Real database backup and empty-database restore retained memory and private task notes. Restore
  disabled external connections in the restore transaction and refused an already populated database.
- Live HTTPS exchange with a deployed planning application: tasks created on each side appeared
  on the other side. Remote category moves converged through Working, Agent Action, In Review,
  Done and Archive. Private notes stayed at their source; Agent Action did not execute an agent.
- Pausing published an empty snapshot, the recipient applied withdrawal, and the temporary test
  domain and records were retired. Pairing/replay history was preserved.
- Earlier live calendar acceptance covered selected Google imports, field minimization, stable
  updates, cancellation, return records and withdrawal. Google writes remain unsupported.

The updater checks for a clean fast-forward checkout, stops this installation's login supervisor
and processes, backs up before changing code, then migrates and checks readiness. Automated tests
cover dirty/divergent checkouts, another installation's supervisor, backup failure, migration failure,
successful ordering and preservation of local settings. Failures never automatically restore old
pairing counters or roll code back over a newer database.

Still required on the destination Mac: approved prerequisites, Google account/SSO consent and
calendar selection, real chat latency, logout/login startup, sleep/wake recovery, and a synthetic
exchange through its own fresh pairing. Never copy the development workspace or its invitation.
Google verification status belongs to the selected app registration, not this source release.

This calendar/task pilot leaves context-window exchange disabled unless both connector and
recipient adapter support it. Production company-memory hosting and arbitrary remote agent dispatch
are outside this release. See [installation](WORK_LAPTOP_START.md) and [security](../SECURITY.md).
