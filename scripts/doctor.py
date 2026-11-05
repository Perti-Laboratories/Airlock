"""Read-only workstation readiness check; never prints credentials or source content."""
import json
import platform
import shutil
import subprocess
import sys
import httpx
from pathlib import Path
from airlock.config import Settings
checks={'python_supported':sys.version_info>=(3,11),'platform':platform.system(),'architecture':platform.machine()}
checks.update({name:bool(shutil.which(name)) for name in ('docker','ollama','git')})
if checks['docker']:
    checks['docker_running']=subprocess.run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
settings=Settings()
try:
    with httpx.Client(base_url=settings.origin,timeout=5,trust_env=False) as c:
        c.get('/')
        status=c.get('/api/status').json()
        checks.update(database=status.get('database'),local_model=status.get('model_status'),version=status.get('version'))
except Exception: checks['app']='not running'
print(json.dumps(checks,indent=2))
ready = all(checks.get(k) is True for k in ('python_supported','docker','ollama','git','docker_running'))
ready = ready and checks.get('database') == 'ready' and checks.get('local_model') == 'ready'
raise SystemExit(0 if ready else 1)
