import pytest
from fastapi.testclient import TestClient

from airlock_connector.cli import provision
from airlock_connector.hosted import hosted_app


def test_hosted_connector_requires_disk_and_explicit_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.ismount', lambda _: False)
    with pytest.raises(RuntimeError, match='persistent disk'):
        hosted_app(tmp_path)
    monkeypatch.setattr('os.path.ismount', lambda _: True)
    client = TestClient(hosted_app(tmp_path))
    assert client.get('/health').json()['needs_initialization']
    assert client.post('/v1/pair', json={}).status_code == 404
    assert not list(tmp_path.iterdir())
    config = provision(tmp_path, 'https://connector.example.test')
    client = TestClient(hosted_app(tmp_path))
    assert client.get('/health').json()['schema_version'] == 1
    assert client.get('/v1/harness/release').status_code == 401
    (tmp_path / 'connector.sqlite3').unlink()
    with pytest.raises(RuntimeError, match='recovery'):
        hosted_app(tmp_path)
    assert config['public_key']


def test_explicit_bootstrap_never_replaces_or_resets_existing_pairing(tmp_path, monkeypatch):
    import json
    from airlock_connector.hosted import initialize_from_secret
    from airlock_connector.service import store
    monkeypatch.setattr('os.path.ismount', lambda _: True)
    source, destination = tmp_path / 'operator', tmp_path / 'host'
    destination.mkdir()
    provision(source, 'https://connector.example.test')
    initialize_from_secret(destination, source / 'config.json')
    with store(destination / 'connector.sqlite3') as db:
        db.execute('UPDATE state SET revoked=1,release_revision=7 WHERE id=1')
    initialize_from_secret(destination, source / 'config.json')
    with store(destination / 'connector.sqlite3') as db:
        row = db.execute('SELECT * FROM state').fetchone()
        assert row['revoked'] == 1 and row['release_revision'] == 7
    config = json.loads((source / 'config.json').read_text())
    config['pairing_code'] = 'different' * 8
    (source / 'config.json').write_text(json.dumps(config))
    with pytest.raises(RuntimeError, match='cannot be replaced'):
        initialize_from_secret(destination, source / 'config.json')
    (destination / 'connector.sqlite3').unlink()
    with pytest.raises(RuntimeError, match='cannot be replaced'):
        initialize_from_secret(destination, source / 'config.json')
