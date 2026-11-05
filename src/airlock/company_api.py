import uuid
from pydantic import Field
from sqlalchemy import select
from .schemas import StrictModel
from .models import CompanyConnection, CompanySource, CompanyCandidate, KnowledgeSource, LocalState, now
from .memory import DOMAIN, ActionError, audited
from .chat import report
from . import company


class Connect(StrictModel):
    endpoint: str = Field(max_length=240)
    token: str = Field(min_length=32,max_length=200)
    extraction_enabled: bool = False


class Options(StrictModel):
    automatic_research: bool | None = None
    enabled: bool
    extraction_enabled: bool


class SourceChoice(StrictModel): enabled: bool


def attach_company_routes(app,sessions,writer,llm):
    def recorded(db,operation,result):
        from fastapi.encoders import jsonable_encoder
        result=jsonable_encoder(result)
        r=report(db,'Company memory operation completed.',operation=operation,changes=[result],source_refs=[])
        db.commit()
        return {'result':result,'report_id':str(r.id)}

    @app.get('/api/company')
    def status():
        with sessions() as db:
            choices={s.source_id:s for s in db.scalars(select(CompanySource).where(CompanySource.domain_id==DOMAIN))}
            sources=[]
            for source in db.scalars(select(KnowledgeSource).where(KnowledgeSource.domain_id==DOMAIN,
                KnowledgeSource.kind.in_(['document','message']),KnowledgeSource.status=='ready').order_by(KnowledgeSource.created_at.desc()).limit(100)):
                choice=choices.get(source.id)
                sources.append({'id':str(source.id),'title':source.title,'kind':source.kind,'selected':bool(choice and choice.enabled),
                    'status':choice.status if choice else 'not_selected','passages_done':choice.cursor if choice else 0,
                    'error':choice.error if choice else None,'company_restricted':source.company_restricted})
            candidates=[company.candidate_payload(db,row) for row in db.scalars(select(CompanyCandidate).where(
                CompanyCandidate.domain_id==DOMAIN).order_by(CompanyCandidate.created_at.desc()).limit(100))]
            return {**company.status(db),'sources':sources,'candidates':candidates}

    @app.post('/api/company/connect')
    def connect(body:Connect):
        with writer() as db: return recorded(db,'company_connect',company.connect(db,body.endpoint,body.token,body.extraction_enabled))

    @app.post('/api/company/demo')
    def demo(body: SourceChoice):
        import json
        from pathlib import Path
        try:
            invitation=json.loads(Path('data/company-demo/invitation.json').read_text())
        except (OSError,ValueError):
            raise ActionError('Start the local demo with .venv/bin/python scripts/company_demo.py start first.') from None
        with writer() as db:
            return recorded(db,'company_connect',company.connect(db,invitation['endpoint'],invitation['token'],body.enabled))

    @app.put('/api/company')
    def options(body:Options):
        with writer() as db:
            c=db.get(CompanyConnection,DOMAIN)
            if not c: raise ActionError('Connect a company service first.')
            def apply():
                if body.automatic_research is not None: c.automatic_research=body.automatic_research
                c.enabled=body.enabled;c.extraction_enabled=body.extraction_enabled;c.next_run_at=None
                db.get(LocalState,1).context_reset_at=now()
            audited(db,'company.options',body.model_dump(),apply)
            return recorded(db,'company_options',company.status(db))

    @app.put('/api/company/sources/{ident}')
    def source(ident:uuid.UUID,body:SourceChoice):
        with writer() as db:
            result=audited(db,'company.select_source',{'source_id':str(ident),'enabled':body.enabled},lambda:company.select_source(db,ident,body.enabled))
            return recorded(db,'company_source',result)

    @app.post('/api/company/extract')
    def extract():
        with writer() as db:
            return recorded(db,'company_extract',company.extract_once(db,llm,force=True))

    @app.post('/api/company/candidates/{ident}/submit')
    def submit(ident:uuid.UUID):
        with writer() as db: return recorded(db,'company_submit',company.submit(db,ident))

    @app.post('/api/company/candidates/{ident}/reject')
    def reject(ident:uuid.UUID):
        with writer() as db:
            row=db.get(CompanyCandidate,ident)
            if not row or row.domain_id!=DOMAIN or row.status!='pending': raise ActionError('Pending candidate not found.')
            audited(db,'company.reject',{'candidate_id':str(ident)},lambda:setattr(row,'status','rejected'))
            return recorded(db,'company_reject',{'id':str(ident)})
