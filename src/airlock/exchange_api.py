import uuid
from pydantic import Field
from .schemas import StrictModel
from .memory import DOMAIN, ActionError, audited
from .models import ExchangeState, LocalState, now
from .chat import report
from . import exchange, todos
from .calendar import Revision


class PairBody(StrictModel):
    invitation: exchange.Invitation


class ExchangeOptions(StrictModel):
    enabled: bool
    allow_availability: bool


def attach_exchange_routes(app,sessions,writer,settings,lock,release_writer=None):
    release_writer = release_writer or writer
    def recorded(db,operation,result):
        r=report(db,'Local '+operation+' completed.',operation=operation,changes=[],source_refs=[])
        db.commit()
        return {'report_id':str(r.id),'result':result}

    @app.get('/api/exchange')
    def status():
        with sessions() as db:
            from .releases import policy_payload
            return {**exchange.status(db), 'release_paused': policy_payload(db)['paused']}

    @app.post('/api/exchange/pair')
    def pair(body: PairBody):
        with release_writer() as db:
            return recorded(db,'exchange_pair',exchange.pair(db,body.invitation,settings))

    @app.put('/api/exchange')
    def options(body: ExchangeOptions):
        with release_writer() as db:
            s=db.get(ExchangeState,DOMAIN)
            if not s:
                raise ActionError('Pair a connector first.')
            def apply():
                s.enabled=body.enabled;s.allow_availability=body.allow_availability
                if not body.allow_availability or not body.enabled:
                    s.inbound=None
                    db.get(LocalState,1).context_reset_at=now()
                s.next_attempt_at=None
            audited(db,'exchange.options',body.model_dump(),apply)
            return recorded(db,'exchange_options',exchange.status(db))

    @app.post('/api/exchange/sync')
    def sync():
        if not lock.acquire(blocking=False):
            raise ActionError('Airlock is busy. Try shortly.')
        try:
            exchange.exchange_once(sessions,force=True)
        finally:
            lock.release()
        with sessions() as db:
            return exchange.status(db)

    @app.get('/api/todos')
    def listing():
        with sessions() as db:
            return todos.list_todos(db)

    @app.post('/api/todos')
    def create(body: todos.TodoBody):
        with writer() as db:
            return recorded(db,'todo_save',todos.save(db,body))

    @app.put('/api/todos/{ident}')
    def update(ident: uuid.UUID,body: todos.TodoBody):
        with writer() as db:
            return recorded(db,'todo_save',todos.save(db,body,ident))

    @app.post('/api/todos/{ident}/delete')
    def delete(ident: uuid.UUID,body: Revision):
        with writer() as db:
            return recorded(db,'todo_delete',todos.remove(db,ident,body.expected_revision))

    @app.put('/api/todos/{ident}/release')
    def review(ident: uuid.UUID,body: todos.TodoRelease):
        with writer() as db:
            return recorded(db,'todo_release',todos.review(db,ident,body))
