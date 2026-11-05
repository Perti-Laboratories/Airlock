"""Single feed, receipts, notification semantics and bounded pagination."""
import uuid
from datetime import timedelta
from sqlalchemy import select, func
from airlock.models import (Conversation, Message, FeedAcknowledgement, MemoryProposal,
    AgentRun, CompanyCandidate, now)
from airlock.memory import DOMAIN
from airlock.config import USER_ID


def test_one_thread_survives_acknowledgement_and_reopen(workspace):
    c,llm,sessions,_ = workspace
    first=c.post('/api/chat',json={'message':'Synthetic feed one'}).json()
    second=c.post('/api/chat',json={'message':'Synthetic feed two'}).json()
    assert first['conversation_id']==second['conversation_id']
    assert len(llm.contexts[-1]['recent_history'])==2
    active=c.get('/api/feed').json()['items']
    assert len(active)==4
    reply=next(i for i in active if i['metadata'].get('report_id')==first['report_id'])
    for _ in range(2):
        assert c.post('/api/feed/'+reply['key']+'/acknowledge',json={}).status_code==200
    assert len(c.get('/api/feed').json()['items'])==2
    assert len(c.get('/api/feed?acknowledged=true').json()['items'])==2
    assert c.get('/api/messages/'+reply['id']).json()['content']==reply['content']
    assert c.get('/api/messages/'+str(uuid.uuid4())).status_code==404
    third=c.post('/api/chat',json={'message':'Synthetic feed three'}).json()
    assert third['conversation_id']==first['conversation_id']
    assert all(h['content']!='Synthetic feed one' for h in llm.contexts[-1]['recent_history'])
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Conversation))==1
        assert db.scalar(select(func.count()).select_from(Message))==6
        assert db.scalar(select(func.count()).select_from(FeedAcknowledgement))==2


def test_notifications_deduplicate_and_acknowledging_does_not_approve(workspace):
    c,llm,sessions,_=workspace
    with sessions() as db:
        proposal=MemoryProposal(domain_id=DOMAIN,scope='domain',memory_type='fact',title='Synthetic high impact',
            content='Requires review',impact_level='very_high',status='pending_user_approval')
        run=AgentRun(domain_id=DOMAIN,instruction='Synthetic read-only work',status='completed',result='Ready.',completed_at=now())
        db.add_all([proposal,run]);db.commit();pid=proposal.id
    first=c.get('/api/feed').json()
    assert len(first['items'])==2
    assert first==c.get('/api/feed').json()
    for item in first['items']:
        assert item['role']=='notification'
        assert c.post('/api/feed/'+item['key']+'/acknowledge',json={}).status_code==200
    assert c.get('/api/feed').json()['items']==[]
    with sessions() as db:
        assert db.get(MemoryProposal,pid).status=='pending_user_approval'
    assert len(c.get('/api/proposals').json())==1
    assert len(c.get('/api/feed?acknowledged=true').json()['items'])==2
    assert c.post('/api/feed/message:'+str(uuid.uuid4())+'/acknowledge',json={}).status_code==409


def test_feed_paginates_equal_timestamps_and_retains_legacy_sources(workspace):
    c,llm,sessions,_=workspace
    stamp=now()-timedelta(days=1)
    with sessions() as db:
        legacy=Conversation(domain_id=DOMAIN,user_id=uuid.UUID(USER_ID),title='Legacy conversation')
        db.add(legacy);db.flush()
        db.add_all([Message(conversation_id=legacy.id,sender_type='user',content=f'Legacy {i}',created_at=stamp) for i in range(67)])
        db.commit();legacy_id=legacy.id
    page=c.get('/api/feed').json()
    assert len(page['items'])==60 and page['next']
    older=c.get('/api/feed',params=page['next']).json()
    assert len(older['items'])==7 and older['next'] is None
    assert len({i['key'] for i in page['items']+older['items']})==67
    assert len(c.get('/api/conversations/'+str(legacy_id)).json()['messages'])==67
    assert c.get('/api/feed?before=2026-10-20').status_code==422


def test_company_exchange_stays_read_only_until_acknowledged(workspace):
    c,llm,sessions,_=workspace
    first=c.post('/api/chat',json={'message':'Synthetic company question','company_query':'Cedar'}).json()
    assert llm.contexts[-1]['company_read_only']
    llm.decision={'answer':'Creating','action':'todo_create','target_id':None,'title':'','content':'',
        'memory_type':'fact','impact_level':'low','todo':{'title':'Synthetic next local request'}}
    blocked=c.post('/api/chat',json={'message':'Create that to-do'}).json()
    assert blocked['changes']==[] and llm.contexts[-1]['company_read_only']
    for item in c.get('/api/feed').json()['items']:
        if item['role']=='assistant':
            assert c.post('/api/feed/'+item['key']+'/acknowledge',json={}).status_code==200
    result=c.post('/api/chat',json={'message':'Create a to-do titled Synthetic next local request'}).json()
    assert result['conversation_id']==first['conversation_id']
    assert result['changes'] and not llm.contexts[-1]['company_read_only']
    assert llm.contexts[-1]['recent_history']==[]
    assert llm.contexts[-1]['company_memory']['results']==[]


def test_bulk_acknowledgement_is_atomic_and_cannot_hide_new_arrivals(workspace):
    c,llm,sessions,_=workspace
    c.post('/api/chat',json={'message':'Synthetic before snapshot'})
    visible=[i['key'] for i in c.get('/api/feed').json()['items']]
    c.post('/api/chat',json={'message':'Synthetic new arrival'})
    invalid=c.post('/api/feed/acknowledge',json={'keys':[visible[0],'message:'+str(uuid.uuid4())]})
    assert invalid.status_code==409
    assert len(c.get('/api/feed').json()['items'])==4
    assert c.post('/api/feed/acknowledge',json={'keys':visible}).status_code==200
    assert len(c.get('/api/feed').json()['items'])==2
    # CSRF and caller origin still apply to receipt writes.
    assert c.post('/api/feed/acknowledge',json={'keys':visible},headers={'Origin':'https://other.example'}).status_code==403
