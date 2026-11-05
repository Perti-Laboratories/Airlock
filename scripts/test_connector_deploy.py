"""Synthetic HTTPS deployment smoke test; isolated volumes/ports, no OS trust changes.

Build airlock-connector:pilot first. Uses the deployment Compose/Caddy configuration,
with only project/image/loopback ports changed. Removes only this test's resources.
"""
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
import uuid
from datetime import timedelta

import httpx
from airlock_contracts import ReleaseSnapshot, AvailabilitySnapshot, keys, seal, unseal, utcnow

ROOT = Path(__file__).resolve().parents[1]
name = 'airlock-tls-smoke-' + uuid.uuid4().hex[:8]
env = {**os.environ, 'AIRLOCK_CONNECTOR_HOST': 'localhost'}
configuration = json.loads(subprocess.check_output(
    ['docker', 'compose', '-f', 'deploy/connector/compose.yaml', 'config', '--format', 'json'],
    cwd=ROOT, env=env))
configuration['name'] = name
for kind in ('networks', 'volumes'):
    for item in configuration[kind].values():
        item.pop('name', None)  # Never reuse or remove deployment volumes/networks.
configuration['services']['connector'].pop('build')
configuration['services']['connector']['image'] = 'airlock-connector:pilot'
configuration['services']['edge']['ports'] = ['127.0.0.1:8845:443', '127.0.0.1:8846:80']

with tempfile.TemporaryDirectory(prefix=name) as temporary:
    folder = Path(temporary)
    compose = folder / 'compose.json'
    compose.write_text(json.dumps(configuration))
    base = ['docker', 'compose', '-p', name, '-f', str(compose)]

    def run(*args, capture=False, check=True):
        return subprocess.run(base + list(args), cwd=ROOT, env=env, check=check,
                              capture_output=capture, text=True)

    try:
        run('run', '--rm', 'connector', 'init', '--directory', '/data', '--endpoint', 'https://localhost:8845')
        run('up', '-d')
        cert = folder / 'test-root.crt'
        for _ in range(40):
            result = run('cp', 'edge:/data/caddy/pki/authorities/local/root.crt', str(cert), capture=True, check=False)
            if result.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Test HTTPS issuer did not become ready.')
        context = ssl.create_default_context(cafile=str(cert))
        config = json.loads(run('exec', '-T', 'connector', 'cat', '/data/config.json', capture=True).stdout)
        assert run('exec', '-T', 'connector', 'id', '-u', capture=True).stdout.strip() == '10001'
        private, public = keys()
        with httpx.Client(base_url='https://localhost:8845', verify=context, trust_env=False, follow_redirects=False) as client:
            for _ in range(40):
                try:
                    client.get('/health').raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(.5)
            else:
                raise RuntimeError('Test connector did not become ready.')
            client.post('/v1/pair', json={'code':config['pairing_code'], 'public_key':public}).raise_for_status()
            device = {'Authorization':'Bearer ' + config['device_token']}
            harness = {'Authorization':'Bearer ' + config['harness_token']}
            stamp = utcnow()
            doc = ReleaseSnapshot(pairing_id=config['pairing_id'], message_id=uuid.uuid4(), revision=1,
                policy_revision=1, issued_at=stamp, expires_at=stamp+timedelta(minutes=15), sources_fresh=True, items=[])
            client.post('/v1/releases', json=seal(doc, private), headers=device).raise_for_status()
            reply = client.get('/v1/harness/release', headers=harness); reply.raise_for_status()
            assert unseal(reply.json()['snapshot'], config['public_key'], ReleaseSnapshot, config['pairing_id']) == doc
            assert client.get('/v1/harness/release', headers=device).status_code == 401
            client.put('/v1/harness/availability', json={'expected_revision':0, 'items':[]}, headers=harness).raise_for_status()
            incoming = client.get('/v1/inbox', headers=device); incoming.raise_for_status()
            assert unseal(incoming.json()['snapshot'], config['public_key'], AvailabilitySnapshot, config['pairing_id']).revision == 1
            assert client.get('/admin', headers=harness).status_code == 404
            run('run', '--rm', 'connector', 'revoke', '--directory', '/data')
            assert client.get('/v1/inbox', headers=device).status_code == 403
        print('PASS: non-root isolated connector, verified TLS, signed bidirectional traffic, credential separation, host-only revocation.')
    finally:
        run('down', '--volumes', capture=True)
