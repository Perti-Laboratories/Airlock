"""Operator-installed envelopes only; no remote enrollment administration API."""
import hashlib
import hmac
import re
import time
from fastapi import HTTPException, Request
from airlock_contracts.setup import MAX_SETUP


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS setup_envelope (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL, token_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, ciphertext TEXT)')

    columns = {row[1] for row in db.execute('PRAGMA table_info(setup_envelope)')}
    if 'pairing_hash' not in columns:
        db.execute('ALTER TABLE setup_envelope ADD COLUMN pairing_hash TEXT')
    if 'cancelled' not in columns:
        db.execute('ALTER TABLE setup_envelope ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS setup_history (id TEXT PRIMARY KEY)')
    db.execute('INSERT OR IGNORE INTO setup_history SELECT id FROM setup_envelope')


def install(path, envelope, store):
    if (set(envelope) != {'id','token_hash','expires_at','ciphertext','pairing_hash'}
            or not re.fullmatch('[a-f0-9]{32}', envelope['id'])
            or not re.fullmatch('[a-f0-9]{64}', envelope['token_hash'])
            or not re.fullmatch('[a-f0-9]{64}', envelope['pairing_hash'])
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
        if db.execute('SELECT 1 FROM setup_history WHERE id=?', (envelope['id'],)).fetchone():
            raise ValueError('Retired setup package cannot be reinstalled; issue a fresh code.')
        if not time.time() < envelope['expires_at'] <= time.time() + 86401:
            raise ValueError('Setup envelope expired or lifetime too long.')
        state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        if state['revoked'] or state['public_key']:
            raise ValueError('Setup requires a fresh unpaired connector.')
        db.execute('INSERT INTO setup_history VALUES(?)', (envelope['id'],))
        db.execute('INSERT OR REPLACE INTO setup_envelope(slot,id,token_hash,expires_at,ciphertext,pairing_hash,cancelled) VALUES(1,?,?,?,?,?,0)',
                   tuple(envelope[k] for k in ('id','token_hash','expires_at','ciphertext','pairing_hash')))


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
                    or row['cancelled'] or not row['pairing_hash'] or row['expires_at'] <= time.time() or not row['ciphertext']
                    or state['revoked'] or state['public_key']):
                raise HTTPException(401, 'Setup code unavailable.')
            ciphertext = row['ciphertext']
            db.execute('UPDATE setup_envelope SET ciphertext=NULL WHERE slot=1')
        return {'ciphertext': ciphertext}


    @app.post('/v1/setup/cancel')
    def cancel(request: Request):
        token = request.headers.get('authorization', '')
        if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{64}', token):
            raise HTTPException(401, 'Setup unavailable.')
        digest = hashlib.sha256(token[7:].encode()).hexdigest()
        with store(path) as db:
            row = db.execute('SELECT * FROM setup_envelope WHERE slot=1').fetchone()
            state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if not row or not row['pairing_hash'] or not hmac.compare_digest(row['pairing_hash'], digest):
                raise HTTPException(410, 'Setup was replaced or is unavailable.')
            if state['public_key']:
                raise HTTPException(409, 'Connector already paired; cancellation cannot undo pairing.')
            db.execute('UPDATE setup_envelope SET cancelled=1,ciphertext=NULL WHERE slot=1')
        return {'cancelled':True}


def authorize_pair(db, state, code, public_key, legacy_code):
    """Enrollment grants override legacy invitations and expire at initial binding.

    A same-key retry may recover an already committed binding after the deadline.
    The grant secret must still match; a new key can never take over that binding.
    """
    row = db.execute('SELECT * FROM setup_envelope WHERE slot=1').fetchone()
    if row:
        if not row['pairing_hash'] and state['public_key'] == public_key and hmac.compare_digest(code, legacy_code):
            return  # Recover a pre-v2 binding only; never create a new one.
        digest = hashlib.sha256(code.encode()).hexdigest()
        if not row['pairing_hash'] or not hmac.compare_digest(row['pairing_hash'], digest):
            raise HTTPException(401, 'Invalid or superseded invitation.')
        if row['cancelled'] or (not state['public_key'] and row['expires_at'] <= time.time()):
            raise HTTPException(401, 'Setup expired or cancelled; request a fresh code.')
    elif not hmac.compare_digest(code, legacy_code):
        raise HTTPException(401, 'Invalid invitation.')
