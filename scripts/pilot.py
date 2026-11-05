"""Workstation operations. Never copies credentials, model files or personal state."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from datetime import datetime, UTC

ROOT=Path(__file__).resolve().parents[1]
LABEL='io.perti.airlock'


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def login_plist(root=ROOT):
    # launchd does not inherit the interactive shell's Homebrew/Docker PATH.
    paths = ['/usr/bin', '/bin', '/usr/sbin', '/sbin']
    for tool in ('docker', 'ollama'):
        executable = shutil.which(tool)
        if not executable:
            raise SystemExit(f'{tool} must be installed before configuring login startup.')
        parent = str(Path(executable).absolute().parent)
        if parent not in paths:
            paths.insert(0, parent)
    return {'Label': LABEL, 'ProgramArguments': [str(root/'.venv/bin/python'),str(root/'scripts/supervise.py')],
        'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,
        'EnvironmentVariables': {'PATH': ':'.join(paths)},
        'StandardOutPath':str(root/'data/login.log'),'StandardErrorPath':str(root/'data/login.log')}


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['check','login-install','login-remove','backup','restore-empty'])
    parser.add_argument('--path',type=Path)
    args=parser.parse_args()
    if args.action=='check':
        run([sys.executable,str(ROOT/'scripts/doctor.py')]);return
    if args.action.startswith('login-'):
        if sys.platform!='darwin': raise SystemExit('Login startup currently supports macOS only.')
        folder=Path.home()/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(LABEL+'.plist')
        if args.action=='login-remove':
            subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
            target.unlink(missing_ok=True)
            print('Login startup removed; app and stored data retained.');return
        configuration = login_plist()
        if target.exists():
            if plistlib.loads(target.read_bytes()) == configuration:
                print('Login startup is already configured for this installation.');return
            raise SystemExit('Login startup belongs to another configuration; remove it explicitly before replacing it.')
        (ROOT/'data').mkdir(mode=0o700,exist_ok=True)
        (ROOT/'data/login.log').touch(mode=0o600,exist_ok=True)
        target.write_bytes(plistlib.dumps(configuration));target.chmod(0o600)
        run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(target)])
        print('Login startup installed for this user. Docker must be available after login.');return
    if not args.path: raise SystemExit('--path is required.')
    if args.action=='backup':
        destination=args.path.expanduser().resolve()
        destination.mkdir(mode=0o700,parents=True,exist_ok=False)
        with (destination/'airlock.dump').open('xb') as handle:
            run(['docker','compose','exec','-T','postgres','pg_dump','-U','airlock','-d','airlock','-Fc'],stdout=handle)
        import airlock
        build = ROOT/'AIRLOCK_BUILD.json'
        commit = (json.loads(build.read_text())['commit'] if build.is_file() else
                  subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        (destination/'manifest.json').write_text(json.dumps({'version':airlock.__version__,
            'commit':commit,'created_at':datetime.now(UTC).isoformat(),'credentials_included':False},indent=2)+'\n')
        print('Database backup complete. Contains sensitive local history; store only on an approved encrypted volume. Credentials are not included.')
    else:
        # An existing personal/work database is never silently overwritten.
        dump=args.path.expanduser().resolve()/'airlock.dump'
        if not dump.is_file(): raise SystemExit('Backup dump not found.')
        result=subprocess.check_output(['docker','compose','exec','-T','postgres','psql','-U','airlock','-d','airlock','-tAc',
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"],cwd=ROOT,text=True)
        if int(result.strip())!=0: raise SystemExit('Restore requires an empty database. Current data was not touched.')
        import tempfile
        with tempfile.TemporaryFile(mode='w+b') as sql:
            with dump.open('rb') as handle:
                run(['docker','compose','exec','-T','postgres','pg_restore','--no-owner','--no-privileges','--file=-'],stdin=handle,stdout=sql)
            sql.write(b'\nUPDATE public.release_policies SET paused=true,revision=revision+1; UPDATE public.exchange_state SET enabled=false,allow_availability=false,inbound=NULL; UPDATE public.calendar_sources SET enabled=false; UPDATE public.company_connection SET enabled=false;\n')
            sql.seek(0)
            # Restore and disable external activity in the SAME transaction. There is
            # no visible interval in which restored credentials/cursors can publish.
            run(['docker','compose','exec','-T','postgres','psql','-U','airlock','-d','airlock',
                 '--single-transaction','-v','ON_ERROR_STOP=1'],stdin=sql,stdout=subprocess.DEVNULL)
        print('Database restored with all external connections disabled. Reconcile pairing/cursors and credentials before enabling anything.')


if __name__=='__main__': main()
