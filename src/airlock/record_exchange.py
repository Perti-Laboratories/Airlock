"""Leased recipient-origin records, isolated from local source and release tables."""
import hashlib
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from airlock_contracts import RecordPolicy, RecordRules, RecordSnapshot, filter_records, seal, unseal
from .memory import DOMAIN, ActionError, audited
from .models import ExchangeState, RecordExchange, ReleasePolicy, LocalState, now


def rules(db):
    policy = db.get(ReleasePolicy, DOMAIN)
    state = db.get(ExchangeState, DOMAIN)
    if not state or not state.enabled or not policy or policy.paused:
        return RecordRules()
    return RecordRules(**{key: policy.type_rules[key] for key in ('calendar', 'todo')})


def sync(db, state, credentials, wire):
    row = db.get(RecordExchange, DOMAIN)
    if row is None:
        row = RecordExchange(domain_id=DOMAIN)
        db.add(row)
        db.flush()
    previous = RecordPolicy.model_validate_json(row.policy['document']) if row.policy else None
    allowed = rules(db)
    local_policy = db.get(ReleasePolicy, DOMAIN)
    local_revision = local_policy.revision if local_policy else 0
    changed = row.policy_revision != local_revision
    if changed or previous is None or previous.rules != allowed or previous.issued_at < now()-timedelta(minutes=2):
        stamp = now()
        permission = RecordPolicy(message_id=uuid.uuid4(), pairing_id=state.pairing_id,
            revision=previous.revision+1 if previous else 1, issued_at=stamp,
            expires_at=stamp+timedelta(minutes=15), rules=allowed)
        row.policy_revision = local_revision
        row.policy = seal(permission, credentials['private_key'])
        if changed or previous is None or previous.rules != allowed:
            row.inbound = None  # A changed permission cannot revive prior records.
        db.get(LocalState, 1).context_reset_at = now()
        audited(db, 'exchange.records.permission', {'revision': permission.revision}, lambda: None)
        db.commit()
        db.info.pop('audit_attempts', None)
    permission = RecordPolicy.model_validate_json(row.policy['document'])
    try:
        result = audited(db, 'exchange.records.policy', {'revision': permission.revision},
            lambda: wire.request('POST', '/v2/record-policy', row.policy))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        row.error = 'Update the connector to enable automatic calendar and to-do return.'
        row.inbound = None
        return
    if result != {'status': 'applied', 'revision': permission.revision, 'message_id': str(permission.message_id)}:
        raise ActionError('Record permission receipt did not match.')
    result = audited(db, 'exchange.records.poll', {}, lambda: wire.request('GET', '/v2/records'))
    if set(result) != {'snapshot'}:
        raise ActionError('Invalid record inbox.')
    signed = result['snapshot']
    if signed is not None:
        incoming = unseal(signed, state.public_key, RecordSnapshot, state.pairing_id, live=False)
        digest = hashlib.sha256(signed['document'].encode()).hexdigest()
        if incoming.revision < row.inbound_revision or (incoming.revision == row.inbound_revision and digest != row.inbound_hash):
            raise ActionError('Stale or conflicting record snapshot.')
        if incoming.policy_message_id != permission.message_id or incoming.expires_at > permission.expires_at:
            raise ActionError('Record snapshot does not match its permission.')
        if incoming.issued_at > now()+timedelta(seconds=30):
            raise ActionError('Future record snapshot.')
        if filter_records(incoming.items, allowed) != incoming.items:
            raise ActionError('Record snapshot exceeds current sharing rules.')
        if incoming.revision != row.inbound_revision or row.inbound is None:
            row.inbound_revision, row.inbound_hash = incoming.revision, digest
            row.inbound = incoming.model_dump(mode='json')
            db.get(LocalState, 1).context_reset_at = now()
            from .chat import report
            report(db, 'Connected planning records updated.', operation='exchange_records',
                changes=[{'revision': incoming.revision, 'count': len(incoming.items)}], source_refs=[])
            db.commit()  # Record visibility and replay cursor are durable before acknowledgement.
            db.info.pop('audit_attempts', None)
        receipt = audited(db, 'exchange.records.ack', {'revision': incoming.revision},
            lambda: wire.request('POST', '/v2/records/ack', {'revision': incoming.revision}))
        if receipt != {'status': 'applied'}:
            raise ActionError('Invalid record acknowledgement.')
    row.error = None


def visible(db):
    state = db.get(ExchangeState, DOMAIN)
    row = db.get(RecordExchange, DOMAIN)
    if not state or not state.enabled or not row or not row.inbound or not row.policy:
        return [], None
    snapshot = RecordSnapshot.model_validate(row.inbound)
    policy = RecordPolicy.model_validate_json(row.policy['document'])
    if snapshot.expires_at <= now() or policy.expires_at <= now():
        return [], None
    # Recheck policy on every UI/model read, before a background withdrawal can run.
    return filter_records(snapshot.items, rules(db)), snapshot


def status(db):
    items, snapshot = visible(db)
    row = db.get(RecordExchange, DOMAIN)
    allowed = rules(db)
    enabled = allowed.calendar != 'private' or allowed.todo != 'private'
    return {'enabled': enabled, 'stale': not enabled or snapshot is None,
        'revision': row.inbound_revision if row else 0,
        'expires_at': snapshot.expires_at.isoformat() if snapshot else None,
        'calendar_count': sum(i.kind == 'calendar' for i in items),
        'todo_count': sum(i.kind == 'todo' for i in items), 'error': row.error if row else None}


def mirror_id(state, item):
    # Namespaced away from local primary keys and legacy availability identifiers.
    return str(uuid.uuid5(state.pairing_id, 'recipient:'+item.kind+':'+str(item.export_id)))


def calendar_overlays(db, start, end):
    items, snapshot = visible(db)
    state = db.get(ExchangeState, DOMAIN)
    result = []
    for item in items:
        if item.kind != 'calendar':
            continue
        a, b = datetime.fromisoformat(item.start), datetime.fromisoformat(item.end)
        if item.all_day:
            a, b = a.replace(tzinfo=ZoneInfo(item.timezone)), b.replace(tzinfo=ZoneInfo(item.timezone))
        if a < end and b > start:
            ident = mirror_id(state, item)
            result.append(dict(id=ident, occurrence_id=ident, title=item.title, summary='',
                start=item.start, end=item.end, timezone=item.timezone, all_day=item.all_day, blocks_time=True,
                location='', recurrence_rule=None, status='scheduled', source='connector', source_id=None,
                local_note='', revision=snapshot.revision, source_refs=[], series_start=item.start,
                series_end=item.end, read_only=True, origin='recipient'))
    return result


def todo_overlays(db):
    items, snapshot = visible(db)
    state = db.get(ExchangeState, DOMAIN)
    return [dict(id=mirror_id(state, item), title=item.title, description='',
        due_at=item.due_at.isoformat() if item.due_at else None, scheduled_start_at=None,
        estimated_minutes=None, priority='normal', status=item.status, revision=snapshot.revision,
        source_refs=[], release_title=None, release_due=False, release_revision=None,
        read_only=True, origin='recipient') for item in items if item.kind == 'todo']
