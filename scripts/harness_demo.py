"""A reference harness UI using only the connector's public client API.

No Airlock database, model, source credentials or private-memory imports. Loopback test only.
"""
import argparse
import html
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
from airlock_connector.client import ConnectorClient

parser=argparse.ArgumentParser()
parser.add_argument('--harness',required=True)
parser.add_argument('--port',type=int,default=8743)
args=parser.parse_args()
credentials=json.loads(Path(args.harness).read_text())
client=ConnectorClient(credentials['endpoint'],credentials['token'])
origin=f'http://127.0.0.1:{args.port}'
csrf=secrets.token_urlsafe(32)
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)


@app.middleware('http')
async def boundary(request,call_next):
    if request.headers.get('host')!=f'127.0.0.1:{args.port}':
        return JSONResponse({'detail':'Unexpected host.'},status_code=403)
    if request.method=='POST' and (request.headers.get('origin')!=origin or request.headers.get('x-demo-csrf')!=csrf):
        return JSONResponse({'detail':'Local browser session required.'},status_code=403)
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Frame-Options':'DENY','X-Content-Type-Options':'nosniff'})
    return response


@app.get('/',response_class=HTMLResponse)
def index():
    return '''<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Airlock · Reference harness</title>
<style>body{font:16px system-ui;background:#f5f6f2;color:#182a25;max-width:950px;margin:50px auto;padding:20px}h1{font-size:38px}article{background:white;padding:24px;border:1px solid #d8ded7;border-radius:16px;margin:18px 0}button{padding:12px 18px;border-radius:8px;border:1px solid #9cafa6;background:#173d32;color:white;margin:4px;cursor:pointer}small,p{line-height:1.6}td,th{text-align:left;padding:12px;border-bottom:1px solid #eee}table{width:100%}.muted{color:#526b60}#notice{color:#8d3a26}</style></head><body>
<p class="muted">INDEPENDENT REFERENCE HARNESS</p><h1>What crossed the boundary.</h1><p>This test harness talks only to the Airlock Connector. It has no access to your local calendar sources, conversations, private details or release rules.</p>
<article><h2>Released context</h2><p id="status">Loading…</p><table><thead><tr><th>Type</th><th>Allowed title</th><th>Time / status</th></tr></thead><tbody id="items"></tbody></table><p id="empty"></p><button id="refresh">Refresh</button></article>
<article><h2>Send minimal availability back</h2><p>Send a generic “Unavailable” block for tomorrow, 12:00–12:30 in this computer's local timezone. Airlock must independently allow incoming availability. This never writes Google Calendar. The block expires within 15 minutes unless renewed.</p><button id="send">Send test availability</button><button id="clear">Clear test availability</button><p id="inbound"></p></article>
<p id="notice" role="status"></p><p class="muted">A standalone demonstration client. Released titles are display text; no agent execution is available.</p>
<script>const csrf='''+json.dumps(csrf)+''';const $=s=>document.querySelector(s);
async function api(path,method='GET'){const r=await fetch(path,{method,headers:method==='POST'?{'X-Demo-CSRF':csrf}:{}});const d=await r.json();if(!r.ok)throw Error(d.detail||'Connector unavailable');return d;}
async function refresh(){try{const d=await api('/feed');$('#notice').textContent='';$('#status').textContent='Revision '+d.feed.revision+' · '+(d.feed.stale?'stale / not confirmed current':'current')+' · expires '+(d.feed.expires_at?new Date(d.feed.expires_at).toLocaleString():'not yet published');$('#items').replaceChildren();for(const i of d.feed.items){const row=document.createElement('tr');for(const value of [i.kind,i.title,i.kind==='calendar'?i.start+' → '+i.end:i.status+(i.due_at?' · due '+i.due_at:'')]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}$('#items').append(row);}$('#empty').textContent=d.feed.items.length?'':(d.feed.revision?'The connector has received a snapshot, but no active records are available. In Airlock, check Sharing for approved events in the next 30 days and individually reviewed to-dos. Expired snapshots also show no records.':'Waiting for the first snapshot. In Airlock, check Sharing → connection enabled and outbound sharing resumed.');$('#inbound').textContent='Availability revision '+d.inbound.revision+' · acknowledged by Airlock '+d.inbound.acknowledged_revision+'. The test block is for tomorrow at noon. An acknowledgement confirms receipt; it does not renew the 15-minute expiry. Send again to renew.';}catch(e){$('#notice').textContent=e.message+' · Availability is unknown, not free.';$('#items').replaceChildren();}}
$('#refresh').onclick=refresh;for(const name of ['send','clear'])$('#'+name).onclick=async()=>{try{await api('/'+name,'POST');await refresh();}catch(e){$('#notice').textContent=e.message;}};refresh();setInterval(refresh,10000);
</script></body></html>'''


@app.get('/feed')
def feed():
    try:return {'feed':client.projections(),'inbound':client.availability_status()}
    except Exception:raise HTTPException(503,'Connector unavailable or pairing revoked.') from None


@app.post('/send')
def send():
    start=(datetime.now().astimezone()+timedelta(days=1)).replace(hour=12,minute=0,second=0,microsecond=0)
    # An explicit IANA display zone; absolute UTC intervals remain unambiguous.
    try:
        return client.replace_availability([{'export_id':str(uuid.uuid4()),'title':'Unavailable',
            'start':start.astimezone(UTC).isoformat(),'end':(start+timedelta(minutes=30)).astimezone(UTC).isoformat(),'timezone':'UTC'}],
            client.availability_status()['revision'])
    except Exception:raise HTTPException(503,'Could not queue test availability.') from None


@app.post('/clear')
def clear():
    try:return client.replace_availability([],client.availability_status()['revision'])
    except Exception:raise HTTPException(503,'Could not withdraw test availability.') from None


uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,proxy_headers=False)
