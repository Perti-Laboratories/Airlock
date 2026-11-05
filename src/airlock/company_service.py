"""Synthetic company service. Own Postgres, authenticated device API and local Curator console.

No Airlock workspace database or external harness imports. Production SSO/employee ACLs are not implemented.
"""
import hashlib
import hmac
import html
import json
import re
import secrets
import uuid
from datetime import UTC, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text, Uuid, JSON, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.exc import SQLAlchemyError
from .company_contracts import CandidateSubmission, SearchBody


class CompanyBase(DeclarativeBase): pass


class CompanyAudit(CompanyBase):
    __tablename__ = 'company_memory_audit'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CompanyRecord(CompanyBase):
    __tablename__ = 'company_memory_records'
    company_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    source_label: Mapped[str] = mapped_column(String(240))
    source_hash: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int]
    embedding: Mapped[list] = mapped_column(Vector())
    embedding_spec: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CompanyCurator:
    @staticmethod
    def review(db, company_id, ident, decision):
        row = db.get(CompanyRecord, (company_id, ident), with_for_update=True)
        if not row: raise HTTPException(404, 'Candidate not found.')
        if decision not in {'published', 'rejected', 'withdrawn'}: raise HTTPException(422, 'Invalid decision.')
        row.status = decision
        db.add(CompanyAudit(company_id=company_id, operation='curator.'+decision, record_id=ident))
        db.commit()


def create_company_app(sessions, config):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    origin = config['endpoint']; host = origin.removeprefix('http://')
    csrf = secrets.token_urlsafe(32)

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.headers.get('host') != host or request.headers.get('sec-fetch-site') not in {None, 'none', 'same-origin'}:
            return JSONResponse({'detail':'Unexpected origin.'}, status_code=403)
        if request.url.path.startswith('/v1/'):
            token = request.headers.get('authorization', '').removeprefix('Bearer ')
            identity = next((v for k,v in config['tokens'].items() if hmac.compare_digest(k, token)), None)
            if identity is None: return JSONResponse({'detail':'Company authentication required.'}, status_code=401)
            request.state.identity = identity
        if request.method == 'POST':
            if request.url.path == '/review' and (request.headers.get('origin') != origin or not hmac.compare_digest(request.headers.get('x-company-csrf',''), csrf)):
                return JSONResponse({'detail':'Local Curator session required.'}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                return JSONResponse({'detail':'JSON required.'}, status_code=415)
            try: size = int(request.headers.get('content-length','-1'))
            except ValueError: size = -1
            if not 0 <= size <= 150_000: return JSONResponse({'detail':'Invalid body size.'}, status_code=413)
            parts=[]; total=0
            async for part in request.stream():
                total += len(part)
                if total > 150_000: return JSONResponse({'detail':'Body too large.'}, status_code=413)
                parts.append(part)
            request._body=b''.join(parts)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff','Content-Security-Policy':f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{csrf}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc): return JSONResponse({'detail':'Invalid company request.'}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc): return JSONResponse({'detail':'Company storage unavailable.'}, status_code=503)

    @app.get('/health')
    def health(): return {'service':'airlock-company-demo','status':'ok'}

    @app.get('/v1/capabilities')
    def capabilities(request:Request):
        return {'company_id':request.state.identity,'name':config['name'],'embedding_spec':config['embedding_spec'],
            'prototype':True,'max_results':12,'canonical_writes':'curator_only'}

    @app.get('/v1/search-topics')
    def search_topics(request:Request):
        with sessions() as db:
            titles=list(db.scalars(select(CompanyRecord.title).where(
                CompanyRecord.company_id==request.state.identity, CompanyRecord.status=='published')
                .distinct().order_by(CompanyRecord.title).limit(81)))
            db.add(CompanyAudit(company_id=request.state.identity,operation='memory.topics'))
            db.commit()
            return {'company_id':request.state.identity,'titles':titles[:80],'truncated':len(titles)>80}

    def check_spec(body):
        if body.embedding_spec.model_dump() != config['embedding_spec']:
            raise HTTPException(409,'Embedding specification differs. Reindex with the configured company model.')

    @app.post('/v1/candidates')
    def submit(body:CandidateSubmission, request:Request):
        check_spec(body)
        data=body.model_dump(mode='json')
        fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        company=request.state.identity
        with sessions() as db:
            values={**data,'id':body.id,'company_id':company,'fingerprint':fingerprint,'status':'pending'}
            db.execute(insert(CompanyRecord).values(**values).on_conflict_do_nothing(index_elements=['company_id','id']))
            row=db.get(CompanyRecord,(company,body.id))
            if row.fingerprint != fingerprint: raise HTTPException(409,'Candidate ID already has different content.')
            db.add(CompanyAudit(company_id=company,operation='candidate.received',record_id=row.id))
            db.commit()
            return {'id':str(row.id),'status':row.status}

    @app.post('/v1/search')
    def search(body:SearchBody, request:Request):
        check_spec(body)
        with sessions() as db:
            distance=CompanyRecord.embedding.cosine_distance(body.embedding)
            rows=db.execute(select(CompanyRecord,distance).where(CompanyRecord.company_id==request.state.identity,
                CompanyRecord.status=='published').order_by(distance).limit(64)).all()
            words=set(re.findall(r'\w{3,}',body.query.casefold()))
            ranked=[]
            for row,dist in rows:
                cosine=1-float(dist)
                overlap=len(words & set(re.findall(r'\w{3,}',(row.title+' '+row.content).casefold())))
                if cosine >= .3 or overlap >= 2: ranked.append((cosine+.08*min(overlap,5),row))
            ranked.sort(key=lambda pair:pair[0],reverse=True)
            results=[]; used=0
            for score,row in ranked[:body.limit]:
                excerpt=row.content+'\nEvidence: '+row.evidence
                if used+len(excerpt)>14000: break
                used+=len(excerpt)
                results.append({'id':str(row.id),'title':row.title,'excerpt':excerpt,'source_label':row.source_label,
                    'source_hash':row.source_hash,'score':round(score,4)})
            db.add(CompanyAudit(company_id=request.state.identity,operation='memory.search'))
            db.commit()
            return {'company_id':request.state.identity,'results':results,'truncated':len(ranked)>len(results) or len(rows)==64,
                'max_results':12,'retrieved_at':datetime.now(UTC).isoformat()}

    @app.get('/',response_class=HTMLResponse)
    def console():
        # Local-host administrator console only; never exposed as the employee UI in production.
        with sessions() as db:
            rows=db.scalars(select(CompanyRecord).where(CompanyRecord.company_id==config['company_id']).order_by(CompanyRecord.created_at.desc()).limit(100)).all()
            cards=''.join('<article><small>'+html.escape(r.status)+'</small><h2>'+html.escape(r.title)+'</h2><p>'+html.escape(r.content)+'</p><blockquote>'+html.escape(r.evidence)+'</blockquote><small>Source: '+html.escape(r.source_label)+'</small><p>'+''.join(f'<button data-id="{r.id}" data-action="{action}">{label}</button>' for action,label in ([('published','Publish memory'),('rejected','Reject')] if r.status=='pending' else [('withdrawn','Withdraw')] if r.status=='published' else []))+'</p></article>' for r in rows)
        return '''<!doctype html><html><head><meta charset="utf-8"><title>Company memory · Prototype</title><style>body{font:16px system-ui;max-width:850px;margin:40px auto;background:#f5f6f2;color:#182a25;padding:20px}article{background:white;border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}button{padding:10px;margin-right:8px}p,blockquote{white-space:pre-wrap;line-height:1.5}</style></head><body><h1>Company memory</h1><p>Local prototype · Company Curator console. Submitted candidates become searchable only after publication. All published memories are shared within this demo company.</p><button>Refresh</button><p id="status"></p>'''+(cards or '<p>No candidates yet. Submit one from Airlock → Company memory.</p>')+f'''<script nonce="{csrf}">document.querySelector('body > button').onclick=()=>location.reload();document.querySelectorAll('[data-id]').forEach(b=>b.onclick=async()=>{{const r=await fetch('/review',{{method:'POST',headers:{{'Content-Type':'application/json','X-Company-CSRF':'{csrf}'}},body:JSON.stringify({{id:b.dataset.id,decision:b.dataset.action}})}});if(r.ok)location.reload();else document.querySelector('#status').textContent='Review failed.';}});</script></body></html>'''

    @app.post('/review')
    async def review(request:Request):
        body=await request.json()
        if set(body) != {'id','decision'}: raise HTTPException(422,'Invalid review.')
        try: ident=uuid.UUID(body['id'])
        except (ValueError,TypeError): raise HTTPException(422,'Invalid candidate.') from None
        with sessions() as db: CompanyCurator.review(db,config['company_id'],ident,body['decision'])
        return {'status':'reviewed'}

    return app
