"""Manage the synthetic company Postgres/API. Never reuse Airlock or connected planner storage."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
FOLDER=ROOT/'data/company-demo'


def private(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream: stream.write(value)
    path.chmod(0o600)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','serve','status']);args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True,mode=0o700)
    config_path=FOLDER/'config.json';pidfile=FOLDER/'pid.json'
    if args.action=='serve':
        from sqlalchemy import create_engine,text
        from sqlalchemy.orm import sessionmaker
        from airlock.company_service import CompanyBase,create_company_app
        import uvicorn
        config=json.loads(config_path.read_text())
        engine=create_engine(config['database_url'],pool_pre_ping=True,hide_parameters=True)
        with engine.begin() as db: db.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        CompanyBase.metadata.create_all(engine)
        uvicorn.run(create_company_app(sessionmaker(engine,expire_on_commit=False),config),host='127.0.0.1',port=8744,access_log=False,proxy_headers=False)
        return
    owned=None
    if pidfile.exists():
        pid=json.loads(pidfile.read_text())['pid']
        command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout.strip()
        if str(ROOT/'scripts/company_demo.py')+' serve' in command: owned=pid
    if args.action=='status':
        print('Company prototype '+('running at http://127.0.0.1:8744' if owned else 'stopped'));return
    if args.action=='stop':
        if owned: os.kill(owned,signal.SIGTERM)
        pidfile.unlink(missing_ok=True)
        if (FOLDER/'postgres.env').exists():
            subprocess.run(['docker','compose','--env-file',str(FOLDER/'postgres.env'),'-f','company-compose.yml','stop'],check=True)
        print('Company prototype stopped; data retained.');return
    if owned: print('Company prototype already running at http://127.0.0.1:8744');return
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8744))==0: raise SystemExit('Port 8744 belongs to another process.')
    if not config_path.exists():
        from airlock.config import Settings
        from airlock.llm import LocalOllama
        llm=LocalOllama(Settings());models=llm.check_models();vector=llm.embed('Embedding compatibility probe')
        password=secrets.token_hex(32);token=secrets.token_urlsafe(48);company_id=str(uuid.uuid4())
        config={'endpoint':'http://127.0.0.1:8744','company_id':company_id,'name':'Synthetic company',
            'tokens':{token:company_id},'database_url':'postgresql+psycopg://company_demo:'+password+'@127.0.0.1:55434/airlock_company_demo',
            'embedding_spec':{'model':llm.embedding_model,'digest':models[llm.embedding_model],'dimensions':len(vector)}}
        private(config_path,json.dumps(config))
        private(FOLDER/'postgres.env','COMPANY_DEMO_DB_PASSWORD='+password+'\n')
        private(FOLDER/'invitation.json',json.dumps({'endpoint':config['endpoint'],'token':token}))
    subprocess.run(['docker','compose','--env-file',str(FOLDER/'postgres.env'),'-f','company-compose.yml','up','-d','--wait'],check=True)
    with (FOLDER/'server.log').open('ab') as log:
        os.chmod(FOLDER/'server.log',0o600)
        proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/company_demo.py'),'serve'],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    private(pidfile,json.dumps({'pid':proc.pid}))
    import httpx
    for _ in range(50):
        if proc.poll() is not None: raise SystemExit('Company service failed; check data/company-demo/server.log.')
        try:
            if httpx.get('http://127.0.0.1:8744/health',trust_env=False,timeout=1).status_code==200:
                print('Company prototype ready at http://127.0.0.1:8744. In Airlock choose Company memory → Connect local demo.');return
        except httpx.HTTPError: pass
        time.sleep(.2)
    raise SystemExit('Company service is still starting; check its local log.')


if __name__=='__main__': main()
