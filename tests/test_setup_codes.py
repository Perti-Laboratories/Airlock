import json
import time
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from airlock_contracts.setup import prepare, parse_code, proof, decrypt
from airlock_connector.cli import provision
from airlock_connector.service import create_connector, store
from airlock_connector.enrollment import install
from airlock.setup_code import retrieve, validate_payload


@pytest.fixture
def enrollment(tmp_path):
    endpoint='https://connector.example.test'
    config=provision(tmp_path,endpoint)
    invite=json.loads((tmp_path/'invitation.json').read_text())
    google={'installed':{'client_id':'synthetic.apps.googleusercontent.com','client_secret':'synthetic-only'}}
    code,envelope=prepare(endpoint,google,invite)
    path=tmp_path/'connector.sqlite3'
    install(path,envelope,store)
    return TestClient(create_connector(config,path)),code,envelope,path,config


def redeem(client,code):
    _, secret=parse_code(code)
    return client.post('/v1/setup/redeem',json={},headers={'Authorization':'Bearer '+proof(secret)})


def test_single_use_encryption_restart_and_no_shared_peer_access(enrollment):
    client,code,envelope,path,config=enrollment
    assert 'synthetic' not in json.dumps(envelope)
    for token in ('bad',config['harness_token'],config['device_token']):
        assert client.post('/v1/setup/redeem',json={},headers={'Authorization':'Bearer '+token}).status_code==401
    response=redeem(client,code)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    endpoint,secret=parse_code(code)
    payload=decrypt(secret,response.json()['ciphertext'],endpoint)
    validate_payload(payload,endpoint)
    assert payload['invitation']['pairing_id']==config['pairing_id']
    assert redeem(client,code).status_code==401
    install(path,envelope,store)
    assert redeem(client,code).status_code==401
    with store(path) as db:
        assert db.execute('SELECT ciphertext FROM setup_envelope').fetchone()[0] is None
        assert db.execute('SELECT public_key FROM state').fetchone()[0] is None


def test_concurrent_redemption_has_one_winner(enrollment):
    client,code,*_=enrollment
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:redeem(client,code).status_code,range(2)))
    assert sorted(results)==[200,401]


@pytest.mark.parametrize('reason',['expired','revoked','paired'])
def test_unavailable_grants_fail_closed(enrollment,reason):
    client,code,envelope,path,config=enrollment
    with store(path) as db:
        if reason=='expired':db.execute('UPDATE setup_envelope SET expires_at=0')
        if reason=='revoked':db.execute('UPDATE state SET revoked=1')
        if reason=='paired':db.execute("UPDATE state SET public_key='already-bound'")
    assert redeem(client,code).status_code==401


def test_client_tampering_origin_and_transport_limits(enrollment):
    client,code,envelope,_,_=enrollment
    def handler(request):
        assert request.url.path=='/v1/setup/redeem' and not request.url.query
        assert request.headers['authorization'].startswith('Bearer ')
        return httpx.Response(200,json={'ciphertext':envelope['ciphertext']})
    assert retrieve(code,transport=httpx.MockTransport(handler))['version']==1
    endpoint,secret=parse_code(code)
    with pytest.raises(Exception):decrypt(b'x'*32,envelope['ciphertext'],endpoint)
    with pytest.raises(ValueError):decrypt(secret,envelope['ciphertext'],'https://other.example.test')
    for status in (301,302,401,500):
        with pytest.raises(ValueError):retrieve(code,transport=httpx.MockTransport(lambda r:httpx.Response(status,headers={'location':'https://other.example.test'})))
    with pytest.raises(ValueError,match='too large'):
        retrieve(code,transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*40000)))
    for origin in ('http://example.test','https://127.0.0.1','https://localhost','https://x.test/path','https://u:p@x.test','https://x.test:8443'):
        from airlock_contracts.setup import origin as check
        with pytest.raises(ValueError):check(origin)


def test_fresh_pairing_remains_paused_and_disabled(workspace,enrollment,monkeypatch):
    client,_,sessions,settings=workspace
    remote,code,envelope,path,config=enrollment
    endpoint,secret=parse_code(code)
    payload=decrypt(secret,envelope['ciphertext'],endpoint)
    from test_calendar_workspace import Vault
    vault=Vault()
    monkeypatch.setattr('airlock.exchange.ExchangeKeys',lambda:vault)
    def request(self,method,path,body=None):
        result=remote.request(method,path,json=body);result.raise_for_status();return result.json()
    monkeypatch.setattr('airlock.exchange.Transport.request',request)
    result=client.post('/api/exchange/pair',json={'invitation':payload['invitation']})
    assert result.status_code==200
    state=client.get('/api/exchange').json()
    assert state['paired'] and not state['enabled'] and state['release_paused'] and not state['allow_availability']


def test_setup_applies_through_local_session_and_retries_same_identity(workspace,enrollment,monkeypatch):
    client,_,sessions,settings=workspace
    remote,code,envelope,_,_=enrollment
    endpoint,secret=parse_code(code)
    payload=decrypt(secret,envelope['ciphertext'],endpoint)
    from test_calendar_workspace import Vault
    from airlock.google import GoogleCalendar
    from airlock.setup_code import apply
    exchange_vault=Vault();google=GoogleCalendar(settings,vault=Vault())
    monkeypatch.setattr('airlock.exchange.ExchangeKeys',lambda:exchange_vault)
    def request(self,method,path,body=None):
        r=remote.request(method,path,json=body);r.raise_for_status();return r.json()
    monkeypatch.setattr('airlock.exchange.Transport.request',request)
    def local(request):
        r=client.request(request.method,request.url.path,headers=dict(request.headers),content=request.content)
        return httpx.Response(r.status_code,headers=r.headers,content=r.content)
    apply(settings,payload,google=google,transport=httpx.MockTransport(local))
    apply(settings,payload,google=google,transport=httpx.MockTransport(local))
    assert google.status()['configured'] and not google.status()['connected']
    assert client.get('/api/exchange').json()['release_paused']
    google.vault.set('client',{'client_id':'other.apps.googleusercontent.com','client_secret':'other'})
    with pytest.raises(ValueError,match='another Google'):
        apply(settings,payload,google=google,transport=httpx.MockTransport(local))
