"""Automatic company queries must be company-owned text, never private prompt fragments."""
import json
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from airlock import company
from airlock.models import Message, KnowledgeSource, CompanyConnection, ToolCall
from airlock.memory import DOMAIN
from airlock.company_service import CompanyCurator
from test_company_memory import demo, prepare, publish


def ready(demo):
    c,llm,*_=demo
    _,candidate=prepare(demo);publish(demo,candidate)
    llm.decision=None
    llm.company_plan={'searches':[{'topic_index':0,'angle':'dates'},{'topic_index':0,'angle':'people'}]}
    return candidate


def test_auto_research_combines_context_without_sending_private_text(demo):
    c,llm,sessions,service,config,sent,wire=demo
    candidate=ready(demo)
    c.post('/api/todos',json={'title':'Lantern PERSONAL_TODO_SENTINEL','description':'PERSONAL_NOTES_SENTINEL'})
    c.post('/api/todos',json={'title':'Unrelated generic checklist'})
    c.post('/api/memories',json={'title':'Personal preference','content':'PERSONAL_MEMORY_SENTINEL'})
    request_id=str(uuid.uuid4())
    result=c.post('/api/chat',json={'request_id':request_id,
        'message':'When is Lantern launching and who owns it? PERSONAL_MESSAGE_SENTINEL'}).json()
    context=llm.contexts[-1]
    assert result['status']=='completed' and context['company_read_only']
    assert len(context['company_memory']['results'])==1
    assert context['company_memory']['results'][0]['source_label']=='Synthetic-company.txt'
    assert any(candidate['id']==r['id'] for i in c.get('/api/feed').json()['items'] for r in i['metadata'].get('company_refs',[]))
    assert 'PERSONAL_TODO_SENTINEL' in json.dumps(context['local_todos'])
    assert 'Unrelated generic checklist' not in json.dumps(context['local_todos'])
    assert 'PERSONAL_MEMORY_SENTINEL' in json.dumps(context['active_memories'])
    searches=[body for _,path,body in sent if path=='/v1/search']
    assert len(searches)==2
    assert searches[0]['query']=='Lantern launch dates deadlines timeline'
    assert searches[1]['query']=='Lantern launch owners people responsibilities'
    assert 'PERSONAL_' not in json.dumps(sent)
    planner=next(ctx for ctx in llm.contexts if 'company_topics' in ctx)
    assert set(planner)=={'current_message','company_topics'}
    progress=c.get('/api/chat-progress/'+request_id).json()
    assert progress['status']=='completed'
    assert all(s['status']!='running' for s in progress['steps'])
    assert any(s['key']=='company_embed_1' for s in progress['steps'])
    assert any('2 searches' in s.get('detail','') for s in progress['steps'])
    with sessions() as db:
        assistant=db.scalar(select(Message).where(Message.sender_type=='assistant'))
        assert assistant.metadata_['company_restricted']
        assert assistant.metadata_['research_steps']==progress['steps']
        assert not any('PERSONAL_MESSAGE_SENTINEL' in s.content for s in db.scalars(select(KnowledgeSource)))


def test_local_only_and_connection_opt_out_never_call_company(demo):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);before=len(sent)
    c.post('/api/chat',json={'message':'Lantern launch date','local_only':True})
    assert len(sent)==before and not llm.contexts[-1]['company_read_only']
    assert c.put('/api/company',json={'enabled':True,'extraction_enabled':True,'automatic_research':False}).status_code==200
    c.post('/api/chat',json={'message':'Lantern launch date'})
    assert len(sent)==before and not llm.contexts[-1]['company_read_only']
    # Older settings clients must preserve the opt-out rather than resetting it.
    c.put('/api/company',json={'enabled':True,'extraction_enabled':False})
    assert c.get('/api/company').json()['automatic_research'] is False


def test_planner_cannot_emit_arbitrary_private_queries_or_unbounded_work(demo):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo)
    for plan in [
        {'searches':[{'topic_index':0,'angle':'overview','query':'PERSONAL_SECRET'}]},
        {'searches':[{'topic_index':79,'angle':'overview'}]},
        {'searches':[{'topic_index':0,'angle':'overview'}]*4},
    ]:
        llm.company_plan=plan
        count=len([s for s in sent if s[1]=='/v1/search'])
        result=c.post('/api/chat',json={'message':'Please research Lantern. PERSONAL_SECRET'}).json()
        assert result['status']=='completed'
        assert llm.contexts[-1]['company_memory']['status']=='unavailable'
        assert len([s for s in sent if s[1]=='/v1/search'])==count
        assert 'PERSONAL_SECRET' not in json.dumps(sent)


def test_topics_are_tenant_scoped_published_only_and_revocable(demo):
    c,llm,sessions,service,config,sent,wire=demo
    _,candidate=prepare(demo)
    assert wire.request('GET','/v1/search-topics')['titles']==[]
    publish(demo,candidate)
    assert wire.request('GET','/v1/search-topics')['titles']==['Lantern launch']
    other=service.get('/v1/search-topics',headers={'Authorization':'Bearer another-company-token'})
    assert other.json()['titles']==[]
    assert service.get('/v1/search-topics').status_code==401
    with sessions() as db: CompanyCurator.review(db,config['company_id'],uuid.UUID(candidate['id']),'withdrawn')
    assert wire.request('GET','/v1/search-topics')['titles']==[]


def test_partial_research_keeps_successful_evidence_and_visible_failure(demo,monkeypatch):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);original=wire.request
    def partial(method,path,body=None):
        if path=='/v1/search' and 'dates' in body['query']: raise company.ActionError('Unavailable')
        return original(method,path,body)
    monkeypatch.setattr(wire,'request',partial)
    rid=str(uuid.uuid4())
    result=c.post('/api/chat',json={'message':'When and who for Lantern?','request_id':rid}).json()
    assert result['status']=='completed' and 'Some company searches failed' in result['answer']
    ctx=llm.contexts[-1]['company_memory']
    assert ctx['status']=='partial' and len(ctx['results'])==1
    stages=c.get('/api/chat-progress/'+rid).json()['steps']
    assert any(s['status']=='failed' for s in stages)
    assert not any(s['status']=='running' for s in stages)


def test_progress_is_available_while_inference_is_running_and_ids_are_not_replayed(workspace,monkeypatch):
    c,llm,sessions,_=workspace
    entered=threading.Event();release=threading.Event();original=llm.structured_response
    def slow(**kwargs):
        entered.set();assert release.wait(10)
        return original(**kwargs)
    monkeypatch.setattr(llm,'structured_response',slow)
    rid=str(uuid.uuid4());body={'message':'Synthetic progress test','request_id':rid}
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending=executor.submit(c.post,'/api/chat',json=body)
        try:
            assert entered.wait(10)
            progress=c.get('/api/chat-progress/'+rid).json()
            assert progress['status']=='running'
            assert any(s['key']=='answer' and s['status']=='running' for s in progress['steps'])
        finally: release.set()
        assert pending.result().status_code==200
    assert c.get('/api/chat-progress/'+rid).json()['status']=='completed'
    assert c.post('/api/chat',json=body).status_code==409


def test_irrelevant_research_does_not_prevent_an_explicit_local_edit(demo):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);llm.company_plan={'searches':[]}
    llm.decision={'answer':'Saving','action':'todo_create','target_id':None,'title':'','content':'',
        'memory_type':'fact','impact_level':'low','todo':{'title':'Synthetic private checklist'}}
    result=c.post('/api/chat',json={'message':'Create a to-do titled Synthetic private checklist'}).json()
    assert result['changes'] and not llm.contexts[-1]['company_read_only']
    assert not any(path=='/v1/search' for _,path,_ in sent)


def test_research_has_one_shared_evidence_budget(demo,monkeypatch):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);calls=[]
    def many(db,llm,query,**kwargs):
        calls.append(query)
        return {'results':[{'id':f'{len(calls)}-{i}','title':'Synthetic result','excerpt':'x'*2000,
            'source_label':'Synthetic company','source_hash':'a'*64,'score':.9} for i in range(12)],'truncated':False}
    monkeypatch.setattr(company,'search',many)
    c.post('/api/chat',json={'message':'Research Lantern dates and owners'})
    evidence=llm.contexts[-1]['company_memory']
    assert len(calls)==2 and len(evidence['results'])==7 and evidence['truncated']
    assert sum(len(r['excerpt']) for r in evidence['results'])==14000


def test_failed_synthesis_retains_company_protection_and_failed_trace(demo,monkeypatch):
    from airlock_core.llm import LLMClientError
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);original=llm.structured_response
    def fail_answer(**kwargs):
        if kwargs['schema_name']=='airlock_chat': raise LLMClientError('Synthetic model failure')
        return original(**kwargs)
    monkeypatch.setattr(llm,'structured_response',fail_answer)
    rid=str(uuid.uuid4())
    assert c.post('/api/chat',json={'message':'Lantern launch date','request_id':rid}).status_code==503
    status=c.get('/api/chat-progress/'+rid).json()
    assert status['status']=='failed' and not any(s['status']=='running' for s in status['steps'])
    with sessions() as db:
        messages=list(db.scalars(select(Message)))
        assert len(messages)==2 and all(m.metadata_['company_restricted'] for m in messages)
        audits=list(db.scalars(select(ToolCall)))
        assert any(t.tool_name=='company.search_topics' and t.status=='completed' for t in audits)
        assert any(t.tool_name=='ollama.chat' and t.status=='failed' for t in audits)


def test_company_synthesis_uses_answer_only_schema(demo,monkeypatch):
    c,llm,sessions,service,config,sent,wire=demo
    ready(demo);original=llm.structured_response
    def answer(**kwargs):
        if kwargs['schema_name']=='airlock_chat':
            assert set(kwargs['schema']['properties'])=={'answer'}
            context=json.loads(kwargs['input_text'])
            assert 'OUTSIDE calendar coverage' in context['local_context_summary']['calendar_window']
            return {'answer':'Synthetic grounded company response.'}
        return original(**kwargs)
    monkeypatch.setattr(llm,'structured_response',answer)
    result=c.post('/api/chat',json={'message':'When is Lantern launching?'}).json()
    assert result['status']=='completed' and result['changes']==[]
    assert result['answer']=='Synthetic grounded company response.'
