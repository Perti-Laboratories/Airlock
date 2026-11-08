"""Durable, bounded board exchange for the existing paired roles."""
import hashlib
import json
import uuid
from datetime import timedelta
from fastapi import HTTPException, Request
from airlock_contracts import RecordPolicy, RecordSnapshot, ReleaseSnapshot, seal, unseal, utcnow
from airlock_contracts.board import BoardSnapshot, BoardMove, BoardReceipt, BoardInbox


def attach(app, config, path, store, auth):
    with store(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS board_feeds (role TEXT PRIMARY KEY, revision INTEGER NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS board_moves (id TEXT PRIMARY KEY, requester TEXT NOT NULL, body TEXT NOT NULL, result TEXT, expires_at TEXT NOT NULL)')

    def role_check(role, request):
        if role not in {'device', 'harness'}:
            raise HTTPException(404)
        auth(request, role)

    def state(db):
        row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        if row['revoked']:
            raise HTTPException(403, 'Pairing unavailable.')
        return row

    def permission(row):
        p = RecordPolicy.model_validate_json(row['record_policy_body']) if row['record_policy_body'] else None
        return p if p and p.expires_at > utcnow() and p.rules.todo != 'private' else None

    def source_ids(row, role):
        raw = row['release_body'] if role == 'device' else row['records_body']
        if not raw:
            return set(), 0
        s = (ReleaseSnapshot.model_validate_json(raw) if role == 'device' else
             RecordSnapshot.model_validate_json(json.loads(raw)['document']))
        return ({i.export_id for i in s.items if i.kind == 'todo'} if s.expires_at > utcnow() else set()), s.revision

    def decode(body, role, row, model):
        try:
            doc = (unseal(body, row['public_key'], model, config['pairing_id']) if role == 'device'
                   else model.model_validate(body))
            doc.check_live()
            if doc.source != role or str(doc.pairing_id) != config['pairing_id']:
                raise ValueError()
            return doc
        except Exception:
            raise HTTPException(422, 'Invalid board contract.') from None

    def feed(db, row, role):
        stored = db.execute('SELECT body FROM board_feeds WHERE role=?', (role,)).fetchone()
        if not stored or not permission(row):
            return None
        value = BoardSnapshot.model_validate_json(stored['body'])
        ids, revision = source_ids(row, role)
        if value.expires_at <= utcnow() or value.basis_revision != revision:
            return None
        return value.model_copy(update={'items': [i for i in value.items if i.export_id in ids]})

    @app.post('/v3/{role}/board')
    def publish(role: str, body: dict, request: Request):
        role_check(role, request)
        with store(path) as db:
            row = state(db); doc = decode(body, role, row, BoardSnapshot)
            ids, revision = source_ids(row, role)
            if doc.basis_revision != revision or any(i.export_id not in ids for i in doc.items) or (doc.items and not permission(row)):
                raise HTTPException(409, 'Refresh task permission and snapshot.')
            previous = db.execute('SELECT * FROM board_feeds WHERE role=?', (role,)).fetchone()
            digest = hashlib.sha256(doc.model_dump_json().encode()).hexdigest()
            if previous and (doc.revision < previous['revision'] or (doc.revision == previous['revision'] and digest != previous['digest'])):
                raise HTTPException(409, 'Stale board revision.')
            db.execute('INSERT OR REPLACE INTO board_feeds VALUES(?,?,?,?)', (role, doc.revision, digest, doc.model_dump_json()))
            return {'status': 'applied', 'revision': doc.revision}

    @app.post('/v3/{role}/moves')
    def move(role: str, body: dict, request: Request):
        role_check(role, request)
        with store(path) as db:
            row = state(db); doc = decode(body, role, row, BoardMove)
            existing = db.execute('SELECT * FROM board_moves WHERE id=?', (str(doc.message_id),)).fetchone()
            if existing:
                if existing['body'] != doc.model_dump_json() or existing['requester'] != role:
                    raise HTTPException(409, 'Conflicting operation.')
                return {'status': 'queued', 'operation_id': str(doc.message_id)}
            p = permission(row); peer = feed(db, row, 'harness' if role == 'device' else 'device')
            item = next((i for i in peer.items if i.export_id == doc.export_id), None) if peer else None
            if not p or p.revision != doc.permission_revision or not item or item.version != doc.expected_version:
                raise HTTPException(409, 'Task or permission changed. Refresh before moving.')
            # Retain only a bounded window of completed/expired operations. Expired envelopes
            # can never be replayed, even after their deduplication entry is pruned.
            cutoff = (utcnow()-timedelta(days=1)).isoformat()
            db.execute('DELETE FROM board_moves WHERE expires_at < ?', (cutoff,))
            count = db.execute('SELECT count(*) FROM board_moves WHERE result IS NULL AND expires_at>?', (utcnow().isoformat(),)).fetchone()[0]
            if count >= 100:
                raise HTTPException(429, 'Too many pending moves.')
            db.execute('INSERT INTO board_moves VALUES(?,?,?,?,?)', (str(doc.message_id), role, doc.model_dump_json(), None, doc.expires_at.isoformat()))
            return {'status': 'queued', 'operation_id': str(doc.message_id)}

    @app.post('/v3/{role}/receipts')
    def receipt(role: str, body: BoardReceipt, request: Request):
        role_check(role, request)
        with store(path) as db:
            state(db)
            old = db.execute('SELECT * FROM board_moves WHERE id=?', (str(body.operation_id),)).fetchone()
            if not old or old['requester'] == role:
                raise HTTPException(409, 'Unknown incoming move.')
            if old['result'] and old['result'] != body.status:
                raise HTTPException(409, 'Conflicting receipt.')
            db.execute('UPDATE board_moves SET result=? WHERE id=?', (body.status, str(body.operation_id)))
        return {'status': 'applied'}

    @app.get('/v3/{role}/board')
    def inbox(role: str, request: Request):
        role_check(role, request)
        with store(path) as db:
            row = state(db); p = permission(row); stamp = utcnow()
            moves = [BoardMove.model_validate_json(r['body']) for r in db.execute('SELECT body FROM board_moves WHERE requester!=? AND result IS NULL LIMIT 100', (role,))]
            receipts = [BoardReceipt(operation_id=r['id'], status=r['result']) for r in db.execute('SELECT id,result FROM board_moves WHERE requester=? AND result IS NOT NULL ORDER BY rowid DESC LIMIT 200', (role,))]
            packet = BoardInbox(message_id=uuid.uuid4(), pairing_id=config['pairing_id'], revision=1,
                issued_at=stamp, expires_at=stamp+timedelta(minutes=15), source=role,
                permission_revision=p.revision if p else 0, enabled=bool(p),
                feed=feed(db, row, 'harness' if role == 'device' else 'device'), moves=moves, receipts=receipts)
            return seal(packet, config['private_key'])
