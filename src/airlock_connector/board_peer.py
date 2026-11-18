"""Shared peer state machine; the caller owns persistence and task authorization."""
import copy
import hashlib
import uuid
from datetime import datetime, timedelta
import httpx
from airlock_contracts import seal, unseal, utcnow
from airlock_contracts.board import BoardSnapshot, BoardMove, BoardInbox, BoardReceipt


def queue(state, pairing, role, item, column):
    result = copy.deepcopy(state or {})
    if not result.get('enabled'):
        raise ValueError('Task sharing is unavailable. Sync and try again.')
    requests = result.setdefault('requests', [])
    if sum(r['status'] == 'pending' for r in requests) >= 100:
        raise ValueError('Too many pending moves. Wait for sync before adding more.')
    if any(r['move']['export_id'] == str(item.export_id) and r['status'] == 'pending' for r in requests):
        raise ValueError('This task already has a pending move.')
    stamp = utcnow()
    move = BoardMove(message_id=uuid.uuid4(), pairing_id=pairing, revision=1, source=role,
        issued_at=stamp, expires_at=stamp+timedelta(minutes=15), export_id=item.export_id,
        column=column, expected_version=item.version, permission_revision=result['permission_revision'])
    requests[:] = [r for r in requests if r['status'] == 'pending'][-99:] + [
        {'move': move.model_dump(mode='json'), 'status': 'pending'}]
    return result


def cancel(state):
    result = copy.deepcopy(state or {})
    result.update(enabled=False, feed=None)
    for entry in result.get('requests', []):
        if entry['status'] == 'pending':
            entry['status'] = 'rejected'
    return result


def visible(state):
    if not state or not state.get('enabled') or not state.get('feed'):
        return {}
    feed = BoardSnapshot.model_validate(state['feed'])
    if feed.expires_at <= utcnow():
        return {}
    return {str(i.export_id): i for i in feed.items}


def sync(state, *, pairing, role, public_key, request, persist, source, apply, private_key=None):
    """persist must commit state with any task mutation made by apply, atomically."""
    state = copy.deepcopy(state or {})
    path = '/v3/'+role
    def send(document):
        return seal(document, private_key) if role == 'device' else document.model_dump(mode='json')
    try:
        inbox = unseal(request('GET', path+'/board'), public_key, BoardInbox, pairing)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        state.update(enabled=False, feed=None, upgrade_required=True)
        persist(state)
        return
    if inbox.source != role:
        raise ValueError('Wrong board audience.')
    state.update(enabled=inbox.enabled, permission_revision=inbox.permission_revision, upgrade_required=False)
    feed = inbox.feed
    if feed:
        feed.check_live()
        if feed.source == role or feed.pairing_id != inbox.pairing_id:
            raise ValueError('Wrong board source.')
        digest = hashlib.sha256(feed.model_dump_json().encode()).hexdigest()
        previous = state.get('peer_revision', 0)
        if feed.revision < previous or (feed.revision == previous and state.get('peer_hash') != digest):
            raise ValueError('Stale board snapshot.')
        state.update(peer_revision=feed.revision, peer_hash=digest)
    state['feed'] = feed.model_dump(mode='json') if feed else None
    receipts = {str(r.operation_id): r.status for r in inbox.receipts}
    for entry in state.get('requests', []):
        move = BoardMove.model_validate(entry['move'])
        if str(move.message_id) in receipts:
            entry['status'] = receipts[str(move.message_id)]
        elif entry['status'] == 'pending' and (move.expires_at <= utcnow() or not inbox.enabled or move.permission_revision != inbox.permission_revision):
            entry['status'] = 'expired' if move.expires_at <= utcnow() else 'rejected'
    persist(state)
    processed = state.setdefault('processed', {})
    for move in inbox.moves:
        key = str(move.message_id)
        if move.source == role or move.pairing_id != inbox.pairing_id:
            raise ValueError('Invalid incoming move.')
        if key not in processed:
            if move.expires_at <= utcnow():
                outcome = 'expired'
            elif not inbox.enabled or move.permission_revision != inbox.permission_revision:
                outcome = 'rejected'
            else:
                move.check_live()
                outcome = apply(move)
            processed[key] = {'status': outcome, 'expires_at': move.expires_at.isoformat()}
            persist(state)  # A task mutation and its deduplication receipt commit together.
        receipt = BoardReceipt(operation_id=move.message_id, status=processed[key]['status'])
        if request('POST', path+'/receipts', receipt.model_dump(mode='json')) != {'status': 'applied'}:
            raise ValueError('Invalid board receipt.')
    for entry in state.get('requests', []):
        if entry['status'] != 'pending':
            continue
        move = BoardMove.model_validate(entry['move'])
        try:
            response = request('POST', path+'/moves', send(move))
            if response != {'status': 'queued', 'operation_id': str(move.message_id)}:
                raise ValueError('Invalid move receipt.')
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            entry['status'] = 'conflict'
    basis, items = source()
    stamp = utcnow()
    snapshot = BoardSnapshot(message_id=uuid.uuid4(), pairing_id=pairing,
        revision=state.get('revision', 0)+1, issued_at=stamp, expires_at=stamp+timedelta(minutes=15),
        source=role, basis_revision=basis, items=items if inbox.enabled else [])
    # Persist before send; a lost acknowledgement cannot reuse this revision with new bytes.
    state['revision'] = snapshot.revision
    state['processed'] = {k: v for k, v in processed.items()
        if datetime.fromisoformat(v['expires_at']) > stamp-timedelta(days=1)}
    persist(state)
    if request('POST', path+'/board', send(snapshot)) != {'status': 'applied', 'revision': snapshot.revision}:
        raise ValueError('Invalid board publication receipt.')
