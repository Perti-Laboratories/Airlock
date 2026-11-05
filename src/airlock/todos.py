"""Local user-owned Todo records; execution authority is deliberately absent."""
import uuid
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from sqlalchemy import select
from .schemas import StrictModel
from .memory import DOMAIN, ActionError, audited
from .models import Todo, RoutedItem, RoutedObjectChangeLog, LocalState, now


class TodoBody(StrictModel):
    title: str = Field(min_length=1,max_length=240)
    description: str = Field(default='',max_length=4000)
    due_at: datetime | None = None
    scheduled_start_at: datetime | None = None
    estimated_minutes: int | None = Field(default=None,ge=1,le=10080)
    priority: Literal['low','normal','high','urgent'] = 'normal'
    status: Literal['open','done','archived'] = 'open'
    expected_revision: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def times(self):
        for value in (self.due_at,self.scheduled_start_at):
            if value is not None and value.tzinfo is None:
                raise ValueError('Times require a timezone offset.')
        return self


class TodoRelease(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None,min_length=1,max_length=160)
    include_due: bool = False


def payload(t):
    result = {name:getattr(t,name) for name in ('id','title','description','due_at','scheduled_start_at',
        'estimated_minutes','priority','status','revision','source_refs','release_title','release_due','release_revision')}
    result['id']=str(t.id)
    for key in ('due_at','scheduled_start_at'):
        result[key]=result[key].isoformat() if result[key] else None
    return result


def find(db, ident):
    t=db.get(Todo,ident)
    if not t or t.domain_id != DOMAIN or t.deleted:
        raise ActionError('To-do not found.')
    return t


def list_todos(db):
    return [payload(t) for t in db.scalars(select(Todo).where(Todo.domain_id==DOMAIN,Todo.deleted.is_(False)).order_by(Todo.created_at))]


def save(db,body,ident=None,refs=None):
    def apply():
        t=find(db,ident) if ident else Todo(domain_id=DOMAIN,source_refs=refs or [{'type':'local_todo_editor'}],provenance={'owner':'airlock','schema_version':1})
        if ident:
            if t.revision != body.expected_revision:
                raise ActionError('To-do changed. Refresh before editing.')
            still_reviewed = t.release_revision == t.revision and t.title == body.title and t.description == body.description
            t.revision+=1
            if still_reviewed:
                t.release_revision = t.revision
            if refs:
                t.source_refs = [*t.source_refs, *refs][-100:]
        for key,value in body.model_dump(exclude={'expected_revision'}).items():
            setattr(t,key,value)
        db.add(t); db.flush()
        item=RoutedItem(domain_id=DOMAIN,route_type='todo',title=t.title,content=t.description,
            source_refs=t.source_refs,metadata_={'object_id':str(t.id),'revision':t.revision})
        db.add(item);db.flush()
        db.add(RoutedObjectChangeLog(domain_id=DOMAIN,object_type='todo',object_id=t.id,routed_item_id=item.id,
            action='updated' if ident else 'created',revision=t.revision,source_refs=t.source_refs))
        db.get(LocalState,1).context_reset_at=now()
        return payload(t)
    return audited(db,'todo.save',{'id':str(ident) if ident else None},apply)


def remove(db,ident,revision):
    t=find(db,ident)
    if t.revision!=revision:
        raise ActionError('To-do changed. Refresh before deleting.')
    def apply():
        t.deleted=True;t.revision+=1
        db.add(RoutedObjectChangeLog(domain_id=DOMAIN,object_type='todo',object_id=t.id,action='deleted',revision=t.revision,source_refs=t.source_refs))
        db.get(LocalState,1).context_reset_at=now()
        return {'id':str(t.id),'deleted':True}
    return audited(db,'todo.delete',{'id':str(ident)},apply)


def review(db,ident,body):
    t=find(db,ident)
    if t.revision!=body.expected_revision:
        raise ActionError('To-do changed. Review again.')
    def apply():
        t.release_title=body.title;t.release_due=body.include_due
        t.release_revision=t.revision if body.title else None
        return {'id':str(t.id),'approved':bool(body.title)}
    return audited(db,'todo.release.review',{'id':str(ident)},apply)
