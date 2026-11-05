import base64
import hashlib
import uuid
from pydantic import Field
from sqlalchemy import select
from airlock_core.llm import LLMClientError
from .schemas import StrictModel
from .memory import DOMAIN, ActionError, audited, restore_audit_after_rollback
from .models import LocalState, KnowledgeSource
from .chat import report
from .calendar import Revision
from . import contacts, knowledge
from .document_parser import extract_isolated, MAX_FILE


class ModelChoice(StrictModel):
    model: str = Field(min_length=1,max_length=120)


class Upload(StrictModel):
    filename: str = Field(min_length=1,max_length=240)
    content_base64: str = Field(min_length=1,max_length=2_800_000)


def attach_knowledge_routes(app,sessions,writer,llm):
    def recorded(db,operation,result):
        r=report(db,'Local '+operation+' completed.',operation=operation,changes=[result],source_refs=[])
        db.commit()
        return {'report_id':str(r.id),'result':result}

    @app.get('/api/models')
    def models():
        with sessions() as db:
            try:
                choices=audited(db,'ollama.list_models',{},llm.installed_chat_models)
                db.commit()
            except LLMClientError:
                restore_audit_after_rollback(db)
                db.commit()
                raise
        return {'model':llm.model,'embedding_model':llm.embedding_model,'choices':choices}

    @app.put('/api/models')
    def choose(body:ModelChoice):
        with writer() as db:
            choices=audited(db,'ollama.list_models',{},llm.installed_chat_models)
            if body.model not in {c['name'] for c in choices}:
                raise ActionError('Choose an installed local chat model from the list.')
            audited(db,'model.select',{'model':body.model},lambda:setattr(db.get(LocalState,1),'chat_model',body.model))
            result=recorded(db,'model_selection',{'model':body.model})
            llm.model=body.model
            return result

    @app.get('/api/knowledge')
    def sources():
        with sessions() as db:
            rows=db.scalars(select(KnowledgeSource).where(KnowledgeSource.domain_id==DOMAIN,
                KnowledgeSource.status.not_in(['removed','excluded'])).order_by(KnowledgeSource.created_at.desc()).limit(200))
            return [knowledge.payload(db,row) for row in rows]

    @app.get('/api/knowledge/{ident}')
    def source(ident:uuid.UUID):
        with sessions() as db:
            return knowledge.payload(db,knowledge.find(db,ident),include_content=True)

    @app.post('/api/knowledge/upload')
    def upload(body:Upload):
        try:
            raw=base64.b64decode(body.content_base64,validate=True)
        except ValueError:
            raise ActionError('Invalid document encoding.') from None
        if len(raw)>MAX_FILE:
            raise ActionError('Choose a document smaller than 2 MB.')
        with writer() as db:
            name=body.filename.replace('\\','/').split('/')[-1]
            text=audited(db,'document.extract',{'extension':name.rsplit('.',1)[-1][:12],'bytes':len(raw)},lambda:extract_isolated(name,raw))
            key='upload:'+hashlib.sha256(raw).hexdigest()
            source=knowledge.put_source(db,key=key,kind='document',title=name,content=text,refs=[{'type':'document_upload','filename':name}])
            if source.status!='ready':
                knowledge.index_source(db,llm,source)
            return recorded(db,'document_ingestion',knowledge.payload(db,source))

    @app.post('/api/knowledge/{ident}/retry')
    def retry(ident:uuid.UUID):
        with writer() as db:
            source=knowledge.find(db,ident)
            if source.status=='excluded':
                raise ActionError('Conversation source was excluded after a correction or deletion.')
            knowledge.index_source(db,llm,source)
            return recorded(db,'source_indexing',knowledge.payload(db,source))

    @app.delete('/api/knowledge/{ident}')
    def remove(ident:uuid.UUID):
        with writer() as db:
            source=knowledge.find(db,ident)
            if source.kind in {'contact','interaction'}:
                raise ActionError('Edit or delete this record in Contacts to keep its source consistent.')
            knowledge.remove(db,source)
            return recorded(db,'source_removal',{'id':str(ident)})

    @app.get('/api/contacts')
    def listing(q:str=''):
        if len(q)>1000:raise ActionError('Search text is too long.')
        with sessions() as db:
            return contacts.listing(db,q)

    @app.post('/api/contacts')
    def create(body:contacts.ContactBody):
        with writer() as db:
            return recorded(db,'contact_save',contacts.save(db,llm,body))

    @app.put('/api/contacts/{ident}')
    def update(ident:uuid.UUID,body:contacts.ContactBody):
        with writer() as db:
            return recorded(db,'contact_save',contacts.save(db,llm,body,ident))

    @app.post('/api/contacts/{ident}/delete')
    def delete(ident:uuid.UUID,body:Revision):
        with writer() as db:
            return recorded(db,'contact_delete',contacts.remove(db,ident,body.expected_revision))

    @app.post('/api/contacts/{ident}/interactions')
    def interaction(ident:uuid.UUID,body:contacts.InteractionBody):
        with writer() as db:
            return recorded(db,'contact_interaction',contacts.add_interaction(db,llm,ident,body))

    @app.post('/api/contacts/{ident}/interactions/{interaction_id}/delete')
    def delete_interaction(ident:uuid.UUID,interaction_id:uuid.UUID,body:Revision):
        with writer() as db:
            return recorded(db,'contact_interaction_delete',contacts.remove_interaction(db,ident,interaction_id,body.expected_revision))
