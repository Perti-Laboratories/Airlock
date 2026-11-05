"""Local command feed: read-only notifications and durable acknowledgement receipts.

Receipts change presentation/context, never the underlying approval or release state.
Notification identity comes from its persisted source, so polling cannot duplicate it.
"""
import uuid
from datetime import datetime
from sqlalchemy import select, cast, String, literal, or_, and_
from .memory import DOMAIN, ActionError, audited
from .models import (Conversation, Message, MemoryProposal, AgentRun, CompanyCandidate,
                     FeedAcknowledgement, now)

PAGE_SIZE = 60
MODELS = {'message': Message, 'memory': MemoryProposal, 'agent': AgentRun, 'company': CompanyCandidate}


def item_key(kind, ident):
    return literal(kind + ':') + cast(ident, String)


def is_acknowledged(kind, ident):
    return select(FeedAcknowledgement.key).where(
        FeedAcknowledgement.domain_id == DOMAIN,
        FeedAcknowledgement.key == item_key(kind, ident)).exists()


def listing(db, *, acknowledged=False, before=None, before_key=None):
    items = []
    for kind, model in MODELS.items():
        stamp = model.created_at if kind != 'agent' else model.completed_at
        key = item_key(kind, model.id)
        query = select(model)
        if kind == 'message':
            query = query.join(Conversation).where(Conversation.domain_id == DOMAIN)
        else:
            query = query.where(model.domain_id == DOMAIN)
        if kind == 'agent':
            query = query.where(model.status.in_(['completed', 'failed', 'cancelled', 'interrupted']), stamp.is_not(None))
        # Acknowledged notifications remain in history even after a review is resolved.
        if not acknowledged and kind == 'memory':
            query = query.where(model.status == 'pending_user_approval')
        if not acknowledged and kind == 'company':
            query = query.where(model.status == 'pending')
        seen = is_acknowledged(kind, model.id)
        query = query.where(seen if acknowledged else ~seen)
        if before:
            query = query.where(or_(stamp < before, and_(stamp == before, key < before_key)))
        for row in db.scalars(query.order_by(stamp.desc(), key.desc()).limit(PAGE_SIZE + 1)):
            meta = {}
            if kind == 'message':
                content, role, meta = row.content, row.sender_type, row.metadata_
            elif kind == 'agent':
                content = f'Local agent work {row.status}: {row.instruction[:240]}\n\n{row.result or row.error or "Review this run in Agents."}'
                role, meta = 'notification', {'view': 'agents', 'report_id': str(row.report_id) if row.report_id else None}
            elif kind == 'memory':
                content, role = f'Memory needs your approval: {row.title}', 'notification'
                meta = {'view': 'memory'}
            else:
                # Company text stays in its review screen, not in ordinary chat context.
                content, role = 'A company memory suggestion is ready for your review.', 'notification'
                meta = {'view': 'company', 'candidate_id': str(row.id)}
            items.append({'key': f'{kind}:{row.id}', 'id': str(row.id), 'role': role,
                'content': content, 'metadata': meta, 'created_at': getattr(row, stamp.key).isoformat(),
                'acknowledged': acknowledged})
    items.sort(key=lambda i: (datetime.fromisoformat(i['created_at']), i['key']), reverse=True)
    more = len(items) > PAGE_SIZE
    page = items[:PAGE_SIZE]
    cursor = {'before': page[-1]['created_at'], 'before_key': page[-1]['key']} if more else None
    return {'items': list(reversed(page)), 'next': cursor}


def acknowledge(db, key):
    try:
        kind, raw_id = key.split(':', 1)
        ident = uuid.UUID(raw_id)
        model = MODELS[kind]
    except (ValueError, KeyError):
        raise ActionError('Feed item not found.')
    row = db.get(model, ident)
    if row is None:
        raise ActionError('Feed item not found.')
    domain = db.get(Conversation, row.conversation_id).domain_id if kind == 'message' else row.domain_id
    if domain != DOMAIN:
        raise ActionError('Feed item not found in this workspace.')
    if kind == 'agent' and (row.status not in {'completed', 'failed', 'cancelled', 'interrupted'} or not row.completed_at):
        raise ActionError('This agent run has not finished yet.')
    keys = [f'{kind}:{ident}']
    if kind == 'message' and row.sender_type == 'assistant':
        # Acknowledging a response also clears its request. Old rows predate in_reply_to.
        parent = None
        if row.metadata_.get('in_reply_to'):
            parent = db.get(Message, uuid.UUID(row.metadata_['in_reply_to']))
        else:
            parent = db.scalar(select(Message).where(Message.conversation_id == row.conversation_id,
                Message.created_at < row.created_at).order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
        if parent and parent.sender_type == 'user' and parent.conversation_id == row.conversation_id:
            keys.append(f'message:{parent.id}')
    def apply():
        for target in keys:
            if not db.get(FeedAcknowledgement, target):
                db.add(FeedAcknowledgement(key=target, domain_id=DOMAIN, acknowledged_at=now()))
        db.flush()
        return {'acknowledged': keys}
    return audited(db, 'feed.acknowledge', {'key': key}, apply)
