import json
import pytest
from sqlalchemy import select,func
from airlock import contacts
from airlock.models import Contact,ToolCall
from airlock.memory import ActionError


def test_every_new_exact_identity_enriches_and_preserves_primary_details(workspace):
    c,llm,sessions,_=workspace
    first=c.post('/api/contacts',json={'name':'Alex Chen','email':'alex@example.test','notes':'Prefers morning calls.','organization':'Juniper'}).json()['result']
    response=c.post('/api/contacts',json={'name':'Alexander Chen','email':'ALEX@example.test','notes':'Discussed launch timing.','organization':'Juniper Labs'})
    assert response.status_code==200,response.text
    merged=response.json()['result'];assert merged['id']==first['id']
    assert merged['name']=='Alex Chen' and merged['organization']=='Juniper'
    assert merged['notes']=='Prefers morning calls.\n\nDiscussed launch timing.'
    assert merged['hygiene']['matched_by']=='identity'
    repeated=c.post('/api/contacts',json={'name':'Alexander Chen','email':'alex@example.test','notes':'Discussed launch timing.','organization':'Juniper Labs'}).json()['result']
    assert repeated['revision']==merged['revision']
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Contact))==1
        assert db.scalar(select(Contact)).provenance['aliases']['name']==['Alexander Chen']
        assert db.scalar(select(ToolCall).where(ToolCall.tool_name=='contact.enrich'))


def test_name_normalization_and_phone_identity_match_before_semantics(workspace):
    c,_,sessions,_=workspace
    first=c.post('/api/contacts',json={'name':'José Silva','phone':'+1 (617) 555-1234','notes':'First note'}).json()['result']
    result=c.post('/api/contacts',json={'name':'Dr. Jose Silva','notes':'Second note'}).json()['result']
    assert result['id']==first['id'] and result['hygiene']['matched_by']=='name'
    result=c.post('/api/contacts',json={'name':'Joe S.','phone':'617-555-1234','email':'jose@example.test'}).json()['result']
    assert result['id']==first['id'] and result['email']=='jose@example.test'


def test_semantic_nickname_match_appends_without_creating_duplicate(workspace,monkeypatch):
    c,llm,sessions,_=workspace
    original=c.post('/api/contacts',json={'name':'Robert Jones','organization':'Juniper','notes':'Leads platform engineering.'}).json()['result']
    seen=[]
    def answer(**args):
        assert args['schema_name']=='local_contact_matches'
        packet=json.loads(args['input_text']);seen.append(packet)
        return {'matches':[{'contact_id':r['contact_id'],'same_person':True,'confidence':.86} for r in packet['candidates']]}
    monkeypatch.setattr(llm,'structured_response',answer)
    response=c.post('/api/contacts',json={'name':'Bob Jones','organization':'Juniper','notes':'Platform lead prefers concise updates.'})
    assert response.status_code==200,response.text
    result=response.json()['result'];assert result['id']==original['id']
    assert result['hygiene']['matched_by']=='semantic' and 'concise updates' in result['notes']
    assert len(seen)==1
    assert len(c.get('/api/contacts').json())==1


def test_conflicting_identities_ambiguity_and_model_failure_do_not_merge(workspace,monkeypatch):
    c,llm,sessions,_=workspace
    first=c.post('/api/contacts',json={'name':'Alex Chen','email':'one@example.test'}).json()['result']
    second=c.post('/api/contacts',json={'name':'Alex Chen','email':'two@example.test'}).json()['result']
    assert first['id']!=second['id']
    assert c.post('/api/contacts',json={'name':'Alex Chen','notes':'Uncertain person'}).status_code==409
    def fail(**kw):raise RuntimeError('Synthetic model failure')
    monkeypatch.setattr(llm,'structured_response',fail)
    assert c.post('/api/contacts',json={'name':'Alexander Chen','notes':'Do not misattribute'}).status_code==409
    assert len(c.get('/api/contacts').json())==2
    assert all(not r['notes'] for r in c.get('/api/contacts').json())


def test_deleted_contact_not_resurrected_and_full_notes_are_not_truncated(workspace):
    c,_,sessions,_=workspace
    first=c.post('/api/contacts',json={'name':'Deleted Person','email':'deleted@example.test'}).json()['result']
    assert c.post('/api/contacts/'+first['id']+'/delete',json={'expected_revision':1}).status_code==200
    assert c.post('/api/contacts',json={'name':'Deleted Person','email':'deleted@example.test'}).status_code==409
    full=c.post('/api/contacts',json={'name':'Another Person','email':'full@example.test','notes':'x'*4000}).json()['result']
    assert c.post('/api/contacts',json={'name':'Another Person','email':'full@example.test','phone':'6175551212','notes':'Extra'}).status_code==409
    result=c.get('/api/contacts').json()[0];assert result['phone']=='' and result['notes']=='x'*4000


def test_semantic_ties_and_unknown_ids_require_review(workspace,monkeypatch):
    c,llm,_,_=workspace
    for name,email in [('Robert Jones','one@example.test'),('Bob Jones','two@example.test')]:
        assert c.post('/api/contacts',json={'name':name,'email':email,'organization':'Juniper'}).status_code==200
    def tied(**args):
        candidates=json.loads(args['input_text'])['candidates']
        return {'matches':[{'contact_id':r['contact_id'],'same_person':True,'confidence':.86} for r in candidates]}
    monkeypatch.setattr(llm,'structured_response',tied)
    assert c.post('/api/contacts',json={'name':'Bobby Jones','organization':'Juniper','notes':'Uncertain'}).status_code==409
    monkeypatch.setattr(llm,'structured_response',lambda **kw:{'matches':[{'contact_id':'invented','same_person':True,'confidence':1}]})
    assert c.post('/api/contacts',json={'name':'Bobby Jones','organization':'Juniper'}).status_code==409
    assert len(c.get('/api/contacts').json())==2


def test_calendar_intake_uses_semantic_hygiene_and_retains_invitation_provenance(workspace,monkeypatch):
    import uuid
    from datetime import timedelta
    from airlock.models import CalendarSource,CalendarEvent,now
    from airlock.memory import DOMAIN
    from airlock.context_processing import route_attendees
    c,llm,sessions,_=workspace
    first=c.post('/api/contacts',json={'name':'Robert Jones','notes':'Existing local note.'}).json()['result']
    def match(**args):
        return {'matches':[{'contact_id':first['id'],'same_person':True,'confidence':.9}]}
    monkeypatch.setattr(llm,'structured_response',match)
    with sessions() as db:
        source=CalendarSource(domain_id=DOMAIN,external_calendar_id='test@example.test',name='Synthetic',timezone='UTC')
        db.add(source);db.flush()
        event=CalendarEvent(domain_id=DOMAIN,source_id=source.id,title='Synthetic invitation',start_at=now(),end_at=now()+timedelta(hours=1),external_provider='google_calendar',attendees=[{'name':'Bob Jones','email':'bob@example.test'}],metadata_={})
        db.add(event);db.flush()
        assert route_attendees(db,llm,event)==0
        survivor=db.get(Contact,uuid.UUID(first['id']))
        assert survivor.email=='bob@example.test' and survivor.notes=='Existing local note.'
        assert any(r['type']=='google_calendar_attendee' for r in survivor.source_refs)
        assert db.scalar(select(func.count()).select_from(Contact))==1
        db.commit()
