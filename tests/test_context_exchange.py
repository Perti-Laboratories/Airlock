"""Synthetic end-to-end context projections across the real connector boundary."""
import uuid
from datetime import timedelta
import pytest
from pydantic import ValidationError
from airlock_contracts import ContextProjection, RecordRules, filter_records
from airlock.models import now
from airlock.exchange import content
from airlock.calendar import list_events
from test_exchange_workspace import exchange, feed
from test_record_exchange import send


def context_item():
    stamp=now()+timedelta(days=1)
    return dict(kind='context',export_id=str(uuid.uuid4()),title='Remote focus',
        start=stamp.isoformat(),end=(stamp+timedelta(hours=1)).isoformat(),timezone='UTC',
        context_type='energy',scheduling_effect='prefer_avoid',busy=False)


def permit(c, level='private', source='original'):
    p=c.get('/api/release-policy').json()
    r=c.put('/api/release-policy',json=dict(expected_revision=p['revision'],paused=False,
        rules={'local':source},type_rules={'context':level},acknowledge_titles=True))
    assert r.status_code==200,r.text


def test_context_is_explicit_allowlist_and_never_hard():
    item=ContextProjection(**context_item())
    assert filter_records([item],RecordRules(calendar='original'))==[]
    assert filter_records([item],RecordRules(context='window'))[0].title=='Context'
    assert 'context' not in RecordRules().model_dump()  # old wire shape when opt-out
    for extra in ({'busy':True},{'scheduling_effect':'hard'},{'summary':'PRIVATE'},{'attendees':[]}):
        with pytest.raises(ValidationError):ContextProjection(**{**context_item(),**extra})


def test_context_both_directions_default_private_no_echo_and_withdrawal(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    incoming=context_item()
    body={k:v for k,v in incoming.items() if k not in {'kind','export_id','busy'}}
    body.update(title='Local focus',item_kind='context_window',blocks_time=False,summary='PRIVATE_NOTES',location='PRIVATE_LOCATION')
    assert c.post('/api/calendar',json=body).status_code==200
    permit(c);tick();assert feed(receiver,config)['items']==[]
    assert send(receiver,config,[incoming]).status_code==422
    permit(c,'title');tick()
    outbound=feed(receiver,config)['items'];assert len(outbound)==1
    assert outbound[0]['kind']=='context' and outbound[0]['busy'] is False
    assert outbound[0]['title']=='Local focus' and 'PRIVATE' not in str(outbound)
    identity=outbound[0]['export_id']
    assert send(receiver,config,[incoming]).status_code==200;tick()
    with sessions() as db:
        records=list_events(db,now(),now()+timedelta(days=3),include_overlays=True)
        remote=next(e for e in records if e.get('origin')=='recipient')
        assert remote['item_kind']=='context_window' and not remote['blocks_time']
        assert remote['scheduling_effect']=='prefer_avoid' and remote['context_type']=='energy'
        assert all(i['title']!='Remote focus' for i in content(db)['items'])
    permit(c,'window');tick()
    out=feed(receiver,config)['items'][0]
    assert out['export_id']==identity and out['title']=='Context' and not out['busy']
    assert send(receiver,config,[incoming]).status_code==422
    incoming['title']='Context';assert send(receiver,config,[incoming]).status_code==200;tick()
    permit(c)
    with sessions() as db:
        assert not any(e.get('origin')=='recipient' for e in list_events(db,now(),now()+timedelta(days=3),include_overlays=True))
    tick();assert feed(receiver,config)['items']==[]


def test_context_source_and_title_acknowledgement_are_required(exchange):
    c,sessions,receiver,config,wire,tick=exchange
    p=c.get('/api/release-policy').json()
    r=c.put('/api/release-policy',json=dict(expected_revision=p['revision'],paused=False,
        rules={'local':'original'},type_rules={'context':'title'}))
    assert r.status_code==409
    incoming=context_item();body={k:v for k,v in incoming.items() if k not in {'kind','export_id','busy'}}
    body.update(item_kind='context_window')
    assert c.post('/api/calendar',json=body).status_code==200
    permit(c,'title','private');tick();assert feed(receiver,config)['items']==[]
    permit(c,'title','busy');tick();assert feed(receiver,config)['items'][0]['title']=='Context'
