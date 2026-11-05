"""Serialize release-relevant commits with publication, independently of inference."""
from sqlalchemy import event
from sqlalchemy.orm import Session
from .models import CalendarEvent, CalendarSource, Todo, ReleasePolicy, ReleaseOverride, ExchangeState

PROTECTED = (CalendarEvent, CalendarSource, Todo, ReleasePolicy, ReleaseOverride, ExchangeState)


@event.listens_for(Session, 'before_flush')
def hold_release_boundary(session, flush_context, instances):
    lock = session.info.get('release_lock')
    if lock and not session.info.get('release_lock_held') and any(
        isinstance(row, PROTECTED) for row in session.new | session.dirty | session.deleted
    ):
        lock.acquire()
        session.info['release_lock_held'] = True


@event.listens_for(Session, 'after_transaction_end')
def release_boundary(session, transaction):
    if transaction.parent is None and session.info.pop('release_lock_held', False):
        session.info['release_lock'].release()
