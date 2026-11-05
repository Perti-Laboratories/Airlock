"""Build a wheel containing only the connector and wire contract, never the local assistant."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='airlock-connector-build-') as tmp:
    stage=Path(tmp)
    shutil.copy(root/'connector/pyproject.toml',stage/'pyproject.toml')
    for package in ('airlock_connector','airlock_contracts'):
        shutil.copytree(root/'src'/package,stage/'src'/package,ignore=shutil.ignore_patterns('__pycache__'))
    subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--wheel-dir',str(root/'dist'),str(stage)],check=True)
