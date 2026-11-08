"""Local routed calendar records; source ownership is enforced below the API/model layer."""

import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dateutil.rrule import rrulestr
from pydantic import Field, model_validator
from sqlalchemy import select, or_
from .schemas import StrictModel
from .models import (
    CalendarEvent,
    CalendarSource,
    RoutedItem,
    RoutedObjectChangeLog,
    LocalState,
    now,
)
from .memory import DOMAIN, ActionError, audited


class EventBody(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    start: str = Field(max_length=40)
    end: str = Field(max_length=40)
    timezone: str = Field(default="America/New_York", max_length=80)
    all_day: bool = False
    blocks_time: bool = True
    location: str = Field(default="", max_length=320)
    recurrence_rule: str | None = Field(default=None, max_length=240)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_interval(self):
        start, end = self.times()
        if end <= start or end - start > timedelta(days=366):
            raise ValueError("An event needs an ordered interval of at most one year.")
        if self.recurrence_rule:
            rule = self.recurrence_rule.upper().removeprefix("RRULE:")
            parts = dict(p.split("=", 1) for p in rule.split(";"))
            if len(parts) != len(rule.split(";")) or set(parts) - {
                "FREQ",
                "INTERVAL",
                "BYDAY",
                "BYMONTHDAY",
                "COUNT",
                "UNTIL",
            }:
                raise ValueError("Unsupported recurrence fields.")
            if parts.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
                raise ValueError("Use daily, weekly, monthly or yearly recurrence.")
            if not 1 <= int(parts.get("INTERVAL", "1")) <= 366:
                raise ValueError("Invalid recurrence interval.")
            if "COUNT" in parts and not 1 <= int(parts["COUNT"]) <= 1000:
                raise ValueError("Use at most 1,000 occurrences.")
            parsed = rrulestr(rule, dtstart=start.astimezone(ZoneInfo(self.timezone)))
            if parsed.after(start - timedelta(seconds=1)) is None:
                raise ValueError("Recurrence has no occurrences after the start.")
            self.recurrence_rule = rule
        return self

    def times(self):
        try:
            zone = ZoneInfo(self.timezone)

            def parse(value):
                if self.all_day:
                    return datetime.combine(
                        date.fromisoformat(value), time.min, zone
                    ).astimezone(UTC)
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if result.tzinfo is None:
                    candidates = [result.replace(tzinfo=zone, fold=f) for f in (0, 1)]
                    valid = [
                        v
                        for v in candidates
                        if v.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
                        == result
                    ]
                    if not valid or len({v.utcoffset() for v in valid}) > 1:
                        raise ValueError(
                            "Ambiguous or nonexistent local time; supply an explicit UTC offset."
                        )
                    result = valid[0]
                else:
                    local = result.astimezone(zone)
                    if (
                        local.replace(tzinfo=None) != result.replace(tzinfo=None)
                        or local.utcoffset() != result.utcoffset()
                    ):
                        raise ValueError(
                            "The supplied UTC offset does not match the selected timezone."
                        )
                return result.astimezone(UTC)

            return parse(self.start), parse(self.end)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                "Check the date, IANA timezone and UTC offset; all-day end dates are exclusive."
            ) from exc


class EventNote(StrictModel):
    note: str = Field(max_length=4000)
    expected_revision: int = Field(ge=1)


class Revision(StrictModel):
    expected_revision: int = Field(ge=1)


def event_payload(event, start=None, end=None):
    start, end = start or event.start_at, end or event.end_at
    zone = ZoneInfo(event.timezone)
    return dict(
        id=str(event.id),
        occurrence_id=f"{event.id}:{start.isoformat()}",
        title=event.title,
        summary=event.summary,
        start=start.astimezone(zone).date().isoformat()
        if event.all_day
        else start.astimezone(zone).isoformat(),
        end=end.astimezone(zone).date().isoformat()
        if event.all_day
        else end.astimezone(zone).isoformat(),
        timezone=event.timezone,
        all_day=event.all_day,
        blocks_time=event.blocks_time,
        location=event.location,
        recurrence_rule=event.recurrence_rule,
        status=event.status,
        source="google" if event.source_id else "local",
        source_id=str(event.source_id) if event.source_id else None,
        local_note=event.local_note,
        revision=event.revision,
        source_refs=event.source_refs,
        series_start=event.start_at.astimezone(zone).isoformat(),
        series_end=event.end_at.astimezone(zone).isoformat(),
    )


def find_event(db, event_id):
    row = db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id, CalendarEvent.domain_id == DOMAIN
        )
    )
    if row is None:
        raise ActionError("Calendar event not found in this workspace.")
    return row


def record_change(db, event, action, refs, *, route=True):
    item = None
    if route:
        item = RoutedItem(
            domain_id=DOMAIN,
            route_type="event",
            title=event.title,
            content=event.summary,
            source_refs=refs,
            metadata_={
                "object_id": str(event.id),
                "action": action,
                "revision": event.revision,
            },
        )
        db.add(item)
        db.flush()
    db.add(
        RoutedObjectChangeLog(
            domain_id=DOMAIN,
            object_id=event.id,
            routed_item_id=item.id if item else None,
            action=action,
            revision=event.revision,
            source_refs=refs,
        )
    )


def save_event(db, body, refs, *, event_id=None):
    def apply():
        event = find_event(db, event_id) if event_id else None
        if event:
            if event.source_id:
                raise ActionError(
                    "Google owns this event. Edit it in Google; local notes are separate."
                )
            if body.expected_revision != event.revision:
                raise ActionError("This event changed. Refresh before editing it.")
            if event.status == "cancelled":
                raise ActionError(
                    "This event was cancelled. Create a new event instead."
                )
        start, end = body.times()
        if event is None:
            # Only identical local records deduplicate; source-owned records never match by title.
            event = db.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.domain_id == DOMAIN,
                    CalendarEvent.source_id.is_(None),
                    CalendarEvent.status != "cancelled",
                    CalendarEvent.title == body.title,
                    CalendarEvent.start_at == start,
                    CalendarEvent.end_at == end,
                    CalendarEvent.summary == body.summary,
                    CalendarEvent.location == body.location,
                    CalendarEvent.all_day == body.all_day,
                    CalendarEvent.timezone == body.timezone,
                    CalendarEvent.blocks_time == body.blocks_time,
                    CalendarEvent.recurrence_rule == body.recurrence_rule,
                )
            )
            if event:
                return {"outcome": "duplicate_skipped", "event_id": str(event.id)}
        action = "updated" if event else "created"
        if event is None:
            event = CalendarEvent(
                domain_id=DOMAIN,
                title=body.title,
                start_at=start,
                end_at=end,
                source_refs=refs,
                provenance={"owner": "airlock", "schema_version": 1},
            )
            db.add(event)
        else:
            event.revision += 1
            db.get(LocalState, 1).context_reset_at = now()
            event.source_refs = [*event.source_refs, *refs][-100:]
        for name in (
            "title",
            "summary",
            "timezone",
            "all_day",
            "blocks_time",
            "location",
            "recurrence_rule",
        ):
            setattr(event, name, getattr(body, name))
        event.start_at, event.end_at = start, end
        event.scheduling_effect = "hard" if body.blocks_time else "informational"
        db.flush()
        record_change(db, event, action, refs)
        return {
            "outcome": action,
            "event_id": str(event.id),
            "revision": event.revision,
        }

    return audited(
        db, "calendar.save", {"event_id": str(event_id) if event_id else None}, apply
    )


def cancel_event(db, event_id, revision, refs):
    def apply():
        event = find_event(db, event_id)
        if event.source_id:
            raise ActionError("Imported events are read-only. Cancel them in Google.")
        if event.revision != revision:
            raise ActionError("This event changed. Refresh before cancelling it.")
        if event.status != "cancelled":
            event.status = "cancelled"
            event.revision += 1
            db.get(LocalState, 1).context_reset_at = now()
            record_change(db, event, "cancelled", refs)
        return {
            "outcome": "cancelled",
            "event_id": str(event.id),
            "revision": event.revision,
        }

    return audited(db, "calendar.cancel", {"event_id": str(event_id)}, apply)


def list_events(db, start, end, *, limit=2000, include_overlays=False):
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= timedelta(days=370)
    ):
        raise ActionError(
            "Choose an explicit timezone and a calendar window of at most 370 days."
        )
    rows = db.scalars(
        select(CalendarEvent)
        .where(
            CalendarEvent.domain_id == DOMAIN,
            CalendarEvent.status != "cancelled",
            CalendarEvent.start_at < end,
            or_(
                CalendarEvent.end_at > start, CalendarEvent.recurrence_rule.is_not(None)
            ),
        )
        .order_by(CalendarEvent.start_at)
    ).all()
    result = []
    for event in rows:
        if event.recurrence_rule:
            zone = ZoneInfo(event.timezone)
            local_start = event.start_at.astimezone(zone)
            duration = event.end_at.astimezone(zone) - local_start
            recurrence = rrulestr(event.recurrence_rule, dtstart=local_start)
            for occurrence in recurrence.xafter(
                start.astimezone(zone) - duration, count=1001, inc=True
            ):
                if occurrence >= end:
                    break
                finish = occurrence + duration
                # Skip nonexistent wall-clock instances at a DST transition.
                if occurrence.astimezone(UTC).astimezone(zone).replace(
                    tzinfo=None
                ) != occurrence.replace(tzinfo=None):
                    continue
                if finish > start:
                    result.append(event_payload(event, occurrence, finish))
                if len(result) > limit:
                    raise ActionError(
                        "Too many calendar occurrences. Narrow the date range."
                    )
        else:
            result.append(event_payload(event))
        if len(result) > limit:
            raise ActionError("Too many calendar events. Narrow the date range.")

    def starts_at(payload):
        value = datetime.fromisoformat(payload["start"])
        if payload["all_day"]:
            value = value.replace(tzinfo=ZoneInfo(payload["timezone"]))
        return value.astimezone(UTC)

    if include_overlays:
        from .exchange import overlays
        result.extend(overlays(db,start,end))
        from .record_exchange import calendar_overlays
        result.extend(calendar_overlays(db, start, end))
    return sorted(result, key=starts_at)
