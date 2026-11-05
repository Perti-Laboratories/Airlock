"""Local release gate and bounded outbound exchange; no harness-specific knowledge."""
import hashlib
import json
import uuid
from datetime import timedelta
from urllib.parse import urlsplit
import httpx
from pydantic import Field
from .schemas import StrictModel
from sqlalchemy import select
from airlock_contracts import ReleaseSnapshot, AvailabilitySnapshot, CalendarProjection, TodoProjection, keys, seal, unseal, MAX_BYTES
from .google import Keychain
from .memory import DOMAIN, ActionError, audited, restore_audit_after_rollback
from .models import ExchangeState, ExportIdentity, Todo, CalendarSource, LocalState, now
from .releases import preview, policy_payload


class ExchangeKeys(Keychain):
    service='Airlock.Exchange.v1'


def validate_endpoint(value, allow_loopback=False):
    u=urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in {'','/'} or not u.hostname:
        raise ActionError('Use a connector origin without a path or embedded credentials.')
    if u.scheme != 'https' and not (allow_loopback and u.scheme=='http' and u.hostname=='127.0.0.1'):
        raise ActionError('Connector requires HTTPS. Explicit local-test mode permits 127.0.0.1 HTTP.')
    return value.rstrip('/')


class Transport:
    def __init__(self, endpoint, token=None):
        self.endpoint,self.token=endpoint,token

    def request(self, method, path, body=None):
        headers={'Authorization':'Bearer '+self.token} if self.token else {}
        # No redirects, ambient proxies, cookies, or arbitrary paths supplied by remote content.
        with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as client:
            with client.stream(method,self.endpoint+path,json=body,headers=headers) as response:
                response.raise_for_status()
                data=bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data)>MAX_BYTES:
                        raise ActionError('Connector response too large.')
                return json.loads(data)


class Invitation(StrictModel):
    endpoint: str = Field(max_length=500)
    pairing_id: uuid.UUID
    public_key: str = Field(min_length=44,max_length=44)
    code: str = Field(min_length=32,max_length=160)


def pair(db, invitation, settings, vault=None, transport=None):
    invite=Invitation.model_validate(invitation)
    endpoint=validate_endpoint(invite.endpoint,settings.exchange_allow_loopback)
    if db.get(ExchangeState,DOMAIN):
        raise ActionError('This workspace is already paired. Disable exchange to stop it; replacing identity needs a fresh workspace.')
    vault=vault or ExchangeKeys()
    name=str(invite.pairing_id)
    credentials=vault.get(name)
    if not credentials:
        private,public=keys()
        credentials={'private_key':private,'public_key':public}
        vault.set(name,credentials)
    def apply():
        result=(transport or Transport(endpoint)).request('POST','/v1/pair',{'code':invite.code,'public_key':credentials['public_key']})
        if result.get('pairing_id')!=name or result.get('public_key')!=invite.public_key or not isinstance(result.get('device_token'),str) or not 32<=len(result['device_token'])<=200:
            raise ActionError('Connector did not match this invitation.')
        vault.set(name,{**credentials,'token':result['device_token']})
        db.add(ExchangeState(domain_id=DOMAIN,pairing_id=invite.pairing_id,endpoint=endpoint,public_key=invite.public_key))
        db.flush()
        return {'paired':True}
    return audited(db,'exchange.pair',{},apply)


def status(db):
    s=db.get(ExchangeState,DOMAIN)
    if not s:
        return {'paired':False,'enabled':False,'allow_availability':False}
    inbound_expiry=s.inbound.get('expires_at') if s.inbound else None
    package = None
    if s.outbox:
        doc = ReleaseSnapshot.model_validate_json(s.outbox['document'])
        package = {'calendar_count': sum(i.kind == 'calendar' for i in doc.items),
            'todo_count': sum(i.kind == 'todo' for i in doc.items),
            'sources_fresh': doc.sources_fresh, 'expires_at': doc.expires_at,
            'expired': doc.expires_at <= now()}
    return {'paired':True,'endpoint':s.endpoint,'enabled':s.enabled,'allow_availability':s.allow_availability,
        'revision':s.revision,'acknowledged_revision':s.acknowledged_revision,'last_sent_at':s.last_sent_at,
        'error':s.error,'inbound_revision':s.inbound_revision,'inbound_expires_at':inbound_expiry,
        'queued':s.revision>s.acknowledged_revision, 'last_package':package}


def export_id(db,key):
    row=db.get(ExportIdentity,key)
    if not row:
        row=ExportIdentity(domain_id=DOMAIN,local_key=key)
        db.add(row);db.flush()
    return row.export_id


def content(db):
    p=preview(db)
    items=[]
    for entry in p['items']:
        if entry['candidate']:
            key='calendar:'+entry['export_key']
            items.append(CalendarProjection(export_id=export_id(db,key),**entry['candidate']))
    policy=policy_payload(db)
    todo_level = policy['type_rules']['todo']
    if not policy['paused'] and todo_level != 'private':
        for t in db.scalars(select(Todo).where(Todo.domain_id==DOMAIN,Todo.deleted.is_(False))):
            if t.release_title and t.release_revision==t.revision:
                items.append(TodoProjection(export_id=export_id(db,'todo:'+str(t.id)),title=t.release_title,
                    status=t.status,due_at=t.due_at if t.release_due and todo_level == 'title_due' else None))
    selected=[s for s in policy['sources'] if policy['type_rules']['calendar'] != 'private'
        and policy['rules'].get(s['id'],'private')!='private']
    observations=[s.last_synced_at for s in db.scalars(select(CalendarSource).where(CalendarSource.domain_id==DOMAIN))
        if str(s.id) in {s['id'] for s in selected} and s.last_synced_at]
    return {'policy_revision':policy['revision'],'sources_fresh':all(not s['stale'] for s in selected),
        'source_observed_at':min(observations).isoformat() if observations else None,
        'items':[i.model_dump(mode='json') for i in sorted(items,key=lambda i:str(i.export_id))]}


def exchange_once(sessions, *, vault=None, transport=None, force=False):
    """Caller holds the workspace mutation lock through recheck/send/receipt; never sends stale outbox blindly."""
    vault=vault or ExchangeKeys()
    with sessions() as db:
        s=db.get(ExchangeState,DOMAIN)
        if not s or not s.enabled:
            return
        if not force and s.next_attempt_at and s.next_attempt_at>now():
            return
        try:
            credentials=vault.get(str(s.pairing_id))
            if not credentials or not credentials.get('token'):
                raise ActionError('Connector credential unavailable.')
            wire=transport or Transport(s.endpoint,credentials['token'])
            projected=content(db)
            fingerprint=hashlib.sha256(json.dumps(projected,sort_keys=True).encode()).hexdigest()
            old=ReleaseSnapshot.model_validate_json(s.outbox['document']) if s.outbox else None
            # Renew lease while awake; policy/source mutations replace obsolete unsent snapshots.
            if not old or s.fingerprint!=fingerprint or old.issued_at<now()-timedelta(minutes=2):
                stamp=now();s.revision+=1
                doc=ReleaseSnapshot(message_id=uuid.uuid4(),pairing_id=s.pairing_id,revision=s.revision,
                    issued_at=stamp,expires_at=stamp+timedelta(minutes=15),**projected)
                s.outbox=seal(doc,credentials['private_key']);s.fingerprint=fingerprint
                audited(db,'exchange.seal',{'revision':s.revision,'count':len(doc.items)},lambda:None)
                db.commit()  # Immutable outbox survives a lost connection or process exit.
                db.info.pop("audit_attempts", None)
            if s.acknowledged_revision<s.revision:
                result=audited(db,'exchange.publish',{'revision':s.revision},
                    lambda:wire.request('POST','/v1/releases',s.outbox))
                document=ReleaseSnapshot.model_validate_json(s.outbox['document'])
                if result!={'status':'applied','revision':s.revision,'message_id':str(document.message_id)}:
                    raise ActionError('Connector receipt did not match.')
                s.acknowledged_revision=s.revision;s.last_sent_at=now()
                from .chat import report
                report(db,"Approved snapshot applied by connector.",operation="exchange_publish",changes=[{"revision":s.revision}],source_refs=[])
                db.commit()
                db.info.pop("audit_attempts", None)
            if s.allow_availability:
                result=audited(db,'exchange.inbox',{},lambda:wire.request('GET','/v1/inbox'))
                signed=result.get('snapshot')
                if signed:
                    incoming=unseal(signed,s.public_key,AvailabilitySnapshot,s.pairing_id,live=False)
                    digest=hashlib.sha256(signed['document'].encode()).hexdigest()
                    if incoming.revision<s.inbound_revision or (incoming.revision==s.inbound_revision and digest!=s.inbound_hash):
                        raise ActionError('Stale or conflicting inbound revision.')
                    # Expired inbox content is never made visible. Cursor still prevents replay.
                    if incoming.issued_at>now()+timedelta(seconds=30):
                        raise ActionError('Future inbound package.')
                    if incoming.revision>s.inbound_revision or s.inbound is None:
                        s.inbound_revision=incoming.revision;s.inbound_hash=digest
                        s.inbound=incoming.model_dump(mode='json')
                        db.get(LocalState,1).context_reset_at=now()
                        db.commit()
                        db.info.pop("audit_attempts", None)
                    audited(db,'exchange.inbox.ack',{'revision':incoming.revision},
                        lambda:wire.request('POST','/v1/inbox/ack',{'revision':incoming.revision}))
            s.error=None;s.failures=0;s.next_attempt_at=now()+timedelta(seconds=30)
            db.commit()
        except Exception:
            restore_audit_after_rollback(db)
            s=db.get(ExchangeState,DOMAIN)
            s.failures+=1
            s.next_attempt_at=now()+timedelta(seconds=min(300,15*2**min(s.failures,5)))
            s.error='Exchange unavailable or package rejected. Check pairing and retry; private data was not included in this error.'
            db.commit()


def overlays(db,start,end):
    s=db.get(ExchangeState,DOMAIN)
    if not s or not s.enabled or not s.allow_availability or not s.inbound:
        return []
    snapshot=AvailabilitySnapshot.model_validate(s.inbound)
    if snapshot.expires_at<=now():
        return []
    from datetime import datetime
    from zoneinfo import ZoneInfo
    result=[]
    for item in snapshot.items:
        a,b=datetime.fromisoformat(item.start),datetime.fromisoformat(item.end)
        if item.all_day:
            a,b=a.replace(tzinfo=ZoneInfo(item.timezone)),b.replace(tzinfo=ZoneInfo(item.timezone))
        if a<end and b>start:
            result.append(dict(id=str(item.export_id),occurrence_id=str(item.export_id),title='Unavailable',
                summary='',start=item.start,end=item.end,timezone=item.timezone,all_day=item.all_day,blocks_time=True,
                location='',recurrence_rule=None,status='scheduled',source='connector',source_id=None,local_note='',
                revision=snapshot.revision,source_refs=[],series_start=item.start,series_end=item.end))
    return result


def availability_status(db):
    s=db.get(ExchangeState,DOMAIN)
    if not s or not s.enabled or not s.allow_availability:
        return {'enabled':False,'stale':True,'expires_at':None}
    expiry=AvailabilitySnapshot.model_validate(s.inbound).expires_at if s.inbound else None
    return {'enabled':True,'stale':expiry is None or expiry<=now(),'expires_at':expiry.isoformat() if expiry else None}
