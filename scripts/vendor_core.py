"""Verify the bundled core against its reviewed source manifest."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'vendor/airlock_core'
MANIFEST = ROOT / 'vendor/airlock_core.lock.json'
files = {str(p.relative_to(TARGET)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(TARGET.rglob('*')) if p.is_file()
         and not any(x in {'__pycache__', 'build', 'dist'} or x.endswith('.egg-info')
                     for x in p.relative_to(TARGET).parts)}
if files != json.loads(MANIFEST.read_text())['sha256']:
    raise SystemExit('Bundled core differs from its reviewed manifest.')
print('Bundled core source checksums verified.')
