"""Repeatable real HTTP acceptance test against a personal/synthetic local workspace.

Leaves synthetic examples for inspection, but restores calendar policy and disables exchange.
Never use this test with work records: it temporarily permits busy-only local calendar releases.
"""
import argparse
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
import httpx
from airlock_connector.client import ConnectorClient

p=argparse.ArgumentParser()
p.add_argument('--harness',required=True)
p.add_argument('--synthetic-workspace',action='store_true',required=True)
args=p.parse_args()
credentials=json.loads(Path(args.harness).read_text())
harness=ConnectorClient(credentials['endpoint'],credentials['token'])
root='http://127.0.0.1:8741'
checks=[]

def passed(name):
    checks.append(name);print('PASS:',name,flush=True)

with httpx.Client(base_url=root,timeout=30,trust_env=False) as local:
    local.get('/')
    local.headers.update({'Origin':root,'X-Airlock-CSRF':local.get('/api/session').json()['csrf']})
    def call(path,method='GET',body=None):
        r=local.request(method,path,json=body);r.raise_for_status();return r.json()
    previous=call('/api/release-policy')
    connection=call('/api/exchange')
    if not connection['paired'] or connection['endpoint']!=credentials['endpoint']:
        raise SystemExit('Pair this connector first.')
    stamp=(datetime.now(UTC)+timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    prefix='Synthetic connector '+uuid.uuid4().hex[:6]
    event_body={'title':prefix+' PRIVATE_SENTINEL','summary':'PRIVATE_SENTINEL details','location':'PRIVATE_SENTINEL location',
        'start':stamp.isoformat(),'end':(stamp+timedelta(minutes=30)).isoformat(),'timezone':'UTC'}
    eid=call('/api/calendar','POST',event_body)['event_id']
    todo_body={'title':prefix+' task','description':'PRIVATE_SENTINEL task details','status':'open'}
    task=call('/api/todos','POST',todo_body)['result'];tid=task['id']
    try:
        call('/api/release-policy','PUT',{'expected_revision':previous['revision'],'paused':False,'rules':{'local':'busy'}})
        call('/api/todos/'+tid+'/release','PUT',{'expected_revision':1,'title':prefix+' approved task'})
        call('/api/exchange','PUT',{'enabled':True,'allow_availability':True})
        # Do not force sync: demonstrate the actual background worker through HTTP.
        deadline=time.monotonic()+55
        while time.monotonic()<deadline:
            feed=harness.projections()
            if any(i['kind']=='todo' and i['title']==prefix+' approved task' for i in feed['items']):break
            time.sleep(2)
        else: raise AssertionError('Automatic publication did not arrive within 55 seconds.')
        assert 'PRIVATE_SENTINEL' not in json.dumps(feed)
        event=next(i for i in feed['items'] if i['kind']=='calendar' and datetime.fromisoformat(i['start'])==stamp)
        assert event['title']=='Busy'
        passed('automatic calendar and to-do delivery; private sentinels excluded')
        call('/api/todos/'+tid,'PUT',{**todo_body,'status':'done','expected_revision':1})
        call('/api/exchange/sync','POST',{})
        assert any(i['kind']=='todo' and i['status']=='done' and i['title']==prefix+' approved task' for i in harness.projections()['items'])
        passed('completion sync under standing task approval')
        call('/api/calendar/'+eid,'PUT',{**event_body,'start':(stamp+timedelta(hours=1)).isoformat(),'end':(stamp+timedelta(hours=1,minutes=30)).isoformat(),'expected_revision':1})
        call('/api/exchange/sync','POST',{})
        moved=[i for i in harness.projections()['items'] if i['export_id']==event['export_id']]
        assert len(moved)==1 and datetime.fromisoformat(moved[0]['start'])==stamp+timedelta(hours=1)
        passed('event move preserves one export identity')
        status=harness.availability_status()
        overlay={'export_id':str(uuid.uuid4()),'title':'Unavailable','start':stamp.isoformat(),'end':(stamp+timedelta(hours=1)).isoformat(),'timezone':'UTC'}
        overlay_revision=harness.replace_availability([overlay],status['revision'])['revision']
        call('/api/exchange/sync','POST',{})
        result=local.get('/api/calendar',params={'start':(stamp-timedelta(days=1)).isoformat(),'end':(stamp+timedelta(days=2)).isoformat()});result.raise_for_status()
        assert any(e['source']=='connector' and e['id']==overlay['export_id'] for e in result.json()['events'])
        assert all(i['export_id']!=overlay['export_id'] for i in harness.projections()['items'])
        assert harness.availability_status()['acknowledged_revision']==overlay_revision
        passed('minimal inbound availability applied, acknowledged and excluded from re-export')
        call('/api/calendar/'+eid+'/cancel','POST',{'expected_revision':2})
        call('/api/todos/'+tid+'/delete','POST',{'expected_revision':2})
        call('/api/exchange/sync','POST',{})
        assert all(i['export_id']!=event['export_id'] and i.get('title')!=prefix+' approved task' for i in harness.projections()['items'])
        passed('event cancellation and task deletion withdraw receiver projections')
    finally:
        policy=call('/api/release-policy')
        call('/api/release-policy','PUT',{'expected_revision':policy['revision'],'paused':True,'rules':previous['rules'],'acknowledge_titles':True})
        call('/api/exchange/sync','POST',{})
        assert harness.projections()['items']==[]
        state=harness.availability_status();harness.replace_availability([],state['revision'])
        call('/api/exchange/sync','POST',{})
        call('/api/exchange','PUT',{'enabled':False,'allow_availability':False})
        passed('all projections withdrawn and exchange disabled after test')
Path('data/connector-acceptance.json').write_text(json.dumps({'at':datetime.now(UTC).isoformat(),'checks':checks},indent=2))
harness.close()
