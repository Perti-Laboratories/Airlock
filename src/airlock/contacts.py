"""Single-domain contacts and interactions with provenance."""
import re
from datetime import datetime
from typing import Literal
from pydantic import Field, field_validator
from sqlalchemy import select, or_
from .schemas import StrictModel
from .memory import DOMAIN, ActionError, audited
from .models import Contact, ContactInteraction, RoutedItem, RoutedObjectChangeLog, LocalState, KnowledgeSource, now
from . import knowledge


class ContactFields(StrictModel):
    name: str = Field(min_length=1, max_length=240)
    email: str = Field(default='', max_length=320)
    phone: str = Field(default='', max_length=80)
    organization: str = Field(default='', max_length=240)
    summary: str = Field(default='', max_length=4000)
    notes: str = Field(default='', max_length=4000)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter an email address or leave it empty.')
        return value.casefold()


class ContactBody(ContactFields):
    expected_revision: int | None = Field(default=None, ge=1)


class InteractionFields(StrictModel):
    interaction_type: Literal['note', 'meeting', 'email', 'call', 'message'] = 'note'
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=4000)

    @field_validator('occurred_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Interaction time requires a timezone offset.')
        return value


class InteractionBody(InteractionFields):
    expected_revision: int = Field(ge=1)


def find(db, ident):
    row = db.get(Contact, ident)
    if not row or row.domain_id != DOMAIN or row.status != 'active':
        raise ActionError('Contact not found in this workspace.')
    return row


def interactions(db, ident):
    return list(db.scalars(select(ContactInteraction).where(ContactInteraction.domain_id == DOMAIN,
        ContactInteraction.contact_id == ident, ContactInteraction.deleted.is_(False)).order_by(ContactInteraction.occurred_at.desc()).limit(100)))


def payload(db, row):
    value = {k:getattr(row,k) for k in ('name','email','phone','organization','summary','notes','revision','status','source_refs')}
    value.update(id=str(row.id), last_contact_at=row.last_contact_at.isoformat() if row.last_contact_at else None)
    value['interactions'] = [dict(id=str(i.id), interaction_type=i.interaction_type, occurred_at=i.occurred_at.isoformat(),
        summary=i.summary, source_refs=i.source_refs) for i in interactions(db,row.id)]
    return value


def listing(db, query='', limit=200):
    base = select(Contact).where(Contact.domain_id == DOMAIN, Contact.status == 'active')
    if query:
        terms = re.findall(r'\w{2,}',query)[:12]
        if terms:
            base = base.where(or_(*[or_(Contact.name.ilike('%'+t+'%'),Contact.organization.ilike('%'+t+'%'),Contact.email.ilike('%'+t+'%')) for t in terms]))
    return [payload(db,c) for c in db.scalars(base.order_by(Contact.updated_at.desc()).limit(limit))]


def record(db, c, action, refs):
    routed = RoutedItem(domain_id=DOMAIN, route_type='contact', title=c.name, content=c.summary,
        source_refs=refs, metadata_={'object_id':str(c.id),'revision':c.revision})
    db.add(routed); db.flush()
    db.add(RoutedObjectChangeLog(domain_id=DOMAIN, object_type='contact', object_id=c.id, routed_item_id=routed.id,
        action=action, revision=c.revision, source_refs=refs))
    db.get(LocalState,1).context_reset_at = now()


def index(db,llm,c):
    text = '\n'.join([c.name,c.email,c.phone,c.organization,c.summary,c.notes]).strip()
    source = knowledge.put_source(db,key='contact:'+str(c.id),kind='contact',title=c.name,content=text,
        refs=[{'type':'contact','id':str(c.id),'revision':c.revision}])
    knowledge.index_source(db,llm,source)


def save(db,llm,body,ident=None,refs=None):
    refs = refs or [{'type':'local_contact_editor'}]
    def apply():
        c = find(db,ident) if ident else Contact(domain_id=DOMAIN,provenance={'owner':'airlock','schema_version':1},source_refs=refs)
        if ident and c.revision != body.expected_revision:
            raise ActionError('Contact changed. Refresh before editing.')
        duplicate = db.scalar(select(Contact.id).where(Contact.domain_id == DOMAIN,Contact.status=='active',Contact.email==body.email)) if body.email else None
        if duplicate and duplicate != ident:
            raise ActionError('A contact with that email already exists. Edit that contact instead.')
        if ident:
            c.revision += 1
            c.source_refs = [*c.source_refs,*refs][-100:]
        for name,value in body.model_dump(exclude={'expected_revision'}).items():
            setattr(c,name,value)
        c.normalized_name = ' '.join(c.name.casefold().split())
        db.add(c); db.flush()
        record(db,c,'updated' if ident else 'created',refs)
        index(db,llm,c)
        return payload(db,c)
    return audited(db,'contact.save',{'id':str(ident) if ident else None},apply)


def add_interaction(db,llm,ident,body,refs=None):
    c=find(db,ident)
    if c.revision != body.expected_revision:
        raise ActionError('Contact changed. Refresh before adding an interaction.')
    refs=refs or [{'type':'local_contact_editor'}]
    def apply():
        i=ContactInteraction(domain_id=DOMAIN,contact_id=c.id,**body.model_dump(exclude={'expected_revision'}),
            source_refs=refs,provenance={'owner':'airlock','schema_version':1})
        db.add(i);db.flush()
        c.revision+=1
        c.last_contact_at=max(c.last_contact_at, i.occurred_at) if c.last_contact_at else i.occurred_at
        record(db,c,'interaction_added',refs)
        s=knowledge.put_source(db,key='interaction:'+str(i.id),kind='interaction',title=c.name+' · '+i.interaction_type,
            content=c.name+'\n'+i.occurred_at.isoformat()+'\n'+i.summary,
            refs=[{'type':'contact_interaction','id':str(i.id),'contact_id':str(c.id)}])
        knowledge.index_source(db,llm,s)
        return payload(db,c)
    return audited(db,'contact.interaction',{'contact_id':str(c.id)},apply)


def remove_interaction(db,ident,interaction_id,revision):
    c=find(db,ident)
    i=db.get(ContactInteraction,interaction_id)
    if c.revision!=revision or not i or i.domain_id!=DOMAIN or i.contact_id!=c.id or i.deleted:
        raise ActionError('Interaction changed or is unavailable. Refresh first.')
    def apply():
        i.deleted=True;c.revision+=1
        source=db.scalar(select(KnowledgeSource).where(KnowledgeSource.domain_id==DOMAIN,KnowledgeSource.source_key=='interaction:'+str(i.id)))
        if source:knowledge.remove(db,source)
        db.flush()
        remaining=interactions(db,c.id)
        c.last_contact_at=remaining[0].occurred_at if remaining else None
        record(db,c,'interaction_deleted',i.source_refs)
        return payload(db,c)
    return audited(db,'contact.interaction_delete',{'contact_id':str(c.id),'interaction_id':str(i.id)},apply)


def remove(db,ident,revision):
    c=find(db,ident)
    if c.revision!=revision:
        raise ActionError('Contact changed. Refresh before deleting.')
    def apply():
        c.status='deleted';c.revision+=1
        keys=['contact:'+str(c.id)] + ['interaction:'+str(i) for i in db.scalars(select(ContactInteraction.id).where(ContactInteraction.contact_id==c.id))]
        for source in db.scalars(select(KnowledgeSource).where(KnowledgeSource.domain_id==DOMAIN,KnowledgeSource.source_key.in_(keys))):
            knowledge.remove(db,source)
        record(db,c,'deleted',c.source_refs)
        return {'id':str(c.id),'deleted':True}
    return audited(db,'contact.delete',{'id':str(c.id)},apply)
