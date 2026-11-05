import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from airlock.api import create_app
from airlock.config import DOMAIN_ID, Settings
from airlock.models import MemoryEmbedding, MemoryItem, Domain, ToolCall, Report


def memory(content='My test notebook is Juniper.', **extra):
    return dict(title='Test notebook', content=content, memory_type='fact', impact_level='low', **extra)


def decision(action, content='', target=None):
    return dict(answer='Proposed response.', action=action, target_id=target, title='Test notebook',
                content=content, memory_type='fact', impact_level='low')


def test_remember_retrieve_restart_and_provenance(workspace):
    client, llm, sessions, settings = workspace
    llm.decision = decision('remember', 'My test notebook is Juniper.')
    response = client.post('/api/chat', json={'message': 'Remember my test notebook is Juniper.'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['changes'][0]['memory_id']
    memories = client.get('/api/memories').json()
    assert len(memories) == 1 and memories[0]['source_refs'][0]['type'] == 'message'
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 1
        assert db.get(Report, uuid.UUID(result['report_id'])).structured_data['status'] == 'completed'
    llm.decision = None
    restarted = TestClient(create_app(settings, llm=llm, sessions=sessions), base_url=settings.origin)
    restarted.get('/')
    restarted.headers.update({'Origin': settings.origin, 'X-Airlock-CSRF': restarted.get('/api/session').json()['csrf']})
    assert len(restarted.get('/api/memories').json()) == 1
    assert restarted.post('/api/chat', json={'message': 'What is my test notebook called?'}).status_code == 200
    assert llm.contexts[-1]['active_memories'][0]['content'] == 'My test notebook is Juniper.'


def test_correction_and_forget_remove_embeddings_and_old_prompt_history(workspace):
    c, llm, sessions, _ = workspace
    llm.decision = decision('remember', 'My test notebook is Juniper.')
    first = c.post('/api/chat', json={'message': 'Remember my test notebook is Juniper.'}).json()
    old = first['changes'][0]['memory_id']
    llm.decision = decision('correct', 'My test notebook is Cedar.', old)
    correction = c.post('/api/chat', json={'conversation_id': first['conversation_id'], 'message': 'Correct my notebook to Cedar.'})
    assert correction.status_code == 200, correction.text
    new = c.get('/api/memories').json()
    assert len(new) == 1 and 'Cedar' in new[0]['content']
    with sessions() as db:
        assert db.get(MemoryItem, uuid.UUID(old)).valid_until is not None
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 1
    llm.decision = None
    c.post('/api/chat', json={'conversation_id': first['conversation_id'], 'message': 'What is my notebook called?'})
    assert 'Juniper' not in str(llm.contexts[-1])
    assert c.request('DELETE', '/api/memories/'+new[0]['id'], json={}).status_code == 200
    c.post('/api/chat', json={'conversation_id': first['conversation_id'], 'message': 'What is my notebook called?'})
    assert llm.contexts[-1]['active_memories'] == []
    assert 'Cedar' not in str(llm.contexts[-1])
    assert 'Juniper' in str(c.get('/api/conversations/'+first['conversation_id']).json())
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 0


def test_approval_gate_reject_and_idempotence(workspace):
    c, _, _, _ = workspace
    body = memory()
    body['impact_level'] = 'very_high'
    result = c.post('/api/memories', json=body).json()
    assert result['outcome'] == 'pending_user_approval'
    assert c.get('/api/memories').json() == []
    path = '/api/proposals/'+result['proposal_id']+'/approve'
    assert c.post(path, json={}).status_code == 200
    assert c.post(path, json={}).status_code == 409
    assert len(c.get('/api/memories').json()) == 1
    body['content'] = 'A different very high impact fact.'
    pending = c.post('/api/memories', json=body).json()
    assert c.post('/api/proposals/'+pending['proposal_id']+'/reject', json={}).status_code == 200
    assert c.get('/api/proposals').json() == []
    assert len(c.get('/api/memories').json()) == 1


def test_failed_embedding_rolls_back_memory_but_preserves_attempt_audit(workspace):
    c, llm, sessions, _ = workspace
    llm.fail_embed = True
    assert c.post('/api/memories', json=memory()).status_code == 503
    assert c.get('/api/memories').json() == []
    with sessions() as db:
        calls = list(db.scalars(select(ToolCall)))
        assert any(t.tool_name == 'ollama.embed' and t.status == 'failed' for t in calls)
        assert any(t.tool_name == 'memory.curate' and t.status == 'failed' for t in calls)
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 0


def test_invalid_action_cannot_mutate_and_is_reported(workspace):
    c, llm, _, _ = workspace
    llm.decision = decision('forget', target=str(uuid.uuid4()))
    response = c.post('/api/chat', json={'message': 'Forget that old fact.'})
    assert response.status_code == 503
    assert response.json()['changes'] == []
    assert response.json()['report_id']
    llm.decision = {'action': 'execute_shell', 'command': 'anything'}
    assert c.post('/api/chat', json={'message': 'Hello.'}).status_code == 503
    assert c.get('/api/memories').json() == []


def test_browser_and_domain_boundaries(workspace):
    c, llm, sessions, settings = workspace
    unauthed = TestClient(create_app(settings, llm=llm, sessions=sessions), base_url=settings.origin)
    assert unauthed.get('/api/memories').status_code == 401
    assert c.get('/api/memories', headers={'Host': 'evil.example'}).status_code == 403
    assert c.get('/api/memories', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert c.post('/api/memories', json=memory(), headers={'Origin': 'https://evil.example'}).status_code == 403
    assert c.post('/api/memories', json=memory(), headers={'X-Airlock-CSRF': 'wrong'}).status_code == 403
    with sessions() as db:
        db.add(Domain(id=uuid.uuid4(), name='Other organization'))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize('url', ['https://api.example.com', 'http://localhost:11435', 'http://127.0.0.1:11435/?x=1'])
def test_ollama_remote_and_ambiguous_addresses_rejected(url):
    with pytest.raises(ValueError):
        Settings(database_url='postgresql+psycopg://airlock@127.0.0.1/airlock_test', session_secret='a'*32, ollama_url=url)


def test_standing_instruction_cannot_bypass_review_with_low_impact_label(workspace):
    c, _, _, _ = workspace
    body = memory('Use a fictional demo formatting rule.')
    body['memory_type'] = 'standing_instruction'
    result = c.post('/api/memories', json=body)
    assert result.status_code == 200
    assert result.json()['outcome'] == 'pending_user_approval'
    assert c.get('/api/memories').json() == []


def test_pending_correction_preserves_original_until_approval(workspace):
    c, _, sessions, _ = workspace
    original = c.post('/api/memories', json=memory()).json()['memory_id']
    correction = memory('My test notebook is Cedar.')
    correction['impact_level'] = 'very_high'
    pending = c.patch('/api/memories/'+original, json=correction).json()
    assert 'Juniper' in c.get('/api/memories').json()[0]['content']
    approved = c.post('/api/proposals/'+pending['proposal_id']+'/approve', json={})
    assert approved.status_code == 200, approved.text
    active = c.get('/api/memories').json()
    assert len(active) == 1 and 'Cedar' in active[0]['content']
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 1
