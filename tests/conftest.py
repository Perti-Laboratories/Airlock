import json
import os
import uuid
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from airlock.api import create_app
from airlock.cli import initialize
from airlock.config import Settings
from airlock.db import database
from airlock.models import Base


class FakeLLM:
    model = 'test-local'
    embedding_model = 'test-embedding'
    decision = None
    fail_embed = False
    contexts = None

    def __init__(self):
        self.contexts = []

    def check_models(self):
        return {self.model: 'test-digest'}

    def embed(self, text):
        if self.fail_embed:
            from airlock_core.llm import LLMClientError
            raise LLMClientError('Embedding unavailable.')
        return [1.0, .2, .3]

    def structured_response(self, **kwargs):
        self.contexts.append(json.loads(kwargs['input_text']))
        if kwargs.get('schema_name')=='company_research_plan':
            return getattr(self,'company_plan',{'searches':[]})
        return self.decision or dict(answer='Local response.', action='chat', target_id=None,
                                     title='', content='', memory_type='fact', impact_level='low')


@pytest.fixture(scope='session')
def settings():
    url = os.environ.get('AIRLOCK_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set AIRLOCK_TEST_DATABASE_URL to the dedicated airlock_test database.')
    parsed = make_url(url)
    if parsed.database != 'airlock_test':
        pytest.fail('Tests require exactly the airlock_test database; refusing other names.')
    settings = Settings(database_url=url, session_secret='test-only-' * 8)
    previous = os.environ.get('AIRLOCK_DATABASE_URL')
    os.environ['AIRLOCK_DATABASE_URL'] = url
    try:
        command.upgrade(Config('alembic.ini'), 'head')
    finally:
        if previous is None:
            os.environ.pop('AIRLOCK_DATABASE_URL', None)
        else:
            os.environ['AIRLOCK_DATABASE_URL'] = previous
    return settings


@pytest.fixture
def workspace(settings):
    engine, sessions = database(settings)
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE ' + ', '.join('"'+t.name+'"' for t in Base.metadata.sorted_tables) + ' CASCADE'))
    initialize(settings)
    llm = FakeLLM()
    client = TestClient(create_app(settings, llm=llm, sessions=sessions), base_url=settings.origin)
    client.get('/')
    token = client.get('/api/session').json()['csrf']
    client.headers.update({'Origin': settings.origin, 'X-Airlock-CSRF': token})
    yield client, llm, sessions, settings
    client.close()
    engine.dispose()
