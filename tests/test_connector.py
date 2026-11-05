import json
import uuid
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from airlock_contracts import keys, seal, unseal, ReleaseSnapshot, AvailabilitySnapshot, utcnow
from airlock_connector.cli import provision
from airlock_connector.service import create_connector, store


@pytest.fixture
def connector(tmp_path):
    cfg=provision(tmp_path/'connector','http://127.0.0.1:8742')
    path=tmp_path/'connector/connector.sqlite3'
    client=TestClient(create_connector(cfg,path))
    private,public=keys()
    pair=client.post('/v1/pair',json={'code':cfg['pairing_code'],'public_key':public})
    assert pair.status_code==200
    return client,cfg,path,private,public


def release(cfg,revision=1,**kw):
    stamp=utcnow()
    data=dict(message_id=uuid.uuid4(),pairing_id=cfg['pairing_id'],revision=revision,
        issued_at=stamp,expires_at=stamp+timedelta(minutes=15),policy_revision=1,sources_fresh=True,items=[])
    data.update(kw)
    return ReleaseSnapshot(**data)


def device(cfg):
    return {'Authorization':'Bearer '+cfg['device_token']}


def harness(cfg):
    return {'Authorization':'Bearer '+cfg['harness_token']}


def event():
    a=utcnow()+timedelta(days=1)
    return {'kind':'calendar','export_id':str(uuid.uuid4()),'title':'Busy','busy':True,
        'all_day':False,'start':a.isoformat(),'end':(a+timedelta(hours=1)).isoformat(),'timezone':'UTC'}


def test_atomic_replace_replay_restart_and_auth(connector):
    c,cfg,path,key,_=connector
    item=event();one=seal(release(cfg,items=[item]),key)
    assert c.post('/v1/releases',json=one,headers=harness(cfg)).status_code==401
    assert c.get('/v1/harness/projections',headers=device(cfg)).status_code==401
    for _ in range(2):
        assert c.post('/v1/releases',json=one,headers=device(cfg)).json()['revision']==1
    feed=c.get('/v1/harness/projections',headers=harness(cfg)).json();assert len(feed['items'])==1
    c2=TestClient(create_connector(cfg,path))
    assert c2.get('/v1/harness/projections',headers=harness(cfg)).json()==feed
    two=seal(release(cfg,revision=2),key)
    assert c2.post('/v1/releases',json=two,headers=device(cfg)).status_code==200
    assert c.post('/v1/releases',json=one,headers=device(cfg)).status_code==409
    assert c.post('/v1/releases',json=seal(release(cfg,revision=2,items=[item]),key),headers=device(cfg)).status_code==409
    assert c.get('/v1/harness/projections',headers=harness(cfg)).json()['items']==[]


def test_reject_extra_private_fields_tampering_audience_expiry(connector):
    c,cfg,path,key,_=connector
    doc=seal(release(cfg,items=[event()]),key)
    bad=dict(doc,document=doc['document'].replace('Busy','Private'))
    assert c.post('/v1/releases',json=bad,headers=device(cfg)).status_code==422
    for mutate in ('extra','audience','expiry'):
        data=release(cfg).model_dump(mode='json')
        if mutate=='extra':data['source_refs']=[{'secret':'SENTINEL'}]
        if mutate=='audience':data['pairing_id']=str(uuid.uuid4())
        if mutate=='expiry':
            data['issued_at']=(utcnow()-timedelta(hours=1)).isoformat();data['expires_at']=(utcnow()-timedelta(minutes=50)).isoformat()
        # Sign arbitrary bytes to prove the receiver validates even an authenticated sender.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64
        document=json.dumps(data)
        signed={'document':document,'signature':base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(key)).sign(document.encode())).decode()}
        r=c.post('/v1/releases',json=signed,headers=device(cfg));assert r.status_code==422;assert 'SENTINEL' not in r.text
    assert 'SENTINEL' not in path.read_bytes().decode(errors='ignore')


def test_availability_strict_ownership_receipt_and_revocation(connector):
    c,cfg,path,key,_=connector
    item=event();item.pop('kind');item.pop('busy');item['title']='Unavailable'
    body={'expected_revision':0,'items':[item]}
    assert c.put('/v1/harness/availability',json=body,headers=device(cfg)).status_code==401
    assert c.put('/v1/harness/availability',json=body,headers=harness(cfg)).status_code==200
    signed=c.get('/v1/inbox',headers=device(cfg)).json()['snapshot']
    snap=unseal(signed,cfg['public_key'],AvailabilitySnapshot,cfg['pairing_id']);assert len(snap.items)==1
    assert c.post('/v1/inbox/ack',json={'revision':1},headers=device(cfg)).status_code==200
    assert c.get('/v1/harness/availability',headers=harness(cfg)).json()['acknowledged_revision']==1
    assert c.put('/v1/harness/availability',json=body,headers=harness(cfg)).status_code==409
    body['expected_revision']=1;body['items'][0]['title']='Secret doctor appointment'
    assert c.put('/v1/harness/availability',json=body,headers=harness(cfg)).status_code==422
    with store(path) as db:db.execute('UPDATE state SET revoked=1 WHERE id=1')
    assert c.get('/v1/harness/projections',headers=harness(cfg)).status_code==403
    assert c.get('/v1/inbox',headers=device(cfg)).status_code==403


def test_browser_and_oversize_boundary(connector):
    c,cfg,*_=connector
    assert c.get('/v1/harness/projections',headers={**harness(cfg),'Origin':'https://evil.test'}).status_code==403
    assert c.post('/v1/releases',content='x'*1_000_001,headers={**device(cfg),'Content-Type':'application/json'}).status_code==413


def test_expired_feed_does_not_expose_old_projection(connector):
    c,cfg,path,key,_=connector
    snapshot=release(cfg,items=[event()])
    assert c.post('/v1/releases',json=seal(snapshot,key),headers=device(cfg)).status_code==200
    data=snapshot.model_dump(mode='json');data['issued_at']=(utcnow()-timedelta(hours=1)).isoformat();data['expires_at']=(utcnow()-timedelta(minutes=50)).isoformat()
    with store(path) as db:db.execute('UPDATE state SET release_body=? WHERE id=1',(json.dumps(data),))
    feed=c.get('/v1/harness/projections',headers=harness(cfg)).json()
    assert feed['stale'] and feed['items']==[]


@pytest.mark.parametrize('change',[{'timezone':'No/Such_Zone'},{'all_day':True},{'end':'2000-01-01T00:00:00Z'},{'instructions':'run shell'}])
def test_harness_invalid_availability_is_bounded_safe_error(connector,change):
    c,cfg,*_=connector
    item=event();item.pop('kind');item.pop('busy');item['title']='Unavailable';item.update(change)
    r=c.put('/v1/harness/availability',json={'expected_revision':0,'items':[item]},headers=harness(cfg))
    assert r.status_code==422 and 'run shell' not in r.text


def test_signed_harness_release_attests_same_projection(tmp_path):
    from datetime import timedelta
    import uuid
    from fastapi.testclient import TestClient
    from airlock_contracts import keys, seal, unseal, ReleaseSnapshot, utcnow
    from airlock_connector.cli import provision
    from airlock_connector.service import create_connector
    config=provision(tmp_path/'signed','http://127.0.0.1:8742')
    c=TestClient(create_connector(config,tmp_path/'signed/connector.sqlite3'))
    private, public=keys()
    assert c.post('/v1/pair',json={'code':config['pairing_code'],'public_key':public}).status_code==200
    stamp=utcnow()
    doc=ReleaseSnapshot(pairing_id=config['pairing_id'], message_id=uuid.uuid4(),revision=1,
        policy_revision=1,issued_at=stamp,expires_at=stamp+timedelta(minutes=15),sources_fresh=True,items=[])
    assert c.post('/v1/releases',json=seal(doc,private),headers={'Authorization':'Bearer '+config['device_token']}).status_code==200
    assert c.get('/v1/harness/release',headers={'Authorization':'Bearer '+config['device_token']}).status_code==401
    r=c.get('/v1/harness/release',headers=harness(config));assert r.status_code==200
    parsed=unseal(r.json()['snapshot'],config['public_key'],ReleaseSnapshot,config['pairing_id'])
    assert parsed==doc


def test_connector_rate_limit_bounds_unauthenticated_requests(tmp_path):
    from fastapi.testclient import TestClient
    from airlock_connector.cli import provision
    from airlock_connector.service import create_connector
    config=provision(tmp_path/'limited','http://127.0.0.1:8742')
    c=TestClient(create_connector(config,tmp_path/'limited/connector.sqlite3'))
    for _ in range(120): assert c.get('/v1/inbox').status_code==401
    assert c.get('/v1/inbox').status_code==429
    assert c.get('/health').status_code==200


def test_harness_client_caps_streamed_response_and_refuses_redirect():
    import httpx
    from airlock_connector.client import ConnectorClient
    client = ConnectorClient('https://connector.example.test', 'synthetic')
    client.client.close()
    class Oversize(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(20):
                yield b'x' * 65536
    client.client = httpx.Client(base_url='https://connector.example.test',
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Oversize())))
    with pytest.raises(ValueError, match='too large'):
        client.signed_release()
    client.close()
    client.client = httpx.Client(base_url='https://connector.example.test', follow_redirects=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={'Location':'https://elsewhere.test'})))
    with pytest.raises(httpx.HTTPStatusError):
        client.signed_release()
    client.close()


def test_public_throttle_does_not_starve_paired_peer(connector):
    c, cfg, *_ = connector
    for _ in range(120):
        c.get('/v1/inbox')
    assert c.get('/v1/inbox').status_code == 429
    assert c.get('/v1/inbox', headers=device(cfg)).status_code == 200
    assert c.get('/v1/harness/projections', headers=harness(cfg)).status_code == 200
