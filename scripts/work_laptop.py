"""First installation on a fresh Mac. No personal state or remote pairing is imported."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]


def preflight(root, timezone):
    if sys.platform != 'darwin' or sys.version_info < (3, 11):
        raise SystemExit('Use macOS with Python 3.11 or newer (3.13 is tested).')
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise SystemExit('Use an IANA timezone, such as America/New_York.') from None
    if (root / '.env').exists() or (root / 'data').exists():
        raise SystemExit('This folder already has local state. Use setup.sh/start.sh for an existing installation; do not overwrite it with a fresh install.')
    for name in ('git', 'docker', 'ollama'):
        if not shutil.which(name):
            raise SystemExit(f'Install {name} before continuing. See docs/WORK_LAPTOP_START.md.')
    for args in (['docker', 'info'], ['docker', 'compose', 'version']):
        if subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise SystemExit('Start Docker Desktop and ensure Docker Compose is available, then retry.')
    # Prevent accidentally reusing another Airlock database/volume on this machine.
    volumes = subprocess.check_output(['docker', 'volume', 'ls', '--filter',
        'label=com.docker.compose.project=airlock-local', '--format', '{{.Name}}'], text=True)
    if volumes.strip():
        raise SystemExit('An airlock-local database volume already exists. Preserve it and use the existing installation.')
    for port in (8741, 55433, 11435):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit(f'Local port {port} is in use. Stop the conflicting service before installing.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check prerequisites without installing anything')
    parser.add_argument('--no-login', action='store_true', help='Do not install automatic startup after login')
    parser.add_argument('--timezone', default='America/New_York')
    args = parser.parse_args()
    preflight(ROOT, args.timezone)
    if args.check:
        print('Fresh-install checks passed. No settings changed.');return
    # Do not let shell settings silently select a different workspace, provider or database.
    env = {k:v for k,v in os.environ.items() if not k.startswith(('AIRLOCK_', 'COMPOSE_', 'OLLAMA_'))}
    env.update(AIRLOCK_PYTHON=sys.executable, AIRLOCK_WORKSPACE_NAME='Work workspace',
               AIRLOCK_WORKSPACE_TIMEZONE=args.timezone)
    def run(command, **kwargs):
        subprocess.run(command, cwd=ROOT, env=env, check=True, **kwargs)
    run(['bash', 'scripts/setup.sh'])
    run(['bash', 'scripts/start.sh'])
    print('Downloading local model weights. This may take several minutes.', flush=True)
    model_env = {**env, 'OLLAMA_HOST':'127.0.0.1:11435', 'OLLAMA_NO_CLOUD':'1'}
    for model in ('qwen3:8b', 'nomic-embed-text:latest'):
        subprocess.run(['ollama', 'pull', model], cwd=ROOT, env=model_env, check=True)
    python = str(ROOT / '.venv/bin/python')
    run([python, 'scripts/pilot.py', 'check'])
    if not args.no_login:
        run([python, 'scripts/pilot.py', 'login-install'])
    print('\nAirlock is ready: http://127.0.0.1:8741\n'
          'Sharing starts paused and unpaired. Google and company memory are not connected.\n'
          'Next: follow docs/WORK_LAPTOP_START.md for the local smoke test and Google setup.')


if __name__ == '__main__':
    main()
