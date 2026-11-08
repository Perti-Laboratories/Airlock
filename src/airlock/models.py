"""connected planner-compatible local records, without workflow/agent runtime foreign keys."""
import uuid
from datetime import UTC, datetime
from typing import Any
from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, Uuid)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .config import DOMAIN_ID


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Domain(TimestampMixin, Base):
    __tablename__ = "domains"
    __table_args__ = (CheckConstraint(f"id = '{DOMAIN_ID}'", name="single_domain"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, default="local")
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), default="Local owner")


class DomainRecord:
    domain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("domains.id"), nullable=False)


class Conversation(DomainRecord, TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(240), default="New conversation")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    sender_type: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(DomainRecord, TimestampMixin, Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(240))
    report_type: Mapped[str] = mapped_column(String(80), default="airlock_action")
    summary: Mapped[str | None] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MemoryProposal(DomainRecord, TimestampMixin, Base):
    __tablename__ = "memory_proposals"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("reports.id"))
    scope: Mapped[str] = mapped_column(String(40))
    memory_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    impact_level: Mapped[str] = mapped_column(String(40), default="low")
    status: Mapped[str] = mapped_column(String(40), default="proposed", index=True)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryItem(DomainRecord, TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (CheckConstraint("scope = 'domain' AND agent_id IS NULL", name="domain_memory_only"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_from_proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("memory_proposals.id"))
    scope: Mapped[str] = mapped_column(String(40), default="domain")
    memory_type: Mapped[str] = mapped_column(String(80), default="fact")
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    impact_level: Mapped[str] = mapped_column(String(40), default="low")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryLink(Base):
    __tablename__ = "memory_links"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_memory_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("memory_items.id", ondelete="CASCADE"))
    target_memory_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("memory_items.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(80))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MemoryEmbedding(TimestampMixin, Base):
    __tablename__ = "memory_embeddings"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    memory_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("memory_items.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(80), default="ollama")
    model: Mapped[str] = mapped_column(String(160))
    dimensions: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector())


class ToolCall(DomainRecord, Base):
    __tablename__ = "tool_calls"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tool_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="started")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocalState(Base):
    __tablename__ = "local_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    context_reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    chat_model: Mapped[str | None] = mapped_column(String(160))


class KnowledgeSource(DomainRecord, TimestampMixin, Base):
    company_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    __tablename__ = 'knowledge_sources'
    __table_args__ = (UniqueConstraint('domain_id', 'source_key'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_key: Mapped[str] = mapped_column(String(320))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default='pending')
    error: Mapped[str | None] = mapped_column(String(240))


class KnowledgeChunk(DomainRecord, Base):
    __tablename__ = 'knowledge_chunks'
    __table_args__ = (UniqueConstraint('source_id', 'ordinal'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('knowledge_sources.id', ondelete='CASCADE'), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(160))
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector())


class Contact(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'contacts'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(260))
    email: Mapped[str] = mapped_column(String(320), default='')
    phone: Mapped[str] = mapped_column(String(80), default='')
    organization: Mapped[str] = mapped_column(String(240), default='')
    summary: Mapped[str] = mapped_column(Text, default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default='active')
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class ContactInteraction(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'contact_interactions'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('contacts.id', ondelete='CASCADE'), index=True)
    interaction_type: Mapped[str] = mapped_column(String(80), default='note')
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class CalendarSource(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'calendar_sources'
    __table_args__ = (UniqueConstraint('domain_id', 'external_calendar_id'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_calendar_id: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(240))
    timezone: Mapped[str] = mapped_column(String(80), default='America/New_York')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_token: Mapped[str | None] = mapped_column(Text)
    window_date: Mapped[str | None] = mapped_column(String(10))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(240))


class RoutedItem(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'routed_items'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_type: Mapped[str] = mapped_column(String(80), default='event')
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(40), default='promoted')
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column('metadata', JSON, default=dict)


class CalendarEvent(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'calendar_events'
    __table_args__ = (UniqueConstraint('source_id', 'external_event_id'),
                     CheckConstraint('end_at > start_at', name='event_time_order'))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default='')
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[str] = mapped_column(String(80), default='America/New_York')
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_rule: Mapped[str | None] = mapped_column(Text)
    item_kind: Mapped[str] = mapped_column(String(40), default='event')
    scheduling_effect: Mapped[str] = mapped_column(String(40), default='hard')
    blocks_time: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[str] = mapped_column(String(320), default='')
    attendees: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default='scheduled')
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('calendar_sources.id'))
    external_provider: Mapped[str | None] = mapped_column(String(80))
    external_calendar_id: Mapped[str | None] = mapped_column(String(320))
    external_event_id: Mapped[str | None] = mapped_column(String(320))
    external_etag: Mapped[str | None] = mapped_column(String(320))
    sync_status: Mapped[str] = mapped_column(String(40), default='local')
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_note: Mapped[str] = mapped_column(Text, default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict] = mapped_column('metadata', JSON, default=dict)


class RoutedObjectChangeLog(DomainRecord, Base):
    __tablename__ = 'routed_object_change_logs'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    object_type: Mapped[str] = mapped_column(String(80), default='event')
    object_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    routed_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('routed_items.id'))
    action: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentRun(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'agent_runs'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default='queued', index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[list[dict]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(320))
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('reports.id'))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)


class AgentSchedule(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'agent_schedules'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    instruction: Mapped[str] = mapped_column(Text)
    interval_minutes: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('agent_runs.id'))


class ReleasePolicy(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'release_policies'
    domain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('domains.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    type_rules: Mapped[dict] = mapped_column(JSON, default=lambda: {
        "calendar": "private", "todo": "private", "contacts": "private",
        "memory": "private", "company_memory": "private",
    })


class ReleaseOverride(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'release_overrides'
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('calendar_events.id'), primary_key=True)
    event_revision: Mapped[int] = mapped_column(Integer)
    policy_revision: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(40))
    display_title: Mapped[str | None] = mapped_column(String(160))


class Todo(DomainRecord, TimestampMixin, Base):
    """connected planner Todo semantics, without workflow execution or global-domain foreign keys."""
    __tablename__ = 'todos'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default='')
    todo_type: Mapped[str] = mapped_column(String(80), default='task')
    owner_type: Mapped[str] = mapped_column(String(80), default='user')
    owner_ref: Mapped[str | None] = mapped_column(String(240))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(40), default='normal')
    status: Mapped[str] = mapped_column(String(40), default='open')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    release_title: Mapped[str | None] = mapped_column(String(160))
    release_due: Mapped[bool] = mapped_column(Boolean, default=False)
    release_revision: Mapped[int | None] = mapped_column(Integer)


class ExchangeState(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'exchange_state'
    domain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('domains.id'), primary_key=True)
    pairing_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    endpoint: Mapped[str] = mapped_column(String(500))
    public_key: Mapped[str] = mapped_column(String(44))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_availability: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    acknowledged_revision: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    outbox: Mapped[dict | None] = mapped_column(JSON)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(240))
    inbound_revision: Mapped[int] = mapped_column(Integer, default=0)
    inbound_hash: Mapped[str | None] = mapped_column(String(64))
    inbound: Mapped[dict | None] = mapped_column(JSON)


class ExportIdentity(DomainRecord, Base):
    __tablename__ = 'export_identities'
    local_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    export_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, default=uuid.uuid4)


class CompanyConnection(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'company_connection'
    automatic_research: Mapped[bool] = mapped_column(Boolean, default=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('domains.id'), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    endpoint: Mapped[str] = mapped_column(String(240))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(240))
    embedding_spec: Mapped[dict] = mapped_column(JSON)


class CompanySource(DomainRecord, Base):
    __tablename__ = 'company_sources'
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('knowledge_sources.id'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default='pending')
    error: Mapped[str | None] = mapped_column(String(240))


class CompanyCandidate(DomainRecord, TimestampMixin, Base):
    __tablename__ = 'company_candidates'
    __table_args__ = (UniqueConstraint('source_id', 'content_hash', 'fingerprint'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('knowledge_sources.id'))
    content_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(JSON)
    embedding_spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default='pending')
    receipt: Mapped[dict | None] = mapped_column(JSON)


class FeedAcknowledgement(DomainRecord, Base):
    __tablename__ = 'feed_acknowledgements'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RecordExchange(Base):
    """Separate cursor for leased recipient-origin projections; never source records."""
    __tablename__ = 'record_exchange'
    domain_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('domains.id'), primary_key=True)
    policy_revision: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict | None] = mapped_column(JSON)
    inbound_revision: Mapped[int] = mapped_column(Integer, default=0)
    inbound_hash: Mapped[str | None] = mapped_column(String(64))
    inbound: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(240))
    board_state: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
