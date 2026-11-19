"""Operator-installed envelopes only; no remote enrollment administration API."""
import hashlib
import hmac
import re
import time
from fastapi import HTTPException, Request
from airlock_contracts.setup import MAX_SETUP


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS setup_envelope (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL, token_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, ciphertext TEXT)')


def install(path, envelope, store):
    if (set(envelope) != {'id','token_hash','expires_at','ciphertext'}
            or not re.fullmatch('[a-f0-9]{32}', envelope['id'])
            or not re.fullmatch('[a-f0-9]{64}', envelope['token_hash'])
            or type(envelope['expires_at']) is not int
            or not isinstance(envelope['ciphertext'], str)
            or len(envelope['ciphertext']) > MAX_SETUP):
        raise ValueError('Invalid setup envelope.')
    with store(path) as db:
        initialize(db)
        previous = db.execute('SELECT id FROM setup_envelope WHERE slot=1').fetchone()
        # Restarting a host must never revive a consumed or expired code.
        if previous and previous['id'] == envelope['id']:
            return
        if not time.time() < envelope['expires_at'] <= time.time() + 86401:
            raise ValueError('Setup envelope expired or lifetime too long.')
        state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        if state['revoked'] or state['public_key']:
            raise ValueError('Setup requires a fresh unpaired connector.')
        db.execute('INSERT OR REPLACE INTO setup_envelope VALUES(1,?,?,?,?)',
                   tuple(envelope[k] for k in ('id','token_hash','expires_at','ciphertext')))


def attach(app, path, store):
    with store(path) as db:
        initialize(db)

    @app.post('/v1/setup/redeem')
    def redeem(request: Request):
        token = request.headers.get('authorization', '')
        if not re.fullmatch(r'Bearer [a-f0-9]{64}', token):
            raise HTTPException(401, 'Setup code unavailable.')
        digest = hashlib.sha256(token[7:].encode()).hexdigest()
        with store(path) as db:
            row = db.execute('SELECT * FROM setup_envelope WHERE slot=1').fetchone()
            state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if (not row or not hmac.compare_digest(row['token_hash'], digest)
                    or row['expires_at'] <= time.time() or not row['ciphertext']
                    or state['revoked'] or state['public_key']):
                raise HTTPException(401, 'Setup code unavailable.')
            ciphertext = row['ciphertext']
            db.execute('UPDATE setup_envelope SET ciphertext=NULL WHERE slot=1')
        return {'ciphertext': ciphertext}
