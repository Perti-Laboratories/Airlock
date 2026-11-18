from datetime import timedelta
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from airlock.calendar import EventBody, list_events
from airlock.models import CalendarEvent, RoutedItem, now


def context(**changes):
    start=(now()+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0)
    return dict(title='Synthetic focus preference',start=start.isoformat(),
        end=(start+timedelta(hours=2)).isoformat(),timezone='UTC',
        item_kind='context_window',context_type='energy',scheduling_effect='prefer',
        blocks_time=True,**changes)


def test_context_crud_recurrence_provenance_and_release_boundary(workspace):
    c,_,sessions,_=workspace
    body=context(recurrence_rule='FREQ=DAILY;COUNT=2')
    r=c.post('/api/calendar',json=body);assert r.status_code==200,r.text
    key=r.json()['event_id']
    p=c.get('/api/release-policy').json()
    assert c.put('/api/release-policy',json={'expected_revision':p['revision'],'paused':False,'rules':{'local':'busy'},'type_rules':{'calendar':'busy'}}).status_code==200
    assert c.get('/api/release-preview').json()['eligible_count']==0
    with sessions() as db:
        row=db.get(CalendarEvent,uuid.UUID(key))
        assert not row.blocks_time and row.context_type=='energy' and row.scheduling_effect=='prefer'
        assert row.source_refs and row.provenance['owner']=='airlock'
        assert db.scalar(select(RoutedItem)).metadata_['item_kind']=='context_window'
        events=list_events(db,now(),now()+timedelta(days=5))
        assert len(events)==2 and all(e['item_kind']=='context_window' and not e['blocks_time'] for e in events)
        with pytest.raises(IntegrityError):
            row.blocks_time=True;db.flush()
        db.rollback()
    changed={**body,'expected_revision':1,'scheduling_effect':'strongly_avoid'}
    assert c.put('/api/calendar/'+key,json=changed).status_code==200
    with sessions() as db:assert db.get(CalendarEvent,uuid.UUID(key)).scheduling_effect=='strongly_avoid'
    # Same interval/title with different semantics is a separate normal event, not a duplicate.
    normal={**body,'item_kind':'event','context_type':None,'scheduling_effect':None,'blocks_time':True}
    r=c.post('/api/calendar',json=normal);assert r.json()['event_id']!=key
    assert c.get('/api/release-preview').json()['eligible_count']==2


def test_context_rejects_hard_constraint_and_invalid_category():
    with pytest.raises(ValueError):EventBody(**{**context(),'scheduling_effect':'hard'})
    with pytest.raises(ValueError):EventBody(**{**context(),'context_type':'secret-field'})
    with pytest.raises(ValueError):EventBody(**{**context(),'item_kind':'event'})


def test_chat_creates_and_retrieves_soft_context(workspace):
    c,llm,sessions,_=workspace
    body=context();body['all_day']=False
    llm.decision=dict(answer='Adding context.',action='calendar_create',target_id=None,title='',content='',memory_type='fact',impact_level='low',event=body)
    r=c.post('/api/chat',json={'message':'Add this focus preference as context.'});assert r.status_code==200,r.text
    with sessions() as db:
        row=db.scalar(select(CalendarEvent));assert row.item_kind=='context_window' and not row.blocks_time
    llm.decision=None
    assert c.post('/api/chat',json={'message':'What schedule context do I have?'}).status_code==200
    records=[x['calendar_events'] for x in llm.contexts if 'calendar_events' in x]
    assert records[-1][0]['context_type']=='energy'
    assert records[-1][0]['scheduling_effect']=='prefer'
    assert records[-1][0]['blocks_time'] is False
