"""User login supervisor: recover managed processes, never claim somebody else's port."""
import subprocess
import time
from pathlib import Path
import httpx
import os
from airlock.config import Settings
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
settings=Settings()
while True:
    try:
        with httpx.Client(trust_env=False,timeout=5) as client:
            app=client.get(settings.origin+'/health')
            model=client.get(settings.ollama_url+'/api/version')
            ready=app.status_code==200 and app.json().get('service')=='airlock' and model.status_code==200
    except Exception:
        ready=False
    if not ready:
        subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/manage.py'),'start'],cwd=ROOT)
    # A login can precede Docker readiness; retry, without deleting stored state.
    time.sleep(30)
