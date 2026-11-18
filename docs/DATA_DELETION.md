# Stop access and delete local data

Disconnecting Google, hiding a chat message, withdrawing a shared projection and deleting a workspace
are different operations. Airlock does not currently offer a one-click, source-specific purge of all
Google-derived chat history. The full-workspace procedure below deletes all local workspace records.

## Stop access without deleting the workspace

1. If sharing is enabled, **pause sharing while still connected**. Wait for a successful exchange
   receipt and confirm withdrawal in the receiving application, then disable the connection.
   An offline recipient may retain its prior view until lease expiry; independent copies/backups
   require deletion by that recipient's operator.
2. In **Settings & Activity → Connections**, disconnect Google. This removes local Google account
   tokens and pauses ingestion. Imported events, notes and chat history remain stored locally.
3. Revoke Airlock in [Google Account connections](https://myaccount.google.com/connections) to
   revoke the Google-side authorization too.

## Erase the entire standard local installation

This permanently removes **all** local calendar records, conversations, memories, documents, tasks,
contacts and audit records in the selected workspace, including non-Google data. Export anything
you intend to retain first. Do not run these commands against a shared/custom database installation.

From the exact installation folder (normally `~/Applications/Airlock`):

```sh
cd ~/Applications/Airlock
.venv/bin/python scripts/pilot.py login-remove
./scripts/stop.sh
docker compose ps
docker compose config --volumes
```

Confirm this is your intended local Airlock installation and its `airlock-local` database container
and volume. Only then remove that installation's containers and database volume:

```sh
docker compose down --volumes
```

In Finder, remove that installation's `data` folder (including local backups), any separate backup
copies/exports, and logs you retained. Remove the installation folder if uninstalling. If the folder
was backed up by Time Machine or another system, follow that backup system's retention/deletion
process too; deleting live files does not erase historical backups.

Disconnect optional connections and remove only this installation's Airlock credentials in macOS
Keychain Access when uninstalling. Preserve unrelated applications' credentials. Never restore a
deleted workspace's old pairing counters into an active connector; a new installation needs deliberate
reconciliation or a fresh pairing. Model weights contain no workspace records and may be retained.

These steps remove application-accessible data, not a guarantee of forensic secure erasure of storage
media. Disk encryption and device/backup disposal policies remain necessary. Hosted connectors and
receiving applications store data separately; ask their operators to remove retained copies.
