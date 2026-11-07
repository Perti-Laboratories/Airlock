"""Optional v3 board sidecar. No titles, notes or execution instructions."""
import uuid
from typing import Literal
from pydantic import Field, model_validator
from . import Envelope, Strict

Column = Literal['backlog', 'working', 'agent_action', 'in_review', 'done', 'archive']
Role = Literal['device', 'harness']
COLUMNS = ('backlog', 'working', 'agent_action', 'in_review', 'done', 'archive')


def status_for(column):
    return {'backlog': 'open', 'working': 'in_progress', 'agent_action': 'in_progress',
            'in_review': 'in_review', 'done': 'done', 'archive': 'archived'}[column]


class BoardItem(Strict):
    export_id: uuid.UUID
    column: Column
    version: str = Field(pattern=r'^[a-f0-9]{64}$')


class BoardSnapshot(Envelope):
    schema_version: Literal[3] = 3
    direction: Literal['board'] = 'board'
    source: Role
    basis_revision: int = Field(ge=0)
    items: list[BoardItem] = Field(max_length=2000)

    @model_validator(mode='after')
    def unique(self):
        if len({i.export_id for i in self.items}) != len(self.items):
            raise ValueError('Duplicate board identities.')
        return self


class BoardMove(Envelope):
    schema_version: Literal[3] = 3
    direction: Literal['board_move'] = 'board_move'
    source: Role
    export_id: uuid.UUID
    column: Column
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    permission_revision: int = Field(ge=1)


class BoardReceipt(Strict):
    operation_id: uuid.UUID
    status: Literal['applied', 'conflict', 'rejected', 'expired']


class BoardInbox(Envelope):
    schema_version: Literal[3] = 3
    direction: Literal['board_inbox'] = 'board_inbox'
    source: Role
    permission_revision: int = Field(ge=0)
    enabled: bool
    feed: BoardSnapshot | None = None
    moves: list[BoardMove] = Field(max_length=100)
    receipts: list[BoardReceipt] = Field(max_length=200)
