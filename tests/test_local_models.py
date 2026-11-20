import pytest
from airlock_core.llm import LLMClientError
from airlock.config import Settings
from airlock.llm import LocalOllama


def local():
    return LocalOllama(Settings(database_url='postgresql+psycopg://airlock@127.0.0.1/airlock_test', session_secret='x'*32))


def test_cloud_backed_model_is_rejected_even_when_aliased(monkeypatch):
    llm = local()
    def response(path, payload=None):
        if path == '/api/tags':
            return {'models': [{'name': llm.model}, {'name': llm.embedding_model}]}
        return {'remote_host': 'https://example.com', 'remote_model': 'remote'}
    monkeypatch.setattr(llm, '_request', response)
    with pytest.raises(LLMClientError, match='Remote Ollama'):
        llm.check_models()


@pytest.mark.parametrize('vectors', [[], [[float('nan')]], [['not a number']], [[0]*4097]])
def test_invalid_embeddings_are_not_stored(monkeypatch, vectors):
    llm = local()
    monkeypatch.setattr(llm, '_request', lambda *args: {'embeddings': vectors})
    with pytest.raises(LLMClientError):
        llm.embed('Synthetic text.')


def test_model_selector_excludes_embeddings_and_cloud_aliases(monkeypatch):
    llm=local()
    def response(path,payload=None):
        if path=='/api/tags':return {'models':[{'name':n} for n in ['good:latest','embed:latest','alias:latest','foo-cloud']]}
        if payload['model']=='alias:latest':return {'capabilities':['completion'],'remote_host':'https://remote.example'}
        return {'capabilities':['embedding'] if payload['model']=='embed:latest' else ['completion']}
    monkeypatch.setattr(llm,'_request',response)
    assert [m['name'] for m in llm.installed_chat_models()]==['good:latest']


def test_runtime_endpoint_recheck_blocks_mutated_cloud_address_before_network(monkeypatch):
    llm=local();llm.base_url='https://openrouter.ai/api/v1'
    calls=[]
    monkeypatch.setattr('airlock.llm.http.client.HTTPConnection',lambda *a,**k:calls.append(a))
    with pytest.raises(LLMClientError,match='local Ollama endpoint'):llm.embed('Synthetic input')
    assert calls==[]


def test_transport_ignores_proxy_settings_and_never_follows_redirects(monkeypatch):
    llm=local();calls=[]
    monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:9999')
    monkeypatch.setenv('HTTPS_PROXY','http://proxy.invalid:9999')
    class Response:
        status=302
        def read(self,n):return b'{}'
    class Connection:
        def __init__(self,host,port,**kwargs):calls.append((host,port))
        def request(self,*args):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr('airlock.llm.http.client.HTTPConnection',Connection)
    with pytest.raises(LLMClientError):llm.embed('Synthetic input')
    assert calls==[('127.0.0.1',11435)]
