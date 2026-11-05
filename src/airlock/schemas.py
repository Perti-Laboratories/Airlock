from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FeedAckBody(StrictModel):
    keys: list[str] = Field(min_length=1, max_length=120)


class ChatBody(StrictModel):
    request_id: UUID | None = None
    local_only: bool = False
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=4)
    company_query: str | None = Field(default=None, min_length=1, max_length=1000)


class MemoryBody(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=4000)
    memory_type: Literal["fact", "preference", "decision", "standing_instruction"] = "fact"
    impact_level: Literal["low", "medium", "high", "very_high"] = "low"


class CalendarAction(StrictModel):
    title: str = Field(min_length=1,max_length=240)
    start: str = Field(max_length=40)
    end: str = Field(max_length=40)
    timezone: str = Field(max_length=80)
    all_day: bool
    blocks_time: bool
    summary: str = Field(default="",max_length=4000)
    location: str = Field(default="",max_length=320)
    recurrence_rule: str | None = None


class TodoAction(StrictModel):
    title: str = Field(min_length=1,max_length=240)
    description: str = Field(default="",max_length=4000)
    due_at: str | None = None
    priority: Literal["low","normal","high","urgent"] = "normal"
    status: Literal["open","done","archived"] = "open"


class ContactAction(StrictModel):
    name: str = Field(min_length=1, max_length=240)
    email: str = Field(default='', max_length=320)
    phone: str = Field(default='', max_length=80)
    organization: str = Field(default='', max_length=240)
    summary: str = Field(default='', max_length=4000)
    notes: str = Field(default='', max_length=4000)


class InteractionAction(StrictModel):
    interaction_type: Literal['note', 'meeting', 'email', 'call', 'message'] = 'note'
    occurred_at: str = Field(max_length=40)
    summary: str = Field(min_length=1, max_length=4000)


class ResearchAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)


class ChatDecision(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    action: Literal["chat", "remember", "correct", "forget", "calendar_create", "calendar_update", "calendar_cancel", "agent_run", "todo_create", "todo_update", "todo_delete", "contact_create", "contact_update", "contact_delete", "contact_interaction"]
    target_id: UUID | None
    title: str = Field(max_length=240)
    content: str = Field(max_length=4000)
    memory_type: Literal["fact", "preference", "decision", "standing_instruction"]
    impact_level: Literal["low", "medium", "high", "very_high"]

    event: CalendarAction | None = None
    todo: TodoAction | None = None
    contact: ContactAction | None = None
    interaction: InteractionAction | None = None
