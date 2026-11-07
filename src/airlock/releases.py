"""Local release policy and candidate preview. Only allowlisted content enters exchange."""

from datetime import timedelta
from typing import Literal
from pydantic import Field, model_validator
from sqlalchemy import select
from .schemas import StrictModel
from .memory import DOMAIN, ActionError, audited
from .models import ReleasePolicy, ReleaseOverride, CalendarSource, RecordExchange, LocalState, now
from .calendar import list_events, find_event
from .calendar_sync import source_payload

Mode = Literal["private", "busy", "original"]


class TypeRules(StrictModel):
    # These are disclosure ceilings, never a substitute for source/item approval.
    calendar: Literal["private", "busy", "original"] = "private"
    todo: Literal["private", "title", "title_due"] = "private"
    contacts: Literal["private"] = "private"
    memory: Literal["private"] = "private"
    company_memory: Literal["private"] = "private"


def legacy_type_rules():
    # Prior versions gated calendars per source and tasks per individual review.
    return TypeRules(calendar="original", todo="title_due").model_dump()


class PolicyBody(StrictModel):
    expected_revision: int = Field(ge=0)
    paused: bool
    rules: dict[str, Mode] = Field(max_length=100)
    acknowledge_titles: bool = False
    type_rules: TypeRules | None = None


class OverrideBody(StrictModel):
    expected_event_revision: int = Field(ge=1)
    expected_policy_revision: int = Field(ge=0)
    mode: Literal["inherit", "private", "busy", "reviewed"]
    display_title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def reviewed_title(self):
        if self.mode == "reviewed" and not self.display_title:
            raise ValueError("A reviewed title is required.")
        if self.mode != "reviewed" and self.display_title:
            raise ValueError("Only reviewed titles may contain text.")
        return self


def policy_payload(db):
    row = db.get(ReleasePolicy, DOMAIN)
    sources = list(
        db.scalars(select(CalendarSource).where(CalendarSource.domain_id == DOMAIN))
    )
    from .exchange import status
    connection = status(db)
    return {
        "revision": row.revision if row else 0,
        "paused": row.paused if row else True,
        "rules": row.rules if row else {},
        "type_rules": row.type_rules if row else TypeRules().model_dump(),
        "sources": [
            {"id": "local", "name": "Locally created calendar events", "stale": False}
        ]
        + [
            {"id": str(s.id), "name": s.name, "stale": source_payload(s)["stale"]}
            for s in sources
        ],
        "transport_connected": connection["enabled"],
        "destination": connection.get("endpoint"),
        "supported_types": ["event", "todo"],
    }


def save_policy(db, body):
    current = policy_payload(db)
    if body.expected_revision != current["revision"]:
        raise ActionError("The release rules changed. Refresh before saving.")
    if set(body.rules) - {s["id"] for s in current["sources"]}:
        raise ActionError("Choose sources from this local workspace.")
    # Omission by an older client preserves a saved type policy. Only its first
    # legacy save uses the historical ceilings; source/item approvals still apply.
    type_rules = body.type_rules.model_dump() if body.type_rules is not None else (
        current["type_rules"] if db.get(ReleasePolicy, DOMAIN) else legacy_type_rules()
    )
    if (type_rules["calendar"] == "original" and "original" in body.rules.values()
            and not body.acknowledge_titles):
        raise ActionError("Explicitly allow original titles before saving that rule.")

    def apply():
        row = db.get(ReleasePolicy, DOMAIN)
        if row is None:
            row = ReleasePolicy(domain_id=DOMAIN, revision=0)
            db.add(row)
        row.revision += 1
        row.paused, row.rules = body.paused, body.rules
        row.type_rules = type_rules
        incoming = db.get(RecordExchange, DOMAIN)
        if incoming:
            incoming.inbound = None
            from airlock_connector.board_peer import cancel
            incoming.board_state = cancel(incoming.board_state)
            db.get(LocalState, 1).context_reset_at = now()
        # Overrides bind to the policy revision and are re-reviewed if rules change.
        db.flush()
        return {"policy_revision": row.revision, "paused": row.paused}

    return audited(
        db, "release.policy.save", {"previous_revision": current["revision"]}, apply
    )


def save_override(db, event_id, body):
    event = find_event(db, event_id)
    policy = policy_payload(db)
    if (
        event.revision != body.expected_event_revision
        or policy["revision"] != body.expected_policy_revision
    ):
        raise ActionError(
            "The event or release rules changed. Refresh and review again."
        )

    def apply():
        row = db.get(ReleaseOverride, event_id)
        if body.mode == "inherit":
            if row:
                db.delete(row)
        else:
            if row is None:
                row = ReleaseOverride(event_id=event_id, domain_id=DOMAIN)
                db.add(row)
            row.event_revision, row.policy_revision = event.revision, policy["revision"]
            row.mode, row.display_title = body.mode, body.display_title
        db.flush()
        return {
            "event_id": str(event_id),
            "mode": body.mode,
            "policy_revision": policy["revision"],
        }

    return audited(db, "release.override.save", {"event_id": str(event_id)}, apply)


def preview(db):
    policy = policy_payload(db)
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    events = list_events(db, start, start + timedelta(days=30))
    overrides = {
        str(r.event_id): r
        for r in db.scalars(
            select(ReleaseOverride).where(ReleaseOverride.domain_id == DOMAIN)
        )
    }
    stale = {s["id"]: s["stale"] for s in policy["sources"]}
    items = []
    for event in events:
        source = event["source_id"] or "local"
        mode = policy["rules"].get(source, "private")
        override = overrides.get(event["id"])
        review_needed = bool(
            override
            and (
                override.event_revision != event["revision"]
                or override.policy_revision != policy["revision"]
            )
        )
        if override:
            # An outdated private exception must never fall back to a broader source rule.
            mode = "private" if review_needed else override.mode
        calendar_level = policy["type_rules"]["calendar"]
        if calendar_level == "busy" and mode in ("original", "reviewed"):
            mode = "busy"
        reason, candidate = "", None
        if policy["paused"]:
            reason = "All releases paused"
        elif calendar_level == "private":
            reason = "Calendar sharing is off"
        elif review_needed:
            reason = "Event or rules changed; review the exception again"
        elif mode == "private":
            reason = "Keep inside this workspace"
        elif stale.get(source, True):
            reason = "Source is stale; fresh sync required"
        elif not event["blocks_time"]:
            reason = "Free or declined event; no busy block"
        elif mode == "original" and len(event["title"]) > 160:
            reason = "Title needs a shorter reviewed replacement"
        else:
            title = (
                "Busy"
                if mode == "busy"
                else (override.display_title if mode == "reviewed" else event["title"])
            )
            candidate = {
                "title": title,
                "busy": True,
                "all_day": event["all_day"],
                "start": event["start"],
                "end": event["end"],
                "timezone": event["timezone"],
            }
            reason = "Eligible under current rules"
        # This wrapper is local review information; only candidate is the payload preview.
        items.append(
            {
                "event_id": event["id"],
                "event_revision": event["revision"],
                "export_key": event["occurrence_id"] if event["recurrence_rule"] else event["id"],
                "local_title": event["title"],
                "local_start": event["start"],
                "recurring": bool(event["recurrence_rule"]),
                "source_name": next(
                    (s["name"] for s in policy["sources"] if s["id"] == source),
                    "Calendar",
                ),
                "override_mode": override.mode if override else "inherit",
                "display_title": override.display_title
                if override and not review_needed
                else None,
                "review_needed": review_needed,
                "reason": reason,
                "candidate": candidate,
            }
        )
    return {
        "policy_revision": policy["revision"],
        "transport_connected": policy["transport_connected"],
        "window_start": start.isoformat(),
        "window_end": (start + timedelta(days=30)).isoformat(),
        "items": items,
        "eligible_count": sum(i["candidate"] is not None for i in items),
    }
