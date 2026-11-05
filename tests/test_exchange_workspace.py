import json
import uuid
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from airlock_contracts import utcnow
from airlock_connector.cli import provision
from airlock_connector.service import create_connector
from airlock.exchange import pair, exchange_once, content, overlays, validate_endpoint
from airlock.models import ExchangeState, CalendarSource, Todo, now
from airlock.memory import DOMAIN
from test_connector import harness


class Vault:
    def __init__(self): self.values={}
    def get(self,key): return self.values.get(key)
    def set(self,key,value): self.values[key]=value


class Wire:
    def __init__(self,client): self.client=client; self.token=None; self.lose=False; self.offline=False
    def request(self,method,path,body=None):
        if self.offline: raise OSError('Offline')
        r=self.client.request(method,path,json=body,headers={'Authorization':'Bearer '+self.token} if self.token else {})
        r.raise_for_status()
        if self.lose and path=='/v1/releases':
            self.lose=False;raise OSError('Receipt lost')
        return r.json()


@pytest.fixture
def exchange(workspace,tmp_path):
    c,llm,sessions,settings=workspace
    config=provision(tmp_path/'receiver','http://127.0.0.1:8742')
    receiver=TestClient(create_connector(config,tmp_path/'receiver/connector.sqlite3'))
    wire=Wire(receiver);vault=Vault()
    test_settings=settings.model_copy(update={'exchange_allow_loopback':True})
    invitation=json.loads((tmp_path/'receiver/invitation.json').read_text())
    with sessions() as db:
        pair(db,invitation,test_settings,vault,wire);db.commit()
        state=db.get(ExchangeState,DOMAIN);state.enabled=True;db.commit()
    wire.token=vault.get(config['pairing_id'])['token']
    def tick():exchange_once(sessions,vault=vault,transport=wire,force=True)
    return c,sessions,receiver,config,wire,tick


def calendar(c):
    stamp=(now()+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0)
    body={'title':'PRIVATE_SENTINEL title','summary':'PRIVATE_SENTINEL description','location':'PRIVATE_SENTINEL location',
        'start':stamp.isoformat(),'end':(stamp+timedelta(hours=1)).isoformat(),'timezone':'UTC'}
    r=c.post('/api/calendar',json=body);assert r.status_code==200,r.text
    return body,r.json()['event_id']


def allow(c):
    policy=c.get('/api/release-policy').json()
    r=c.put('/api/release-policy',json={'expected_revision':policy['revision'],'paused':False,'rules':{'local':'busy'}})
    assert r.status_code==200,r.text


def feed(receiver,config):
    r=receiver.get('/v1/harness/projections',headers=harness(config));assert r.status_code==200,r.text
    return r.json()


def test_policy_withdrawal_edit_identity_lost_receipt_and_offline(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    body,ident=calendar(c);allow(c)
    wire.lose=True;tick()
    first=feed(receiver,config);assert first['items'][0]['title']=='Busy'
    assert 'PRIVATE_SENTINEL' not in json.dumps(first)
    with sessions() as db:
        state=db.get(ExchangeState,DOMAIN);assert state.acknowledged_revision==0 and state.error
        original=state.outbox
    tick()
    with sessions() as db:
        state=db.get(ExchangeState,DOMAIN);assert state.acknowledged_revision==1 and state.outbox==original
    body['title']='PRIVATE_SENTINEL changed';body['expected_revision']=1
    assert c.put('/api/calendar/'+ident,json=body).status_code==200
    tick();assert feed(receiver,config)['items'][0]['export_id']==first['items'][0]['export_id']
    wire.offline=True
    policy=c.get('/api/release-policy').json()
    assert c.put('/api/release-policy',json={'expected_revision':policy['revision'],'paused':True,'rules':{'local':'busy'}}).status_code==200
    tick()
    wire.offline=False;tick()
    assert feed(receiver,config)['items']==[]
    with sessions() as db:
        assert 'PRIVATE_SENTINEL' not in json.dumps(db.get(ExchangeState,DOMAIN).outbox)


def test_todo_review_complete_reopen_delete_convergence(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    allow(c)
    r=c.post('/api/todos',json={'title':'PRIVATE_SENTINEL task','description':'PRIVATE_SENTINEL body'});assert r.status_code==200,r.text
    todo=r.json()['result'];ident=todo['id']
    tick();assert feed(receiver,config)['items']==[]
    assert c.put('/api/todos/'+ident+'/release',json={'expected_revision':1,'title':'Prepare update','include_due':False}).status_code==200
    tick();first=feed(receiver,config)['items'][0];assert first['status']=='open'
    for revision,status in [(1,'done'),(2,'open')]:
        r=c.put('/api/todos/'+ident,json={'title':'PRIVATE_SENTINEL task','description':'PRIVATE_SENTINEL body','status':status,'expected_revision':revision});assert r.status_code==200,r.text
        tick();assert feed(receiver,config)['items'][0]['status']==status # standing status permission
        assert c.put('/api/todos/'+ident+'/release',json={'expected_revision':revision+1,'title':'Prepare update'}).status_code==200
        tick();item=feed(receiver,config)['items'][0]
        assert item['status']==status and item['export_id']==first['export_id']
    assert c.post('/api/todos/'+ident+'/delete',json={'expected_revision':3}).status_code==200
    tick();assert feed(receiver,config)['items']==[]


def test_inbound_default_denied_minimal_readonly_no_loop_and_expiry(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    stamp=utcnow()+timedelta(days=1)
    item={'export_id':str(uuid.uuid4()),'start':stamp.isoformat(),'end':(stamp+timedelta(hours=1)).isoformat(),'timezone':'UTC'}
    assert receiver.put('/v1/harness/availability',headers=harness(config),json={'expected_revision':0,'items':[item]}).status_code==200
    tick()
    with sessions() as db:assert overlays(db,stamp-timedelta(days=1),stamp+timedelta(days=1))==[]
    assert c.put('/api/exchange',json={'enabled':True,'allow_availability':True}).status_code==200
    tick()
    with sessions() as db:
        visible=overlays(db,stamp-timedelta(days=1),stamp+timedelta(days=1));assert visible[0]['title']=='Unavailable'
        assert content(db)['items']==[]
    assert c.post('/api/calendar/'+item['export_id']+'/cancel',json={'expected_revision':1}).status_code==409
    assert c.put('/api/exchange',json={'enabled':True,'allow_availability':False}).status_code==200
    with sessions() as db:assert overlays(db,stamp-timedelta(days=1),stamp+timedelta(days=1))==[]
    assert c.put('/api/exchange',json={'enabled':True,'allow_availability':True}).status_code==200
    tick()
    with sessions() as db:
        state=db.get(ExchangeState,DOMAIN);data=dict(state.inbound)
        data['issued_at']=(now()-timedelta(hours=1)).isoformat();data['expires_at']=(now()-timedelta(minutes=50)).isoformat()
        state.inbound=data;db.commit()
        assert overlays(db,stamp-timedelta(days=1),stamp+timedelta(days=1))==[]


def test_disable_does_not_contact_connector(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    assert c.put('/api/exchange',json={'enabled':False,'allow_availability':False}).status_code==200
    wire.offline=True;tick()
    with sessions() as db:assert db.get(ExchangeState,DOMAIN).error is None


def test_transport_origin_restrictions():
    for value in ['http://example.com','http://localhost:8742','https://user:pass@example.com','https://example.com/path','https://example.com/?secret=1']:
        with pytest.raises(Exception):validate_endpoint(value)
    assert validate_endpoint('https://connector.example.com/')=='https://connector.example.com'
    with pytest.raises(Exception):validate_endpoint('http://127.0.0.1:8742')
    assert validate_endpoint('http://127.0.0.1:8742',True)=='http://127.0.0.1:8742'


def test_task_title_edits_invalidate_but_due_updates_follow_explicit_rule(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    allow(c)
    t=c.post('/api/todos',json={'title':'Original task'}).json()['result']
    assert c.put('/api/todos/'+t['id']+'/release',json={'expected_revision':1,'title':'Generic task','include_due':True}).status_code==200
    due=(now()+timedelta(days=2)).isoformat()
    assert c.put('/api/todos/'+t['id'],json={'title':'Original task','due_at':due,'expected_revision':1}).status_code==200
    tick();assert feed(receiver,config)['items'][0]['due_at'] is not None
    assert c.put('/api/todos/'+t['id'],json={'title':'Changed meaning','due_at':due,'expected_revision':2}).status_code==200
    tick();assert feed(receiver,config)['items']==[]


def test_chat_todo_routes_without_canonical_memory(workspace):
    c,llm,sessions,settings=workspace
    llm.decision={'answer':'Okay','action':'todo_create','target_id':None,'title':'','content':'','memory_type':'fact','impact_level':'low',
        'todo':{'title':'Synthetic notebook check','description':'Local-only details','status':'open'}}
    r=c.post('/api/chat',json={'message':'Add a to-do to check the synthetic notebook.'})
    assert r.status_code==200,r.text
    assert c.get('/api/todos').json()[0]['title']=='Synthetic notebook check'
    assert c.get('/api/memories').json()==[]
    with sessions() as db:
        task=db.query(Todo).one();assert task.source_refs[0]['type']!='local_todo_editor'


def test_invalid_invitation_and_remote_task_authority_denied(workspace):
    c,llm,sessions,settings=workspace
    r=c.post('/api/exchange/pair',json={'invitation':{'endpoint':'http://evil.test','code':'PRIVATE_SECRET'}})
    assert r.status_code==422 and 'PRIVATE_SECRET' not in r.text
    r=c.post('/api/todos',json={'title':'Task','agent_task':True,'workflow_task_id':str(uuid.uuid4())})
    assert r.status_code==422
    assert c.get('/api/todos').json()==[]


def test_local_delivery_diagnostics_count_prepared_records_without_private_fields(exchange, monkeypatch):
    from airlock import exchange as service
    c, sessions, receiver, config, wire, tick = exchange
    calendar(c)
    allow(c)
    wire.offline = True
    tick()
    pending = c.get('/api/exchange').json()
    assert pending['queued']
    assert pending['last_package']['calendar_count'] == 1
    assert pending['last_package']['todo_count'] == 0
    assert pending['last_package']['sources_fresh']
    assert not pending['last_package']['expired']
    assert 'PRIVATE_SENTINEL' not in json.dumps(pending)
    wire.offline = False
    tick()
    delivered = c.get('/api/exchange').json()
    assert not delivered['queued']
    assert delivered['acknowledged_revision'] == delivered['revision']
    future = now() + timedelta(minutes=16)
    monkeypatch.setattr(service, 'now', lambda: future)
    assert c.get('/api/exchange').json()['last_package']['expired']


def test_type_levels_filter_and_withdraw_at_receiver_even_after_lost_receipt(exchange):
    c, sessions, receiver, config, wire, tick = exchange
    _, event_id = calendar(c)
    due = (now() + timedelta(days=2)).isoformat()
    task = c.post('/api/todos', json={'title': 'PRIVATE_TASK',
        'description': 'PRIVATE_NOTES', 'due_at': due}).json()['result']
    c.put('/api/todos/' + task['id'] + '/release', json={
        'expected_revision': 1, 'title': 'Approved task', 'include_due': True})
    # Unreviewed tasks remain private even when the type is on.
    c.post('/api/todos', json={'title': 'PRIVATE_UNREVIEWED'})

    def save(calendar='original', todo='title_due'):
        p = c.get('/api/release-policy').json()
        r = c.put('/api/release-policy', json={
            'expected_revision': p['revision'], 'paused': False,
            'rules': {'local': 'original'}, 'acknowledge_titles': True,
            'type_rules': {'calendar': calendar, 'todo': todo}})
        assert r.status_code == 200, r.text
        return r.json()

    save()
    tick()
    first = feed(receiver, config)['items']
    assert len(first) == 2
    calendar_id = next(i['export_id'] for i in first if i['kind'] == 'calendar')
    todo_id = next(i['export_id'] for i in first if i['kind'] == 'todo')
    assert next(i for i in first if i['kind'] == 'todo')['due_at'] is not None

    p = save('busy', 'title')
    # A fresh reviewed title still cannot bypass the type ceiling.
    assert c.put('/api/release-policy/events/' + event_id, json={
        'expected_event_revision': 1, 'expected_policy_revision': p['revision'],
        'mode': 'reviewed', 'display_title': 'PRIVATE_REVIEWED_TITLE'}).status_code == 200
    tick()
    items = feed(receiver, config)['items']
    assert next(i for i in items if i['kind'] == 'calendar')['title'] == 'Busy'
    assert next(i for i in items if i['kind'] == 'todo')['due_at'] is None
    assert 'PRIVATE' not in json.dumps(items)
    assert {i['export_id'] for i in items} == {calendar_id, todo_id}

    save('private', 'title')
    tick()
    assert [i['kind'] for i in feed(receiver, config)['items']] == ['todo']
    save('private', 'private')
    wire.lose = True
    tick()
    assert feed(receiver, config)['items'] == []
    tick()  # Lost receipt retry cannot restore records withdrawn by type policy.
    assert feed(receiver, config)['items'] == []
    with sessions() as db:
        assert json.loads(db.get(ExchangeState, DOMAIN).outbox['document'])['items'] == []


def test_type_due_permission_does_not_override_task_review(exchange):
    c, _, receiver, config, _, tick = exchange
    task = c.post('/api/todos', json={'title': 'Task',
        'due_at': (now() + timedelta(days=2)).isoformat()}).json()['result']
    c.put('/api/todos/' + task['id'] + '/release', json={
        'expected_revision': 1, 'title': 'Approved task', 'include_due': False})
    assert c.put('/api/release-policy', json={'expected_revision': 0,
        'paused': False, 'rules': {}, 'type_rules': {'todo': 'title_due'}}).status_code == 200
    tick()
    assert feed(receiver, config)['items'][0]['due_at'] is None
