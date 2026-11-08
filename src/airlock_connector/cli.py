"""Connector administration is local to its host; never exposed to a harness."""
import argparse
import json
import os
import secrets
import uuid
from pathlib import Path
from airlock_contracts import keys
from .service import create_connector, initialize, store


def provision(directory, endpoint):
    from urllib.parse import urlsplit
    u=urlsplit(endpoint)
    if u.scheme not in {'https','http'} or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in {'','/'}:
        raise ValueError('Use a plain connector origin.')
    if u.scheme=='http' and u.hostname!='127.0.0.1':
        raise ValueError('HTTP is permitted only for loopback tests.')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if (directory/'config.json').exists():
        raise ValueError('Connector already initialized; existing credentials preserved.')
    private,public=keys()
    config={'pairing_id':str(uuid.uuid4()),'private_key':private,'public_key':public,
        'device_token':secrets.token_urlsafe(48),'harness_token':secrets.token_urlsafe(48),
        'pairing_code':secrets.token_urlsafe(48)}
    invitation={'endpoint':endpoint.rstrip('/'),'pairing_id':config['pairing_id'],'public_key':public,'code':config['pairing_code']}
    for name,value in [('config.json',config),('invitation.json',invitation),('harness.json',{'endpoint':endpoint.rstrip('/'),'token':config['harness_token']})]:
        path=directory/name
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: json.dump(value,f)
    binding = {'endpoint': endpoint.rstrip('/'), 'pairing_id': config['pairing_id'], 'public_key': public}
    (directory/'binding.json').write_text(json.dumps(binding))
    (directory/'binding.json').chmod(0o600)
    initialize(directory/'connector.sqlite3')
    return config


def main():
    parser=argparse.ArgumentParser(description='Independent Airlock Connector')
    parser.add_argument('command',choices=['init','serve','revoke'])
    parser.add_argument('--directory',required=True)
    parser.add_argument('--endpoint',default='http://127.0.0.1:8742')
    parser.add_argument('--port',type=int,default=8742)
    parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','0.0.0.0'])
    args=parser.parse_args();directory=Path(args.directory)
    os.umask(0o077)
    if args.command=='init':
        provision(directory,args.endpoint)
        print('Connector created. Import invitation.json in local Airlock. Give only harness.json to the harness. Keep config.json private.')
    elif args.command=='revoke':
        with store(directory/'connector.sqlite3') as db:
            db.execute('UPDATE state SET revoked=1,release_body=NULL,overlay_body=NULL,record_policy_body=NULL,records_body=NULL WHERE id=1')
            for table in ('board_feeds', 'board_moves'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    db.execute('DELETE FROM '+table)
        print('Pairing revoked; current connector projections removed. Copies already ingested by a harness cannot be recalled.')
    else:
        import uvicorn
        config=json.loads((directory/'config.json').read_text())
        uvicorn.run(create_connector(config,directory/'connector.sqlite3'),host=args.host,port=args.port,access_log=False,proxy_headers=False)


if __name__=='__main__':
    main()
