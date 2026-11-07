"""Task categorization only; no remote agent execution authority."""
import hashlib
from sqlalchemy import select
from airlock_contracts.board import BoardItem, status_for
from airlock_connector import board_peer
from .memory import DOMAIN, ActionError, audited
from .models import Todo, ExportIdentity, RecordExchange, ExchangeState, LocalState, now
from . import todos, record_exchange


def version(t):
    return hashlib.sha256(f'{t.revision}:{todos.column(t)}'.encode()).hexdigest()


def sources(db):
    if record_exchange.rules(db).todo == 'private':
        return {}
    result = {}
    for t in db.scalars(select(Todo).where(Todo.domain_id == DOMAIN, Todo.deleted.is_(False))):
        mapping = db.get(ExportIdentity, 'todo:'+str(t.id))
        if mapping and t.release_title and t.release_revision == t.revision:
            result[str(mapping.export_id)] = t
    return result


def queue_mirror(db, ident, body):
    row = db.get(RecordExchange, DOMAIN); state = db.get(ExchangeState, DOMAIN)
    if not row or record_exchange.rules(db).todo == 'private':
        raise ActionError('Enable task sharing and sync before moving a connected task.')
    items, snapshot = record_exchange.visible(db)
    item = next((i for i in items if i.kind == 'todo' and record_exchange.mirror_id(state, i) == str(ident)), None)
    board = board_peer.visible(row.board_state).get(str(item.export_id)) if item else None
    if not board or snapshot.revision != body.expected_revision or board.column != body.expected_column or board.version != body.expected_version:
        raise ActionError('This task changed or board sync is unavailable. Refresh before moving it.')
    try:
        row.board_state = board_peer.queue(row.board_state, state.pairing_id, 'device', board, body.column)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
    return audited(db, 'todo.board.request', {'id': str(ident), 'column': body.column}, lambda: {'status': 'pending'})


def decorate(db, items):
    row = db.get(RecordExchange, DOMAIN)
    boards = board_peer.visible(row.board_state) if row else {}
    state = row.board_state or {} if row else {}
    for item in items:
        ident = item.pop('_export_id')
        board = boards.get(ident)
        item['board_column'] = board.column if board else {'done':'done','archived':'archive'}.get(item['status'], 'backlog')
        item['board_editable'] = bool(board) and record_exchange.rules(db).todo != 'private'
        if board:
            item['status'] = status_for(board.column)
            item['board_version'] = board.version
        moves = [r for r in state.get('requests', []) if r['move']['export_id'] == ident]
        item['board_move_status'] = moves[-1]['status'] if moves else None
        item['board_move_target'] = moves[-1]['move']['column'] if moves else None
    return items


def sync(db, state, credentials, wire):
    row = db.get(RecordExchange, DOMAIN)
    if not row or not row.policy:
        return
    def persist(value):
        row.board_state = dict(value)
        db.get(LocalState, 1).context_reset_at = now()
        db.commit(); db.info.pop('audit_attempts', None)
    def source():
        return state.revision, [BoardItem(export_id=k, column=todos.column(t), version=version(t)) for k,t in sources(db).items()]
    def apply(move):
        t = sources(db).get(str(move.export_id))
        if not t:
            return 'rejected'
        if version(t) != move.expected_version:
            return 'conflict'
        todos.move(db, t.id, todos.MoveBody(column=move.column, expected_column=todos.column(t), expected_revision=t.revision))
        return 'applied'
    board_peer.sync(row.board_state, pairing=state.pairing_id, role='device', public_key=state.public_key,
        private_key=credentials['private_key'], request=lambda method,path,body=None:
            audited(db,'exchange.board',{'method':method,'path':path},lambda:wire.request(method,path,body)),
        persist=persist, source=source, apply=apply)
