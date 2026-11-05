"""Build a source-only pilot archive from a clean committed tree, never the working folder."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def build(root, output):
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--'], cwd=root, check=True, stdout=subprocess.DEVNULL)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD'], cwd=root)
    prefix = 'Airlock/'
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'airlock-work-pilot-{commit[:12]}.tar.gz'
    hashes = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source, tarfile.open(target, 'w:gz') as package:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if any(p in {'data', '.env', '.venv', '.git', 'logs', 'models', 'artifacts', '__pycache__'} for p in parts):
                raise ValueError('Runtime state must never be tracked in a distributable build.')
            name = Path(member.name).name
            if (name in {'google_desktop_client.json', 'invitation.json', 'harness.json'}
                    or name.startswith(('client_secret', 'credentials'))
                    or (name.startswith('.env.') and name != '.env.example')
                    or name.endswith(('.pem', '.key', '.db', '.sqlite', '.log'))):
                raise ValueError('Credential and runtime files cannot be distributed.')
            if member.issym() or member.islnk():
                raise ValueError('Source package must not contain links.')
            data = source.extractfile(member).read() if member.isfile() else None
            if data is not None:
                hashes[member.name] = hashlib.sha256(data).hexdigest()
            member.name = prefix + member.name
            package.addfile(member, io.BytesIO(data) if data is not None else None)
        manifest = json.dumps({'commit':commit, 'runtime_state_included':False, 'sha256':hashes}, indent=2).encode()
        info = tarfile.TarInfo(prefix+'AIRLOCK_BUILD.json');info.size=len(manifest);info.mode=0o644
        package.addfile(info, io.BytesIO(manifest))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name+'.sha256').write_text(f'{digest}  {target.name}\n')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    print(build(ROOT, args.output.resolve()))
