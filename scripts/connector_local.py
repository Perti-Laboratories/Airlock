"""Own a loopback-only connector demo process; credentials never enter command arguments."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('command',choices=['start','stop','restart']);args=p.parse_args()
folder=root/'data/connector-demo';pidfile=folder/'pid.json'
executable=root/'data/connector-runtime/bin/airlock-connector'
if not executable.exists():raise SystemExit('Build and install the independent connector runtime first; see docs/CONNECTOR.md.')
folder.mkdir(parents=True,exist_ok=True,mode=0o700)
record=json.loads(pidfile.read_text()) if pidfile.exists() else None
owned=False
if record:
    command=subprocess.run(['ps','-p',str(record['pid']),'-o','command='],capture_output=True,text=True).stdout.strip()
    owned=str(executable) in command and str(folder) in command and ' serve ' in command
if owned and args.command in {'stop','restart'}:
    os.kill(record['pid'],signal.SIGTERM)
    for _ in range(50):
        command=subprocess.run(['ps','-p',str(record['pid']),'-o','command='],capture_output=True,text=True).stdout.strip()
        if str(executable) not in command:break
        time.sleep(.1)
    else:raise SystemExit('Connector is still stopping; retry shortly.')
    pidfile.unlink(missing_ok=True);owned=False
if args.command=='stop':raise SystemExit('Connector stopped; local data retained.')
if owned:raise SystemExit('Connector already running at http://127.0.0.1:8742')
import socket
with socket.socket() as sock:
    if sock.connect_ex(('127.0.0.1',8742))==0:raise SystemExit('Port 8742 belongs to another process; refusing to reuse it.')
if not (folder/'config.json').exists():subprocess.run([str(executable),'init','--directory',str(folder)],check=True)
with (folder/'server.log').open('ab') as log:
    (folder/'server.log').chmod(0o600)
    proc=subprocess.Popen([str(executable),'serve','--directory',str(folder)],cwd=folder,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,
        env={k:v for k,v in os.environ.items() if not k.startswith('AIRLOCK_') and k!='PYTHONPATH'})
pidfile.write_text(json.dumps({'pid':proc.pid}));pidfile.chmod(0o600)
print('Connector started at http://127.0.0.1:8742')
