from fastapi.testclient import TestClient
from airlock.api import create_app
from airlock.security import new_session


def test_concurrent_loopback_workspaces_keep_sessions_and_origin_checks(workspace):
    c, llm, sessions, settings = workspace
    other_settings = settings.model_copy(update={'port': 8745, 'session_secret': 'other-secret-' * 8})
    other = TestClient(create_app(other_settings, llm=llm, sessions=sessions), base_url=other_settings.origin)
    # Simulate the shared browser cookie jar: cookies ignore TCP ports.
    other.cookies.update(c.cookies)
    response = other.get('/')
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    c.cookies.update(other.cookies)
    assert c.get('/api/session').status_code == 200
    assert other.get('/api/session').status_code == 200
    token = other.get('/api/session').json()['csrf']
    # Calendar selection is permitted only from its own origin, never the sibling.
    rejected = other.post('/api/calendar-sources', json={'calendar_id': 'test-only'},
                          headers={'Origin': settings.origin, 'X-Airlock-CSRF': token})
    assert rejected.status_code == 403 and 'code' not in rejected.json()
    other.close()


def test_replaced_cookie_has_recoverable_csrf_error_before_mutation(workspace):
    c, _, _, settings = workspace
    name = f'airlock_session_{settings.port}'
    c.cookies.set(name, new_session(settings.session_secret), domain='127.0.0.1', path='/')
    body = {'name': 'Updated test workspace'}
    rejected = c.put('/api/workspace', json=body)
    assert rejected.status_code == 403 and rejected.json()['code'] == 'local_csrf_changed'
    assert c.get('/api/workspace').json()['name'] != body['name']
    c.headers['X-Airlock-CSRF'] = c.get('/api/session').json()['csrf']
    assert c.put('/api/workspace', json=body).status_code == 200
    assert c.get('/api/workspace').json()['name'] == body['name']
    c.cookies.clear()
    assert c.get('/api/session').json()['code'] == 'local_session_expired'
    c.get('/')
    assert c.get('/api/session').status_code == 200
