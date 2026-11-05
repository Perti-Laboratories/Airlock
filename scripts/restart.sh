#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python scripts/manage.py restart
