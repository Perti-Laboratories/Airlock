#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Create only the explicitly isolated test database inside this project's container.
if ! docker compose exec -T postgres psql -U airlock -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='airlock_test'" | grep -q 1; then
  docker compose exec -T postgres createdb -U airlock airlock_test
fi
export PYTHONPATH="$PWD/src"
exec .venv/bin/python - <<'PY'
import os
from sqlalchemy.engine import make_url
from airlock.config import Settings
import pytest
u = make_url(Settings().database_url).set(database='airlock_test')
os.environ['AIRLOCK_TEST_DATABASE_URL'] = u.render_as_string(hide_password=False)
raise SystemExit(pytest.main(['-q']))
PY
