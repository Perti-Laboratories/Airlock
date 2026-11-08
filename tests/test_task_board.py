"""Two real protocol peers, local DB, synthetic tasks and independent stores."""
import copy
import hashlib
import uuid
from datetime import timedelta
import pytest
from airlock_contracts import seal, utcnow
from airlock_contracts.board import BoardItem, BoardMove, BoardSnapshot
from airlock_connector import board_peer
from airlock.models import ExchangeState, Todo
from airlock.memory import DOMAIN
from test_exchange_workspace import exchange, feed
from test_record_exchange import policy, send


class Peer:
    def __init__(self, receiver, config):
        self.receiver, self.config = receiver, config
        self.state = {}; self.tasks = {}; self.revision = 0; self.applied = 0
    def request(self, method, path, body=None):
        r = self.receiver.request(method, path, json=body, headers={'Authorization':'Bearer '+self.config['harness_token']})
        r.raise_for_status(); return r.json()
    def persist(self, value): self.state = copy.deepcopy(value)
    def tick(self):
        records = [{'kind':'todo','export_id':k,'title':'Shared task','status': 'done' if v['column']=='done' else 'archived' if v['column']=='archive' else 'open'} for k,v in self.tasks.items()]
        result = send(self.receiver, self.config, records); result.raise_for_status(); self.revision = result.json()['revision']
        def source(): return self.revision, [BoardItem(export_id=k,**v) for k,v in self.tasks.items()]
        def apply(move):
            task = self.tasks.get(str(move.export_id))
            if not task: return 'rejected'
            if task['version'] != move.expected_version: return 'conflict'
            task.update(column=move.column,version=hashlib.sha256(uuid.uuid4().bytes).hexdigest()); self.applied += 1
            return 'applied'
        board_peer.sync(self.state, pairing=self.config['pairing_id'], role='harness', public_key=self.config['public_key'], request=self.request, persist=self.persist, source=source, apply=apply)


def create(c):
    r = c.post('/api/todos', json={'title':'PRIVATE_TITLE','description':'PRIVATE_NOTES'}); r.raise_for_status()
    task = r.json()['result']
    c.put('/api/todos/'+task['id']+'/release', json={'expected_revision':task['revision'],'title':'Reviewed task'}).raise_for_status()
    return task


def move(c, task, column):
    return c.post('/api/todos/'+task['id']+'/board', json={'column':column,'expected_column':task['board_column'],'expected_revision':task['revision'],'expected_version':task.get('board_version')})


def test_local_columns_reviews_notes_and_stale_moves(exchange):
    c, sessions, receiver, config, wire, tick = exchange
    policy(c); task = create(c)
    for column in ['working','agent_action','in_review','done','archive','backlog']:
        result = move(c, task, column); assert result.status_code == 200, result.text
        current = result.json()['result']
        assert current['board_column'] == column and current['description'] == 'PRIVATE_NOTES'
        assert current['release_revision'] == current['revision']
        assert move(c, task, column).status_code == 409
        task = current; tick()
        assert 'PRIVATE' not in str(feed(receiver, config))
    with sessions() as db:
        assert db.get(Todo, uuid.UUID(task['id'])).owner_type == 'user'


def test_both_directions_source_authority_retry_conflict_and_pause(exchange):
    c, sessions, receiver, config, wire, tick = exchange
    policy(c); task = create(c); tick()
    peer = Peer(receiver,config)
    remote_id = str(uuid.uuid4()); peer.tasks[remote_id] = {'column':'backlog','version':'a'*64}
    peer.tick(); tick()
    # Move the node-owned task from the independent recipient.
    peer.tick()
    released = next(iter(board_peer.visible(peer.state).values()))
    peer.state = board_peer.queue(peer.state, config['pairing_id'], 'harness', released, 'working')
    peer.tick(); tick(); peer.tick(); tick()
    local = next(t for t in c.get('/api/todos').json() if not t.get('read_only'))
    assert local['board_column'] == 'working' and local['description'] == 'PRIVATE_NOTES'
    assert peer.state['requests'][-1]['status'] == 'applied'
    # Move a recipient-owned mirror; notes and ordinary edit/release routes remain protected.
    remote = next(t for t in c.get('/api/todos').json() if t.get('read_only'))
    assert remote['board_editable']
    assert move(c, remote, 'archive').status_code == 200
    assert move(c, remote, 'done').status_code == 409  # one pending intent per task
    tick()
    original = peer.request
    lost = {'once': True}
    def lose(method,path,body=None):
        if path.endswith('/receipts') and lost['once']:
            lost['once']=False;raise OSError('Lost receipt')
        return original(method,path,body)
    peer.request=lose
    with pytest.raises(OSError): peer.tick()
    peer.request=original;peer.tick();tick()
    remote = next(t for t in c.get('/api/todos').json() if t.get('read_only'))
    assert remote['board_column']=='archive' and remote['board_move_status']=='applied'
    assert peer.applied == 1
    assert c.put('/api/todos/'+remote['id'],json={'title':'Forbidden','expected_revision':remote['revision']}).status_code==409
    # Source changed after mirror read: reject rather than overwrite.
    assert move(c,remote,'done').status_code==200
    peer.tasks[remote_id].update(column='in_review',version='b'*64)
    tick();peer.tick();tick()
    remote = next(t for t in c.get('/api/todos').json() if t.get('read_only'))
    assert remote['board_move_status']=='conflict' and remote['board_column']=='in_review'
    assert move(c,remote,'done').status_code==200
    policy(c,paused=True);tick()
    assert not any(t.get('read_only') for t in c.get('/api/todos').json())
    policy(c);tick();peer.tick();tick()
    assert peer.tasks[remote_id]['column']=='in_review'
    # Sidecar contains no source notes, names or titles.
    packet=receiver.get('/v3/harness/board',headers={'Authorization':'Bearer '+config['harness_token']})
    assert 'PRIVATE' not in packet.text and 'Reviewed task' not in packet.text


def test_connector_board_auth_and_unknown_fields(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    assert receiver.get('/v3/device/board').status_code==401
    assert receiver.get('/v3/device/board',headers={'Authorization':'Bearer '+config['harness_token']}).status_code==401
    assert receiver.post('/v3/harness/moves',headers={'Authorization':'Bearer '+config['harness_token']},json={'description':'PRIVATE'}).status_code==422


def test_board_membership_replay_wrong_role_and_expired_envelopes(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    policy(c);tick();peer=Peer(receiver,config)
    ident=str(uuid.uuid4());peer.tasks[ident]={'column':'backlog','version':'a'*64};peer.tick()
    stamp=utcnow()
    packet=BoardSnapshot(message_id=uuid.uuid4(),pairing_id=config['pairing_id'],revision=2,
        issued_at=stamp,expires_at=stamp+timedelta(minutes=15),source='harness',basis_revision=peer.revision,
        items=[BoardItem(export_id=ident,column='backlog',version='a'*64)])
    headers={'Authorization':'Bearer '+config['harness_token']}
    def post(value): return receiver.post('/v3/harness/board',headers=headers,json=value)
    assert post(packet.model_dump(mode='json')).status_code==200
    assert post(packet.model_dump(mode='json')).status_code==200
    assert post(packet.model_copy(update={'message_id':uuid.uuid4()}).model_dump(mode='json')).status_code==409
    assert post(packet.model_copy(update={'revision':3,'items':[BoardItem(export_id=uuid.uuid4(),column='done',version='b'*64)]}).model_dump(mode='json')).status_code==409
    assert post({**packet.model_dump(mode='json'),'notes':'PRIVATE'}).status_code==422
    assert post(packet.model_copy(update={'source':'device'}).model_dump(mode='json')).status_code==422
    expired=packet.model_copy(update={'issued_at':stamp-timedelta(minutes=30),'expires_at':stamp-timedelta(minutes=15)})
    assert post(expired.model_dump(mode='json')).status_code==422
