"""Harness-independent wire contract. Never imports either application's storage/models."""
import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MAX_BYTES = 1_000_000


def utcnow():
    return datetime.now(UTC)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Interval(Strict):
    all_day: bool = False
    start: str = Field(max_length=40)
    end: str = Field(max_length=40)
    timezone: str = Field(max_length=80)

    @model_validator(mode='after')
    def interval(self):
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError):
            raise ValueError("Invalid timezone.") from None
        if self.all_day:
            a, b = date.fromisoformat(self.start), date.fromisoformat(self.end)
            if len(self.start) != 10 or len(self.end) != 10:
                raise ValueError('Use dates for all-day intervals.')
        else:
            a, b = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
            if a.tzinfo is None or b.tzinfo is None:
                raise ValueError('Offsets required.')
        if not timedelta(0) < b-a <= timedelta(days=366):
            raise ValueError('Invalid interval.')
        return self


class CalendarProjection(Interval):
    kind: Literal['calendar'] = 'calendar'
    export_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    busy: Literal[True] = True


class TodoProjection(Strict):
    kind: Literal['todo'] = 'todo'
    export_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    status: Literal['open', 'done', 'archived']
    due_at: datetime | None = None

    @model_validator(mode='after')
    def due(self):
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError('Due time requires an offset.')
        return self


Projection = Annotated[CalendarProjection | TodoProjection, Field(discriminator='kind')]


class Availability(Interval):
    export_id: uuid.UUID
    title: Literal['Unavailable'] = 'Unavailable'


class Envelope(Strict):
    schema_version: Literal[1] = 1
    message_id: uuid.UUID
    pairing_id: uuid.UUID
    revision: int = Field(ge=1, le=9_000_000_000_000_000)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode='after')
    def lifetime(self):
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError('Offsets required.')
        if not timedelta(0) < self.expires_at-self.issued_at <= timedelta(minutes=15):
            raise ValueError('Invalid lease.')
        return self

    def check_live(self):
        if self.issued_at > utcnow()+timedelta(seconds=30) or self.expires_at <= utcnow():
            raise ValueError('Expired or future message.')


class ReleaseSnapshot(Envelope):
    direction: Literal['release'] = 'release'
    policy_revision: int = Field(ge=0)
    sources_fresh: bool
    source_observed_at: datetime | None = None
    items: list[Projection] = Field(max_length=2000)

    @model_validator(mode='after')
    def unique(self):
        if len({i.export_id for i in self.items}) != len(self.items):
            raise ValueError('Duplicate export IDs.')
        if self.source_observed_at is not None:
            if self.source_observed_at.tzinfo is None or self.source_observed_at > self.issued_at:
                raise ValueError('Invalid observation time.')
        return self


class AvailabilitySnapshot(Envelope):
    direction: Literal['availability'] = 'availability'
    items: list[Availability] = Field(max_length=500)

    @model_validator(mode='after')
    def unique(self):
        if len({i.export_id for i in self.items}) != len(self.items):
            raise ValueError('Duplicate export IDs.')
        return self


class Signed(Strict):
    # Signature covers these exact UTF-8 bytes, not a receiver's reserialization.
    document: str = Field(min_length=2, max_length=700_000)
    signature: str = Field(min_length=88, max_length=88)


def keys():
    private = Ed25519PrivateKey.generate()
    return (base64.b64encode(private.private_bytes_raw()).decode(),
            base64.b64encode(private.public_key().public_bytes_raw()).decode())


def seal(model, private):
    document = json.dumps(model.model_dump(mode='json'), ensure_ascii=True, separators=(',', ':'), sort_keys=True)
    signature = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private, validate=True)).sign(document.encode())
    result = Signed(document=document, signature=base64.b64encode(signature).decode())
    if len(result.model_dump_json().encode()) > MAX_BYTES:
        raise ValueError('Package too large.')
    return result.model_dump()


def unseal(value, public, model, pairing_id, *, live=True):
    signed = Signed.model_validate(value)
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)).verify(
        base64.b64decode(signed.signature, validate=True), signed.document.encode())
    def unique_pairs(pairs):
        result = {}
        for key, val in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field.')
            result[key] = val
        return result
    body = model.model_validate(json.loads(signed.document, object_pairs_hook=unique_pairs))
    if str(body.pairing_id) != str(pairing_id):
        raise ValueError('Wrong audience.')
    if live:
        body.check_live()
    return body


class RecordRules(Strict):
    calendar: Literal['private', 'busy', 'original'] = 'private'
    todo: Literal['private', 'title', 'title_due'] = 'private'


class RecordPolicy(Envelope):
    """Node-signed standing permission, separate from the v1 release contract."""
    schema_version: Literal[2] = 2
    direction: Literal['record_policy'] = 'record_policy'
    rules: RecordRules


class RecordSnapshot(Envelope):
    schema_version: Literal[2] = 2
    direction: Literal['records'] = 'records'
    policy_message_id: uuid.UUID
    items: list[Projection] = Field(max_length=2000)

    @model_validator(mode='after')
    def unique(self):
        if len({i.export_id for i in self.items}) != len(self.items):
            raise ValueError('Duplicate export IDs.')
        return self


def filter_records(items, rules):
    """Deterministic field ceiling, applied before transport and on every local read."""
    rules = RecordRules.model_validate(rules)
    result = []
    for item in items:
        if item.kind == 'calendar' and rules.calendar != 'private':
            result.append(item.model_copy(update={'title': 'Busy'}) if rules.calendar == 'busy' else item)
        elif item.kind == 'todo' and rules.todo != 'private':
            result.append(item.model_copy(update={'due_at': None}) if rules.todo == 'title' else item)
    return result
