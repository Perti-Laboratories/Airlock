"""Managed-host startup; identity creation remains an explicit host-only operation."""
import json
import os
import argparse
import base64
import sqlite3
import uuid
from pathlib import Path

from fastapi import FastAPI

from .service import create_connector, initialize


def initialize_from_secret(directory, secret_file):
    """Explicit operator bootstrap through the host's secret-file facility, never HTTP."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    directory = Path(directory)
    if not os.path.ismount(directory):
        raise RuntimeError('Connector requires its persistent disk mount.')
    config = json.loads(Path(secret_file).read_text())
    required = {'pairing_id', 'private_key', 'public_key', 'device_token', 'harness_token', 'pairing_code'}
    if set(config) != required or any(not isinstance(v, str) for v in config.values()):
        raise ValueError('Invalid bootstrap configuration.')
    uuid.UUID(config['pairing_id'])
    private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(config['private_key'], validate=True))
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if public != base64.b64decode(config['public_key'], validate=True):
        raise ValueError('Bootstrap signing key mismatch.')
    if any(not 32 <= len(config[key]) <= 160 for key in ('device_token', 'harness_token', 'pairing_code')):
        raise ValueError('Invalid bootstrap credential.')
    target, database = directory / 'config.json', directory / 'connector.sqlite3'
    if target.exists() or database.exists():
        if not target.exists() or not database.exists() or json.loads(target.read_text()) != config:
            raise RuntimeError('Existing state cannot be replaced by bootstrap.')
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
            if db.execute('SELECT COUNT(*) FROM state WHERE id=1').fetchone()[0] != 1:
                raise RuntimeError('Existing state requires operator recovery.')
        return
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(config, handle)
        handle.flush()
        os.fsync(handle.fileno())
    initialize(database)


def hosted_app(directory):
    directory = Path(directory)
    if not os.path.ismount(directory):
        raise RuntimeError('Connector requires its persistent disk mount.')
    config_path, database = directory / 'config.json', directory / 'connector.sqlite3'
    if config_path.exists() != database.exists():
        raise RuntimeError('Incomplete connector state; operator recovery required.')
    if config_path.exists():
        return create_connector(json.loads(config_path.read_text()), database)
    # A newly mounted empty disk exposes no pairing, harness, or initialization API.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    def health():
        return {'service': 'airlock-connector', 'needs_initialization': True}

    return app


def main():
    import uvicorn
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize-from', help='One-time operator-supplied host secret file')
    args = parser.parse_args()
    if args.initialize_from:
        initialize_from_secret('/data', args.initialize_from)
    app = hosted_app('/data')
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
                access_log=False, proxy_headers=False)


if __name__ == '__main__':
    main()
