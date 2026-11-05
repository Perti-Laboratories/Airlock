#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
PYTHON_BIN="${AIRLOCK_PYTHON:-python3}"
command -v docker >/dev/null || { echo 'Install Docker Desktop first.'; exit 1; }
command -v ollama >/dev/null || { echo 'Install Ollama first.'; exit 1; }
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import secrets, sys, os, json
from zoneinfo import ZoneInfo
if sys.version_info < (3, 11): raise SystemExit('Python 3.11 or newer is required.')
p=Path('.env')
if not p.exists():
    password=secrets.token_hex(24)
    port=int(os.environ.get('AIRLOCK_DB_PORT','55433'))
    if not 1024 <= port <= 65535: raise SystemExit('Invalid local database port.')
    workspace=os.environ.get('AIRLOCK_WORKSPACE_NAME','Local workspace')
    zone=os.environ.get('AIRLOCK_WORKSPACE_TIMEZONE','America/New_York')
    ZoneInfo(zone)
    if not workspace.strip() or any(c in workspace for c in '\r\n\x00'):
        raise SystemExit('Use a nonempty, single-line workspace name.')
    p.write_text(f'AIRLOCK_DB_PORT={port}\nAIRLOCK_DB_PASSWORD={password}\nAIRLOCK_DATABASE_URL=postgresql+psycopg://airlock:{password}@127.0.0.1:{port}/airlock\nAIRLOCK_SESSION_SECRET={secrets.token_hex(32)}\nAIRLOCK_WORKSPACE_NAME={json.dumps(workspace)}\nAIRLOCK_WORKSPACE_TIMEZONE={json.dumps(zone)}\n')
    p.chmod(0o600)
Path('data').mkdir(exist_ok=True, mode=0o700)
PY
[ -d .venv ] || "$PYTHON_BIN" -m venv .venv
.venv/bin/python scripts/vendor_core.py
.venv/bin/pip install -r requirements.lock ./vendor/airlock_core '.[dev]'
docker compose up -d --wait
.venv/bin/alembic upgrade head
.venv/bin/airlock init
.venv/bin/airlock google-provision
printf '\nSetup complete. Run ./scripts/start.sh, then open http://127.0.0.1:8741\n'
