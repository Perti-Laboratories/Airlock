"""Company prototype acceptance boundaries using synthetic evidence only."""
import base64
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, delete
from airlock import company
from airlock.company_service import CompanyBase, CompanyRecord, CompanyCurator, create_company_app
from airlock.models import CompanyCandidate, KnowledgeSource, Message, Todo
from airlock.memory import DOMAIN
from test_exchange_workspace import Vault


@pytest.fixture
def demo(workspace, monkeypatch):
    c,llm,sessions,settings=workspace
    engine=sessions.kw['bind']
    CompanyBase.metadata.create_all(engine)
    with sessions() as db:
        db.execute(delete(CompanyRecord));db.commit()
    identity=str(uuid.uuid4());other=str(uuid.uuid4());token='test-company-token-'*3
    embedding={'model':llm.embedding_model,'digest':'test-embedding-digest','dimensions':3}
    config={'endpoint':'http://127.0.0.1:8744','company_id':identity,'name':'Synthetic company',
        'embedding_spec':embedding,'tokens':{token:identity,'another-company-token':other}}
    service=TestClient(create_company_app(sessions,config),base_url=config['endpoint'])
    sent=[]
    class Wire:
        def request(self,method,path,body=None):
            sent.append((method,path,body))
            r=service.request(method,path,json=body,headers={'Authorization':'Bearer '+token})
            if r.status_code!=200: raise company.ActionError('Company unavailable.')
            return r.json()
    wire=Wire();vault=Vault()
    monkeypatch.setattr(company,'CompanyKeys',lambda:vault)
    monkeypatch.setattr(company,'CompanyClient',lambda url,key:wire)
    monkeypatch.setattr(llm,'check_models',lambda:{llm.model:'test-chat-digest',llm.embedding_model:'test-embedding-digest'})
    r=c.post('/api/company/connect',json={'endpoint':config['endpoint'],'token':token,'extraction_enabled':True})
    assert r.status_code==200,r.text
    yield c,llm,sessions,service,config,sent,wire
    service.close()


def prepare(demo, text='The synthetic Lantern launch is November 12, 2026. The launch owner is Rowan.'):
    c,llm,sessions,*_=demo
    r=c.post('/api/knowledge/upload',json={'filename':'Synthetic-company.txt','content_base64':base64.b64encode(text.encode()).decode()})
    assert r.status_code==200,r.text
    source=r.json()['result']['id']
    assert c.put('/api/company/sources/'+source,json={'enabled':True}).status_code==200
    llm.decision={'candidates':[{'title':'Lantern launch','content':'The synthetic Lantern launch is November 12, 2026.',
        'evidence':'The synthetic Lantern launch is November 12, 2026.'}]}
    r=c.post('/api/company/extract',json={});assert r.status_code==200,r.text
    assert r.json()['result']['status']=='processed'
    candidate=c.get('/api/company').json()['candidates'][0]
    return source,candidate


def publish(demo, candidate):
    c,llm,sessions,service,config,*_=demo
    r=c.post('/api/company/candidates/'+candidate['id']+'/submit',json={});assert r.status_code==200,r.text
    with sessions() as db: CompanyCurator.review(db,config['company_id'],uuid.UUID(candidate['id']),'published')


def test_suggestions_stay_local_until_review_then_curator_publication(demo):
    c,llm,sessions,service,config,sent,wire=demo
    source,candidate=prepare(demo)
    assert candidate['status']=='pending' and candidate['source_current']
    assert not any(path=='/v1/candidates' for _,path,_ in sent)
    with sessions() as db: assert db.scalar(select(func.count()).select_from(CompanyRecord))==0
    path='/api/company/candidates/'+candidate['id']+'/submit'
    assert c.post(path,json={}).status_code==200
    assert c.post(path,json={}).status_code==200
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(CompanyRecord))==1
        assert company.search(db,llm,'Lantern launch',wire=wire)['results']==[]
    publish(demo,candidate)
    with sessions() as db:
        found=company.search(db,llm,'Lantern launch',wire=wire)
        assert found['results'][0]['id']==candidate['id']
        CompanyCurator.review(db,config['company_id'],uuid.UUID(candidate['id']),'withdrawn')
        assert company.search(db,llm,'Lantern launch',wire=wire)['results']==[]
    assert service.post('/review',json={'id':candidate['id'],'decision':'published'}).status_code==403
    assert service.get('/v1/capabilities').status_code==401


def test_company_scope_cannot_be_forged_and_embedding_mismatch_fails(demo):
    c,llm,sessions,service,config,sent,wire=demo
    _,candidate=prepare(demo);publish(demo,candidate)
    body={'query':'Lantern','embedding':[1,.2,.3],'embedding_spec':config['embedding_spec'],'limit':12}
    headers={'Authorization':'Bearer another-company-token'}
    assert service.post('/v1/search',json=body,headers=headers).json()['results']==[]
    assert service.post('/v1/search',json={**body,'company_id':config['company_id']},headers=headers).status_code==422
    wrong={**body,'embedding_spec':{**config['embedding_spec'],'digest':'wrong'}}
    assert service.post('/v1/search',json=wrong,headers=headers).status_code==409
    assert service.post('/v1/search',json={**body,'embedding':[1]},headers=headers).status_code==422
    assert service.post('/v1/search',json={**body,'embedding':[0,0,0]},headers=headers).status_code==422
    assert service.get('/v1/capabilities',headers={**headers,'Host':'evil.example'}).status_code==403


def test_changed_or_unselected_source_cannot_be_submitted(demo):
    c,llm,sessions,*_=demo
    source,candidate=prepare(demo)
    assert c.put('/api/company/sources/'+source,json={'enabled':False}).status_code==200
    assert c.post('/api/company/candidates/'+candidate['id']+'/submit',json={}).status_code==409
    assert c.put('/api/company/sources/'+source,json={'enabled':True}).status_code==200
    with sessions() as db:
        row=db.get(KnowledgeSource,uuid.UUID(source));row.content_hash='a'*64;db.commit()
    assert c.post('/api/company/candidates/'+candidate['id']+'/submit',json={}).status_code==409


def test_unselected_sources_and_fabricated_evidence_are_not_candidates(demo):
    c,llm,sessions,*_=demo
    source,_=prepare(demo)
    # Explicitly restart the selected source with a changed revision and fabricated model evidence.
    with sessions() as db:
        row=db.get(KnowledgeSource,uuid.UUID(source));row.content_hash='b'*64;db.commit()
    llm.decision={'candidates':[{'title':'Unsupported','content':'Invented','evidence':'This was never in the source.'}]}
    result=c.post('/api/company/extract',json={}).json()['result']
    assert result['status']=='failed'
    with sessions() as db: assert db.scalar(select(func.count()).select_from(CompanyCandidate))==1
    c.put('/api/company',json={'enabled':True,'extraction_enabled':False})
    assert c.post('/api/company/extract',json={}).json()['result']['status']=='off'


def test_company_chat_reads_calendar_but_cannot_mutate_or_reindex_company_history(demo):
    c,llm,sessions,service,config,sent,wire=demo
    source,candidate=prepare(demo);publish(demo,candidate)
    llm.decision={'answer':'I will create it.','action':'todo_create','target_id':None,'title':'','content':'',
        'memory_type':'fact','impact_level':'low','todo':{'title':'SECRET_FROM_COMPANY','description':'PRIVATE_DETAILS'}}
    r=c.post('/api/chat',json={'message':'Create a to-do from the launch facts. PERSONAL_QUERY_SENTINEL',
        'company_query':'Lantern launch date'})
    assert r.status_code==200,r.text
    result=r.json();assert result['changes']==[] and 'read-only' in result['answer']
    context=llm.contexts[-1]
    assert context['company_memory']['results'][0]['source_label']=='Synthetic-company.txt'
    assert 'November 12' in context['company_memory']['results'][0]['excerpt']
    assert any(candidate['id']==r['id'] for i in c.get('/api/feed').json()['items'] for r in i['metadata'].get('company_refs',[]))
    assert 'calendar_events' in context and 'local_todos' in context
    queries=[body for _,path,body in sent if path=='/v1/search']
    assert queries[-1]['query']=='Lantern launch date'
    assert 'PERSONAL_QUERY_SENTINEL' not in json.dumps(sent)
    # Follow-up with company search off remains unable to launder earlier evidence into a to-do.
    r=c.post('/api/chat',json={'conversation_id':result['conversation_id'],'message':'Create that to-do now.'})
    assert r.status_code==200 and 'read-only' in r.json()['answer']
    assert all('PERSONAL_QUERY_SENTINEL' not in h['content'] for h in llm.contexts[-1]['recent_history'])
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Todo))==0
        assert db.scalar(select(func.count()).select_from(KnowledgeSource))==1
        assert all(m.metadata_.get('company_restricted') for m in db.scalars(select(Message)))
    c.put('/api/company',json={'enabled':False,'extraction_enabled':False})
    llm.decision=None
    keys=[i['key'] for i in c.get('/api/feed').json()['items']]
    assert c.post('/api/feed/acknowledge',json={'keys':keys}).status_code==200
    plain=c.post('/api/chat',json={'message':'Hello, a new local request after acknowledgement.'})
    assert plain.status_code==200
    assert llm.contexts[-1]['company_read_only'] is False


def test_external_projection_never_contains_company_evidence_or_todo_details(demo):
    from airlock.exchange import content
    c,llm,sessions,*_=demo
    _,candidate=prepare(demo);publish(demo,candidate)
    todo=c.post('/api/todos',json={'title':'Prepare launch','description':'PRIVATE_COMPANY_TODO_DETAILS','priority':'normal','status':'open'}).json()['result']
    assert c.put('/api/todos/'+todo['id']+'/release',json={'expected_revision':todo['revision'],'title':'Prepare launch','include_due':False}).status_code==200
    policy=c.get('/api/release-policy').json()
    c.put('/api/release-policy',json={'expected_revision':policy['revision'],'paused':False,'rules':{'local':'busy'}})
    with sessions() as db:
        projection=content(db);text=json.dumps(projection)
        assert 'Prepare launch' in text
        assert 'PRIVATE_COMPANY_TODO_DETAILS' not in text
        assert 'November 12' not in text
        assert 'embedding' not in text and 'source_label' not in text
    c.put('/api/company',json={'enabled':False,'extraction_enabled':False})
    assert c.get('/api/release-policy').json()['paused'] is False


def test_company_endpoint_cannot_target_other_local_or_remote_services():
    for url in ['https://company.example','http://localhost:8744','http://127.0.0.1:8741','http://127.0.0.1:8744/path','http://user@127.0.0.1:8744']:
        with pytest.raises(company.ActionError): company.endpoint(url)


def test_company_attachment_is_read_only_and_not_retrieved_after_acknowledgement(demo):
    c,llm,sessions,*_=demo
    source,_=prepare(demo)
    llm.decision=None
    r=c.post('/api/chat',json={'message':'Summarize this document.','attachment_ids':[source]})
    assert r.status_code==200 and llm.contexts[-1]['company_read_only']
    assert llm.contexts[-1]['source_excerpts'][0]['company_restricted']
    keys=[i['key'] for i in c.get('/api/feed').json()['items']]
    assert c.post('/api/feed/acknowledge',json={'keys':keys}).status_code==200
    r=c.post('/api/chat',json={'message':'Hello after acknowledging the company exchange.'})
    assert r.status_code==200 and not llm.contexts[-1]['company_read_only']
    assert not any(e['source_id']==source for e in llm.contexts[-1]['source_excerpts'])


def test_failed_embedding_does_not_leave_partial_suggestions(demo,monkeypatch):
    c,llm,sessions,*_=demo
    source,_=prepare(demo)
    with sessions() as db:
        row=db.get(KnowledgeSource,uuid.UUID(source));row.content_hash='c'*64;db.commit()
    llm.decision={'candidates':[
        {'title':'First suggestion','content':'First','evidence':'The synthetic Lantern launch is November 12, 2026.'},
        {'title':'Second suggestion','content':'Second','evidence':'The launch owner is Rowan.'}]}
    count=0
    def embed(text):
        nonlocal count
        count+=1
        if count==2:
            from airlock_core.llm import LLMClientError
            raise LLMClientError('Unavailable')
        return [1,.2,.3]
    monkeypatch.setattr(llm,'embed',embed)
    assert c.post('/api/company/extract',json={}).json()['result']['status']=='failed'
    with sessions() as db: assert db.scalar(select(func.count()).select_from(CompanyCandidate))==1


def test_company_notification_acknowledgement_never_submits_candidate(demo):
    c,llm,sessions,service,config,sent,wire=demo
    _,candidate=prepare(demo)
    before=len(sent)
    notice=next(i for i in c.get('/api/feed').json()['items'] if i['key']=='company:'+candidate['id'])
    assert 'SECRET' not in notice['content'] and notice['metadata']['view']=='company'
    assert c.post('/api/feed/'+notice['key']+'/acknowledge',json={}).status_code==200
    assert len(sent)==before
    with sessions() as db:
        assert db.get(CompanyCandidate,uuid.UUID(candidate['id'])).status=='pending'
    assert not any(i['key']==notice['key'] for i in c.get('/api/feed').json()['items'])
