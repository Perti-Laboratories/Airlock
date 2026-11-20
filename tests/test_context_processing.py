import uuid
from datetime import timedelta
from sqlalchemy import select,func
from airlock import knowledge,contacts,todos
from airlock.context_processing import extract_source,process_once,route_attendees
from airlock.memory import DOMAIN,LocalMemoryCurator,ActionError
from airlock.models import KnowledgeSource,MemoryItem,MemoryProposal,MemoryEmbedding,Contact,CalendarSource,CalendarEvent,LocalState,ReleasePolicy,ExchangeState,ExportIdentity,now
import pytest


def source(db,kind='document',text='My preferred project notebook is Juniper.'):
    s=knowledge.put_source(db,key='test:'+str(uuid.uuid4()),kind=kind,title='Synthetic evidence',content=text,refs=[])
    db.flush();return s


def decision(llm):
    llm.decision={'candidates':[{'title':'Project notebook','content':'The preferred project notebook is Juniper.',
        'memory_type':'preference','evidence':'My preferred project notebook is Juniper.'}]}


def test_extraction_requires_evidence_review_and_deduplicates(workspace):
    _,llm,sessions,_=workspace;decision(llm)
    with sessions() as db:
        s=source(db);extract_source(db,llm,s);db.commit()
        p=db.scalar(select(MemoryProposal));assert p and p.status=='pending_user_approval'
        assert db.scalar(select(func.count()).select_from(MemoryItem))==0
        assert s.status=='ready' and s.extraction_status=='completed'
        s.extraction_cursor=0;extract_source(db,llm,s);db.commit()
        assert db.scalar(select(func.count()).select_from(MemoryProposal))==1
        LocalMemoryCurator(db,llm).review(p.id,True);db.commit()
        assert db.scalar(select(func.count()).select_from(MemoryEmbedding))==1
        assert db.scalar(select(MemoryItem)).content==llm.decision['candidates'][0]['content']


def test_fabricated_evidence_and_restricted_sources_cannot_create_memory(workspace):
    _,llm,sessions,_=workspace;decision(llm)
    with sessions() as db:
        a=source(db,text='Only a question about notebooks.');extract_source(db,llm,a)
        b=source(db);b.company_restricted=True;extract_source(db,llm,b)
        c=source(db);c.source_refs=[{'type':'airlock_projection'}];extract_source(db,llm,c)
        db.commit()
        assert db.scalar(select(func.count()).select_from(MemoryProposal))==0
        assert b.extraction_status==c.extraction_status=='excluded'


def test_removed_or_changed_source_cannot_be_approved(workspace):
    _,llm,sessions,_=workspace;decision(llm)
    with sessions() as db:
        s=source(db);extract_source(db,llm,s);db.commit()
        p=db.scalar(select(MemoryProposal))
        s.content_hash='f'*64
        with pytest.raises(ActionError,match='source changed'):LocalMemoryCurator(db,llm).review(p.id,True)
        knowledge.remove(db,s);db.commit()
        assert p.status=='rejected'


def test_pause_retry_and_no_duplicate_candidates_after_model_failure(workspace):
    client,llm,sessions,_=workspace;decision(llm)
    assert client.put('/api/context-processing',json={'enabled':False}).status_code==200
    with sessions() as db:
        s=source(db);db.commit();ident=s.id
        process_once(db,llm);assert not llm.contexts
        db.get(LocalState,1).automatic_context=True;db.commit()
        llm.fail_embed=True;process_once(db,llm)
        s=db.get(KnowledgeSource,ident);assert s.extraction_status=='failed' and s.extraction_retry_at>now()
        llm.fail_embed=False;s.extraction_retry_at=now()-timedelta(seconds=1);db.commit()
        process_once(db,llm)
        assert s.extraction_status=='completed'
        process_once(db,llm)
        assert db.scalar(select(func.count()).select_from(MemoryProposal))==1


def test_calendar_attendees_create_local_contacts_preserve_edits_and_tombstones(workspace):
    _,llm,sessions,_=workspace
    with sessions() as db:
        calendar=CalendarSource(domain_id=DOMAIN,external_calendar_id='synthetic@example.test',name='Synthetic',timezone='UTC')
        db.add(calendar);db.flush()
        event=CalendarEvent(domain_id=DOMAIN,source_id=calendar.id,title='Synthetic meeting',start_at=now(),end_at=now()+timedelta(hours=1),
            external_provider='google_calendar',attendees=[{'name':'Alex','email':'ALEX@example.test'},
            {'email':'self@example.test','is_user':True},{'email':'room@example.test','resource':True},{'email':'bad'}],metadata_={})
        db.add(event);db.flush()
        assert route_attendees(db,llm,event)==1
        c=db.scalar(select(Contact));assert c.email=='alex@example.test'
        c.name='My edited name';c.notes='Private note'
        assert route_attendees(db,llm,event)==0
        assert c.name=='My edited name' and c.notes=='Private note'
        contacts.remove(db,c.id,c.revision)
        assert route_attendees(db,llm,event)==0
        assert db.scalar(select(func.count()).select_from(Contact))==1
        from airlock.exchange import content
        assert not content(db)['items']


def test_task_status_does_not_claim_delivery_for_review_alone(workspace):
    _,llm,sessions,_=workspace
    with sessions() as db:
        t=todos.save(db,todos.TodoBody(title='Private task',description='Private details'))
        assert 'approve a title' in todos.list_todos(db)[0]['sharing_status']
        todos.review(db,uuid.UUID(t['id']),todos.TodoRelease(expected_revision=1,title='Reviewed task'))
        assert todos.list_todos(db)[0]['sharing_status']=='Title approved · connection off'
        db.add(ExchangeState(domain_id=DOMAIN,pairing_id=uuid.uuid4(),endpoint='https://example.test',public_key='a'*44,enabled=True))
        db.flush()
        assert 'sharing paused' in todos.list_todos(db)[0]['sharing_status']
        p=db.get(ReleasePolicy,DOMAIN)
        if p is None:p=ReleasePolicy(domain_id=DOMAIN);db.add(p)
        p.paused=False;p.type_rules={'todo':'title'};db.flush()
        assert 'delivery pending' in todos.list_todos(db)[0]['sharing_status']


def test_assistant_or_connector_informed_messages_are_not_extraction_evidence(workspace):
    _,llm,sessions,_=workspace;decision(llm)
    from airlock.chat import conversation
    from airlock.models import Message
    with sessions() as db:
        conv=conversation(db)
        for sender,metadata in [('assistant',{}),('user',{'connector_context':True}),('user',{'company_restricted':True})]:
            message=Message(conversation_id=conv.id,sender_type=sender,content='Synthetic',metadata_=metadata)
            db.add(message);db.flush()
            s=source(db,kind='message');s.source_refs=[{'type':'message','id':str(message.id)}]
            extract_source(db,llm,s)
            assert s.extraction_status=='excluded'
        assert not llm.contexts
        assert not db.scalar(select(MemoryProposal))


def test_contact_queue_is_bounded_and_revisits_changed_events(workspace):
    _,llm,sessions,_=workspace
    with sessions() as db:
        source_row=CalendarSource(domain_id=DOMAIN,external_calendar_id='large@example.test',name='Large',timezone='UTC')
        db.add(source_row);db.flush()
        event=CalendarEvent(domain_id=DOMAIN,source_id=source_row.id,title='Synthetic large meeting',start_at=now(),end_at=now()+timedelta(hours=1),
            external_provider='google_calendar',attendees=[{'email':f'person{i}@example.test'} for i in range(22)],metadata_={})
        db.add(event);db.flush()
        assert route_attendees(db,llm,event)==20
        assert event.metadata_.get('contacts_processed_revision') is None
        assert route_attendees(db,llm,event)==2
        assert event.metadata_['contacts_processed_revision']==event.revision
        c=db.scalar(select(Contact).where(Contact.email=='person0@example.test'));contacts.remove(db,c.id,c.revision)
        event.revision+=1
        assert route_attendees(db,llm,event)==0
        assert c.status=='deleted'


def test_task_receipt_matches_current_released_fields(workspace):
    _,_,sessions,_=workspace
    from airlock.exchange import export_id
    from airlock_contracts import ReleaseSnapshot,TodoProjection,keys,seal
    with sessions() as db:
        stamp=now();due=stamp+timedelta(days=1)
        t=todos.save(db,todos.TodoBody(title='Source title',description='LOCAL_ONLY',due_at=due))
        todos.review(db,uuid.UUID(t['id']),todos.TodoRelease(expected_revision=1,title='Reviewed',include_due=True))
        db.add(ReleasePolicy(domain_id=DOMAIN,paused=False,type_rules={'todo':'title_due'}))
        private,public=keys();pid=uuid.uuid4()
        packet=ReleaseSnapshot(message_id=uuid.uuid4(),pairing_id=pid,revision=1,issued_at=stamp,expires_at=stamp+timedelta(minutes=10),policy_revision=1,sources_fresh=True,
            items=[TodoProjection(export_id=export_id(db,'todo:'+t['id']),title='Reviewed',status='open',due_at=due)])
        state=ExchangeState(domain_id=DOMAIN,pairing_id=pid,endpoint='https://example.test',public_key=public,enabled=True,revision=1,acknowledged_revision=0,outbox=seal(packet,private))
        db.add(state);db.flush()
        assert 'pending' in todos.list_todos(db)[0]['sharing_status']
        state.acknowledged_revision=1
        assert todos.list_todos(db)[0]['sharing_status']=='Released to connector'
        from airlock.models import Todo
        db.get(Todo,uuid.UUID(t['id'])).due_at=due+timedelta(days=1)
        assert 'pending' in todos.list_todos(db)[0]['sharing_status']


def test_exact_user_input_can_be_processed_without_reusing_connector_context(workspace):
    _,llm,sessions,_=workspace;decision(llm)
    from airlock.chat import conversation
    from airlock.models import Message
    with sessions() as db:
        text='My preferred project notebook is Juniper.'
        msg=Message(conversation_id=conversation(db).id,sender_type='user',content=text,metadata_={'connector_context':True})
        db.add(msg);db.flush()
        s=source(db,kind='message',text=text)
        s.source_refs=[{'type':'message','id':str(msg.id),'user_authored_only':True}]
        extract_source(db,llm,s)
        assert db.scalar(select(MemoryProposal)) is not None
        assert llm.contexts[-1]=={'source_kind':'message','passage':text}
        s2=source(db,kind='message',text=text+' CONNECTOR_PRIVATE_MARKER')
        s2.source_refs=s.source_refs
        extract_source(db,llm,s2)
        assert s2.extraction_status=='excluded'
        msg.metadata_={'connector_context':True,'company_restricted':True}
        s3=source(db,kind='message',text=text);s3.source_refs=s.source_refs
        extract_source(db,llm,s3)
        assert s3.extraction_status=='excluded'
