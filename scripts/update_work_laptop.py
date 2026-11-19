"""Back up and fast-forward an installed work-pilot checkout; never reset local identity."""
import argparse
from datetime import datetime, UTC
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REMOTE = 'https://github.com/Perti-Laboratories/Airlock.git'


def run(args, root, **kwargs):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('AIRLOCK_', 'COMPOSE_', 'OLLAMA_'))}
    env['AIRLOCK_PYTHON'] = str(root / '.venv/bin/python')
    return subprocess.run(args, cwd=root, env=env, check=True, **kwargs)


def git(root, *args):
    return run(['git', *args], root, capture_output=True, text=True).stdout.strip()


def verify_origin(root):
    try:
        configured = git(root, 'config', '--get-all', 'remote.origin.url').splitlines()
        resolved = git(root, 'remote', 'get-url', '--all', 'origin').splitlines()
    except subprocess.CalledProcessError:
        raise SystemExit('Cannot verify the release repository; no update was attempted.') from None
    if configured != [EXPECTED_REMOTE] or resolved != [EXPECTED_REMOTE]:
        raise SystemExit('Origin must be the official Airlock HTTPS repository, without URL rewrites or extra origins. No update was attempted.')


def plan(root, plist):
    if not (root / '.env').is_file() or not (root / '.venv/bin/python').is_file():
        raise SystemExit('Use the installer first. Updates require an existing local workspace.')
    if git(root, 'branch', '--show-current') != 'work-pilot':
        raise SystemExit('Updates require the work-pilot branch; no files changed.')
    if git(root, 'status', '--porcelain'):
        raise SystemExit('Commit or move source changes before updating; local data was not touched.')
    login = plist.exists()
    if login:
        config = plistlib.loads(plist.read_bytes())
        if config.get('WorkingDirectory') != str(root):
            raise SystemExit('Login startup belongs to another installation; refusing to change it.')
    verify_origin(root)
    git(root, '-c', 'http.followRedirects=false', 'fetch', 'origin', 'refs/heads/work-pilot:refs/remotes/origin/work-pilot')
    previous, target = git(root, 'rev-parse', 'HEAD'), git(root, 'rev-parse', 'origin/work-pilot')
    try:
        git(root, 'merge-base', '--is-ancestor', previous, target)
    except subprocess.CalledProcessError:
        raise SystemExit('Release history diverged; refusing to reset or overwrite this checkout.') from None
    return previous, target, login


def update(root, plist, backup_parent, check=False):
    previous, target, login = plan(root, plist)
    print(f'Installed: {previous}\nAvailable: {target}', flush=True)
    if check or previous == target:
        print('Check complete; workspace unchanged.' if check else 'Already on the current work-pilot release.')
        return
    python = str(root / '.venv/bin/python')
    backup = backup_parent / (datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ') + '-' + previous[:12])
    try:
        if login:
            run([python, 'scripts/pilot.py', 'login-remove'], root)
        run(['bash', 'scripts/stop.sh'], root)
        run([python, 'scripts/pilot.py', 'backup', '--path', str(backup)], root)
        # Use the exact revision checked above, even if the remote branch moves.
        git(root, 'merge', '--ff-only', target)
        run(['bash', 'scripts/setup.sh'], root)
        run(['bash', 'scripts/start.sh'], root)
        run([python, 'scripts/pilot.py', 'check'], root)
        if login:
            run([python, 'scripts/pilot.py', 'login-install'], root)
    except (subprocess.CalledProcessError, OSError):
        # Never roll code back over a possibly upgraded schema or restore pairing counters.
        # Stop a partially started app; login supervision remains off after failure.
        try:
            run(['bash', 'scripts/stop.sh'], root)
        except (subprocess.CalledProcessError, OSError):
            pass
        raise SystemExit(f'Update stopped. Keep .env, Keychain and data. Backup location: {backup}. '
                         'Follow docs/WORK_LAPTOP_START.md recovery; no automatic database rollback was attempted.') from None
    print(f'Update complete. Backup: {backup}\nLocal data, Google sign-in and pairing identity retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fetch and inspect the release without stopping services')
    parser.add_argument('--backup-dir', type=Path, default=ROOT / 'data/backups')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This updater supports the macOS work-pilot installation.')
    os.umask(0o077)
    update(ROOT, Path.home() / 'Library/LaunchAgents/io.perti.airlock.plist',
           args.backup_dir.expanduser().resolve(), check=args.check)


if __name__ == '__main__':
    main()
