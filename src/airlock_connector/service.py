import asyncio
from collections import deque
from time import monotonic
import hashlib
import hmac
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from airlock_contracts import (Strict, Signed, Availability, AvailabilitySnapshot,
    ReleaseSnapshot, RecordPolicy, RecordSnapshot, Projection, filter_records, MAX_BYTES, seal, unseal, utcnow)


class Pair(Strict):
    code: str = Field(min_length=32, max_length=160)
    public_key: str = Field(min_length=44, max_length=44)


class RecordWrite(Strict):
    expected_revision: int = Field(ge=0)
    policy_message_id: uuid.UUID
    items: list[Projection] = Field(max_length=2000)


class OverlayWrite(Strict):
    expected_revision: int = Field(ge=0)
    items: list[Availability] = Field(max_length=500)


@contextmanager
def store(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA secure_delete=ON')
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with store(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), public_key TEXT, revoked INTEGER NOT NULL DEFAULT 0, release_revision INTEGER NOT NULL DEFAULT 0, release_hash TEXT, release_body TEXT, overlay_revision INTEGER NOT NULL DEFAULT 0, overlay_body TEXT, overlay_ack INTEGER NOT NULL DEFAULT 0)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(state)')}
        for name, spec in {'record_policy_revision': 'INTEGER NOT NULL DEFAULT 0',
                'record_policy_hash': 'TEXT', 'record_policy_body': 'TEXT',
                'records_revision': 'INTEGER NOT NULL DEFAULT 0', 'records_body': 'TEXT',
                'records_ack': 'INTEGER NOT NULL DEFAULT 0'}.items():
            if name not in columns:
                db.execute(f'ALTER TABLE state ADD COLUMN {name} {spec}')
        db.execute('INSERT OR IGNORE INTO state(id) VALUES(1)')
    Path(path).chmod(0o600)


def create_connector(config, path):
    initialize(path)
    app = FastAPI(title='Airlock Connector', docs_url=None, redoc_url=None, openapi_url=None)

    requests = {role: deque() for role in ('public', 'device', 'harness')}

    @app.middleware('http')
    async def boundary(request, call_next):
        stamp = monotonic()
        # Unauthenticated traffic cannot exhaust a legitimate peer's application quota.
        role = 'public'
        authorization = request.headers.get('authorization', '')
        for candidate in ('device', 'harness'):
            if hmac.compare_digest(authorization, 'Bearer ' + config[candidate + '_token']):
                role = candidate
        bucket = requests[role]
        while bucket and bucket[0] < stamp - 60:
            bucket.popleft()
        if request.url.path != '/health':
            if len(bucket) >= 120:
                return JSONResponse({'detail': 'Rate limit exceeded.'}, status_code=429, headers={'Retry-After':'60'})
            bucket.append(stamp)
        # No cookie credentials or browser cross-origin access. A harness needs its own bearer.
        if request.headers.get('origin') or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Browser cross-origin access disabled.'}, status_code=403)
        if request.method in {'POST','PUT'}:
            if request.headers.get('content-type','').split(';')[0] != 'application/json':
                return JSONResponse({'detail':'JSON required.'}, status_code=415)
            size = 0
            chunks = []
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            return JSONResponse({'detail':'Package too large.'}, status_code=413)
                        chunks.append(chunk)
            except TimeoutError:
                return JSONResponse({'detail':'Request timed out.'}, status_code=408)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'detail':'Invalid contract.'}, status_code=422)

    def auth(request, role):
        if not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+config[role+'_token']):
            raise HTTPException(401, 'Invalid credential.')
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked'] or not row['public_key']:
                raise HTTPException(403, 'Pairing unavailable.')
        return row

    @app.get('/health')
    def health():
        return {'service':'airlock-connector','schema_version':1}

    @app.post('/v1/pair')
    def pair(body: Pair):
        import base64
        if not hmac.compare_digest(body.code, config['pairing_code']):
            raise HTTPException(401, 'Invalid invitation.')
        try:
            if len(base64.b64decode(body.public_key, validate=True)) != 32:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Invalid public key.') from None
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked'] or row['public_key'] not in {None,body.public_key}:
                raise HTTPException(409, 'Invitation already bound.')
            db.execute('UPDATE state SET public_key=? WHERE id=1', (body.public_key,))
        return {'pairing_id':config['pairing_id'], 'public_key':config['public_key'], 'device_token':config['device_token']}

    @app.post('/v1/releases')
    def receive(body: Signed, request: Request):
        auth(request,'device')
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked']:
                raise HTTPException(403,'Pairing unavailable.')
            try:
                snapshot = unseal(body, row['public_key'], ReleaseSnapshot, config['pairing_id'])
            except Exception:
                raise HTTPException(422, 'Invalid signed release.') from None
            digest = hashlib.sha256(body.document.encode()).hexdigest()
            if snapshot.revision < row['release_revision'] or (snapshot.revision == row['release_revision'] and digest != row['release_hash']):
                raise HTTPException(409,'Stale or conflicting revision.')
            if snapshot.revision > row['release_revision']:
                db.execute('UPDATE state SET release_revision=?,release_hash=?,release_body=? WHERE id=1',
                    (snapshot.revision,digest,snapshot.model_dump_json()))
            # Replacement is atomic: absence in the new snapshot withdraws previous objects.
            return {'status':'applied','revision':snapshot.revision,'message_id':str(snapshot.message_id)}

    @app.get('/v1/harness/projections')
    def projections(request: Request):
        row=auth(request,'harness')
        if not row['release_body']:
            return {'revision':0,'stale':True,'items':[],'expires_at':None}
        snapshot=ReleaseSnapshot.model_validate_json(row['release_body'])
        expired=snapshot.expires_at <= utcnow()
        return {'revision':snapshot.revision,'stale':expired or not snapshot.sources_fresh,
                'expires_at':snapshot.expires_at.isoformat(), 'source_observed_at':snapshot.source_observed_at,
                'items':[] if expired else [i.model_dump(mode='json') for i in snapshot.items]}

    @app.get('/v1/harness/release')
    def signed_projection(request: Request):
        row = auth(request, 'harness')
        snapshot = ReleaseSnapshot.model_validate_json(row['release_body']) if row['release_body'] else None
        # Attest the same approved snapshot for a receiver that pins this connector key.
        # Keep expired envelopes so the harness can advance its durable cursor and withdraw.
        return {'snapshot': seal(snapshot, config['private_key']) if snapshot else None}

    @app.put('/v1/harness/availability')
    def availability(body: OverlayWrite, request: Request):
        auth(request,'harness')
        with store(path) as db:
            row=db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked']:
                raise HTTPException(403,'Pairing unavailable.')
            if body.expected_revision != row['overlay_revision']:
                raise HTTPException(409,'Refresh availability revision.')
            timestamp=utcnow()
            try:
                snapshot=AvailabilitySnapshot(message_id=uuid.uuid4(),pairing_id=config['pairing_id'],
                    revision=row['overlay_revision']+1,issued_at=timestamp,expires_at=timestamp+timedelta(minutes=15),items=body.items)
                signed=seal(snapshot,config['private_key'])
            except ValueError:
                raise HTTPException(422,'Invalid availability.') from None
            db.execute('UPDATE state SET overlay_revision=?,overlay_body=? WHERE id=1',
                (snapshot.revision,json.dumps(signed)))
            return {'revision':snapshot.revision,'status':'queued'}

    @app.get('/v1/harness/availability')
    def overlay_status(request: Request):
        row=auth(request,'harness')
        return {'revision':row['overlay_revision'],'acknowledged_revision':row['overlay_ack']}

    @app.get('/v1/inbox')
    def inbox(request: Request):
        row=auth(request,'device')
        return {'snapshot':json.loads(row['overlay_body']) if row['overlay_body'] else None}

    class Ack(Strict):
        revision: int = Field(ge=1)

    @app.post('/v1/inbox/ack')
    def ack(body: Ack, request: Request):
        auth(request,'device')
        with store(path) as db:
            row=db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked'] or body.revision > row['overlay_revision']:
                raise HTTPException(409,'Invalid receipt.')
            db.execute('UPDATE state SET overlay_ack=max(overlay_ack,?) WHERE id=1',(body.revision,))
        return {'status':'applied'}

    @app.post('/v2/record-policy')
    def record_policy(body: Signed, request: Request):
        auth(request, 'device')
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked']:
                raise HTTPException(403, 'Pairing unavailable.')
            try:
                policy = unseal(body, row['public_key'], RecordPolicy, config['pairing_id'])
            except Exception:
                raise HTTPException(422, 'Invalid signed record policy.') from None
            digest = hashlib.sha256(body.document.encode()).hexdigest()
            if policy.revision < row['record_policy_revision'] or (policy.revision == row['record_policy_revision']
                    and digest != row['record_policy_hash']):
                raise HTTPException(409, 'Stale or conflicting policy.')
            if policy.revision > row['record_policy_revision']:
                # A changed grant invalidates the queued payload, even if a harness is offline.
                db.execute('UPDATE state SET record_policy_revision=?,record_policy_hash=?,record_policy_body=?,records_body=NULL WHERE id=1',
                    (policy.revision, digest, policy.model_dump_json()))
            return {'revision': policy.revision, 'message_id': str(policy.message_id), 'status': 'applied'}

    @app.get('/v2/harness/records')
    def records_status(request: Request):
        row = auth(request, 'harness')
        policy = RecordPolicy.model_validate_json(row['record_policy_body']) if row['record_policy_body'] else None
        return {'policy': seal(policy, config['private_key']) if policy else None,
                'revision': row['records_revision'], 'acknowledged_revision': row['records_ack']}

    @app.put('/v2/harness/records')
    def records_write(body: RecordWrite, request: Request):
        auth(request, 'harness')
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked']:
                raise HTTPException(403, 'Pairing unavailable.')
            try:
                policy = RecordPolicy.model_validate_json(row['record_policy_body'])
                policy.check_live()
            except Exception:
                raise HTTPException(409, 'No current record permission.') from None
            if body.expected_revision != row['records_revision'] or body.policy_message_id != policy.message_id:
                raise HTTPException(409, 'Refresh record revision and permission.')
            if filter_records(body.items, policy.rules) != body.items:
                raise HTTPException(422, 'Records exceed permission.')
            timestamp = utcnow()
            try:
                snapshot = RecordSnapshot(message_id=uuid.uuid4(), pairing_id=config['pairing_id'],
                    revision=row['records_revision']+1, issued_at=timestamp,
                    expires_at=min(policy.expires_at, timestamp+timedelta(minutes=15)),
                    policy_message_id=policy.message_id, items=body.items)
                signed = seal(snapshot, config['private_key'])
            except ValueError:
                raise HTTPException(422, 'Invalid records.') from None
            db.execute('UPDATE state SET records_revision=?,records_body=? WHERE id=1',
                (snapshot.revision, json.dumps(signed)))
            return {'revision': snapshot.revision, 'status': 'queued'}

    @app.get('/v2/records')
    def records_inbox(request: Request):
        row = auth(request, 'device')
        return {'snapshot': json.loads(row['records_body']) if row['records_body'] else None}

    @app.post('/v2/records/ack')
    def records_ack(body: Ack, request: Request):
        auth(request, 'device')
        with store(path) as db:
            row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
            if row['revoked'] or body.revision != row['records_revision']:
                raise HTTPException(409, 'Invalid record receipt.')
            db.execute('UPDATE state SET records_ack=max(records_ack,?) WHERE id=1', (body.revision,))
        return {'status': 'applied'}

    from .board import attach
    attach(app, config, path, store, auth)
    return app
