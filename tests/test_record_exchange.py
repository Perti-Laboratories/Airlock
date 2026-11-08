"""Real node/connector exchange against a synthetic independent recipient."""
import json
import uuid
from datetime import timedelta

import pytest
from airlock_contracts import RecordPolicy, RecordSnapshot, unseal, seal, utcnow
from airlock.models import RecordExchange, ExchangeState, now
from airlock.memory import DOMAIN
from airlock.exchange import content
from airlock.record_exchange import visible
from test_exchange_workspace import exchange, calendar, feed
from test_connector import harness


def policy(c, calendar='original', todo='title_due', paused=False):
    p = c.get('/api/release-policy').json()
    result = c.put('/api/release-policy', json={'expected_revision': p['revision'], 'paused': paused,
        'rules': {'local': 'busy'}, 'type_rules': {'calendar': calendar, 'todo': todo}})
    assert result.status_code == 200, result.text


def source_items():
    stamp = now()+timedelta(days=1)
    return [{'kind': 'calendar', 'export_id': str(uuid.uuid4()), 'title': 'Planning meeting',
        'start': stamp.isoformat(), 'end': (stamp+timedelta(hours=1)).isoformat(), 'timezone': 'UTC'},
        {'kind': 'todo', 'export_id': str(uuid.uuid4()), 'title': 'Prepare plan', 'status': 'open',
         'due_at': (stamp+timedelta(days=1)).isoformat()}]


def send(receiver, config, items, expected=None):
    status = receiver.get('/v2/harness/records', headers=harness(config)).json()
    permission = unseal(status['policy'], config['public_key'], RecordPolicy, config['pairing_id'])
    return receiver.put('/v2/harness/records', headers=harness(config), json={
        'expected_revision': status['revision'] if expected is None else expected,
        'policy_message_id': str(permission.message_id), 'items': items})


def test_automatic_incoming_lifecycle_local_chat_visibility_and_no_echo(exchange):
    c, sessions, receiver, config, wire, tick = exchange
    policy(c); calendar(c)
    tick()
    items = source_items()
    assert send(receiver, config, items).status_code == 200
    tick()
    remote = next(t for t in c.get('/api/todos').json() if t.get('read_only'))
    assert remote['title'] == 'Prepare plan' and remote['description'] == ''
    from airlock.calendar import list_events
    with sessions() as db:
        events = list_events(db, now(), now()+timedelta(days=3), include_overlays=True)
        assert any(e['title']=='Planning meeting' and e.get('origin')=='recipient' for e in events)
        assert all(i['title'] not in {'Planning meeting','Prepare plan'} for i in content(db)['items'])
    # Mirrors cannot mutate local source records, approve exports, or trigger tasks.
    assert c.put('/api/todos/'+remote['id'], json={'title': 'Overwrite', 'expected_revision': remote['revision']}).status_code == 409
    assert c.put('/api/todos/'+remote['id']+'/release', json={'title': 'Export', 'expected_revision': remote['revision']}).status_code == 409
    for status in ['done','open','archived']:
        items[1]['status'] = status
        items[0]['title'] = 'Updated meeting'
        assert send(receiver, config, items).status_code == 200
        tick()
        current = next(t for t in c.get('/api/todos').json() if t.get('read_only'))
        assert current['id']==remote['id'] and current['status']==status
    assert send(receiver, config, []).status_code == 200
    tick()
    assert c.get('/api/todos').json() == []
    assert len(feed(receiver, config)['items']) == 1  # Local calendar untouched.
    assert c.get('/api/exchange').json()['records']['todo_count'] == 0


def test_permissions_auth_schema_policy_tightening_and_resume(exchange):
    c, sessions, receiver, config, wire, tick = exchange
    policy(c); tick(); items=source_items()
    forbidden={**items[1], 'description': 'PRIVATE_NOTES'}
    r=send(receiver,config,[forbidden]); assert r.status_code==422 and 'PRIVATE_NOTES' not in r.text
    assert receiver.get('/v2/harness/records').status_code==401
    assert receiver.get('/v2/records',headers=harness(config)).status_code==401
    assert send(receiver,config,items).status_code==200; tick()
    policy(c,'busy','title')
    # Local read gate takes effect without waiting for the connector/network.
    with sessions() as db:
        values,_=visible(db)
        assert values == []  # A changed policy requires a freshly admitted snapshot.
    tick()
    assert send(receiver,config,items).status_code==422
    items[0]['title']='Busy';items[1]['due_at']=None
    assert send(receiver,config,items).status_code==200; tick()
    policy(c,'private','private');tick()
    assert c.get('/api/todos').json()==[]
    assert send(receiver,config,items).status_code==422
    policy(c);tick()
    assert c.get('/api/todos').json()==[]  # Restoring permissions does not revive old mirrors.
    assert send(receiver,config,items).status_code==200;tick()
    policy(c, paused=True)
    assert c.get('/api/todos').json()==[]
    policy(c)  # Rapid pause/resume, without a network tick between them.
    tick()
    assert c.get('/api/todos').json()==[]


def test_replay_conflict_tamper_wrong_grant_expiry_and_durable_ack(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    policy(c);tick();items=source_items()
    assert send(receiver,config,items).status_code==200
    snapshot=receiver.get('/v2/records',headers={'Authorization':'Bearer '+config['device_token']}).json()
    original=wire.request
    lost={'ack':True}
    def request(method,path,body=None):
        result=original(method,path,body)
        if path=='/v2/records/ack' and lost['ack']:
            lost['ack']=False
            raise OSError('Lost acknowledgement')
        return result
    wire.request=request
    tick()
    assert len(c.get('/api/todos').json())==1
    tick()
    with sessions() as db: assert db.get(ExchangeState,DOMAIN).error is None
    items[1]['status']='done';assert send(receiver,config,items).status_code==200;tick()
    def replay(method,path,body=None):
        return snapshot if path=='/v2/records' else original(method,path,body)
    wire.request=replay;tick()
    assert c.get('/api/todos').json()[0]['status']=='done'
    with sessions() as db: assert db.get(ExchangeState,DOMAIN).error
    wire.request=original
    assert send(receiver,config,items,expected=0).status_code==409
    with sessions() as db:
        row=db.get(RecordExchange,DOMAIN); doc=dict(row.inbound)
        stamp=now()
        doc['issued_at']=(stamp-timedelta(minutes=20)).isoformat()
        doc['expires_at']=(stamp-timedelta(minutes=5)).isoformat();row.inbound=doc;db.commit()
        assert visible(db)[0]==[]
    # Signed data is still rejected when it contains unknown fields or names a stale permission.
    parsed=json.loads(snapshot['snapshot']['document']); parsed['policy_message_id']=str(uuid.uuid4())
    parsed['revision']=999
    forged=seal(RecordSnapshot.model_validate(parsed),config['private_key'])
    wire.request=lambda method,path,body=None: {'snapshot':forged} if path=='/v2/records' else original(method,path,body)
    tick()
    with sessions() as db: assert db.get(RecordExchange,DOMAIN).inbound_revision==2


def test_disconnect_reconnect_requires_new_permission_and_mirrors_reach_chat(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    policy(c);tick();items=source_items()
    assert send(receiver,config,items).status_code==200;tick()
    response=c.post('/api/chat',json={'message':'What is on my to-do list?'})
    assert response.status_code==200,response.text
    from sqlalchemy import select
    from airlock.models import Message,KnowledgeSource
    with sessions() as db:
        messages=list(db.scalars(select(Message)))
        assert any(m.sender_type=='assistant' and m.metadata_.get('connector_context') for m in messages)
        assert db.scalar(select(KnowledgeSource).where(KnowledgeSource.kind=='message')) is None
    assert c.put('/api/exchange',json={'enabled':False,'allow_availability':False}).status_code==200
    assert c.get('/api/todos').json()==[]
    assert c.put('/api/exchange',json={'enabled':True,'allow_availability':False}).status_code==200
    tick()
    assert c.get('/api/todos').json()==[]
    assert send(receiver,config,items).status_code==200;tick()
    assert c.get('/api/todos').json()[0]['title']=='Prepare plan'
