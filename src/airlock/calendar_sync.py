"""Atomic provider mirror updates with bounded rolling windows and incremental cursors."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from airlock_core.calendar import google_calendar_route_payload
from .google import GoogleError
from .calendar import EventBody, record_change
from .memory import DOMAIN, audited, restore_audit_after_rollback
from .models import CalendarEvent, CalendarSource, LocalState, now


def source_payload(source):
    fresh = source.last_synced_at and now() - source.last_synced_at < timedelta(
        minutes=15
    )
    return {
        "id": str(source.id),
        "name": source.name,
        "timezone": source.timezone,
        "enabled": source.enabled,
        "last_synced_at": source.last_synced_at.isoformat()
        if source.last_synced_at
        else None,
        "stale": not bool(fresh and source.enabled and not source.error),
        "error": source.error,
        "window_date": source.window_date,
    }


def fetch_changes(db, google, source, today):
    full = not source.sync_token or source.window_date != today.isoformat()

    def fetch(full):
        params = {"maxResults": 250, "singleEvents": "true", "showDeleted": "true"}
        if full:
            params.update(
                timeMin=datetime.combine(
                    today - timedelta(days=90), datetime.min.time(), UTC
                ).isoformat(),
                timeMax=datetime.combine(
                    today + timedelta(days=366), datetime.min.time(), UTC
                ).isoformat(),
            )
        else:
            params["syncToken"] = source.sync_token
        items = []
        seen_pages = set()
        for _ in range(200):
            data = audited(
                db,
                "google.events.list",
                {"source_id": str(source.id)},
                lambda: google.event_page(source.external_calendar_id, params),
            )
            page_items = data.get("items", [])
            if not isinstance(page_items, list):
                raise GoogleError("Invalid calendar response; no changes were applied.")
            items.extend(page_items)
            if len(items) > 50_000:
                raise GoogleError(
                    "Calendar exceeds the local sync limit; use a smaller test calendar."
                )
            page = data.get("nextPageToken")
            if not page:
                if not data.get("nextSyncToken"):
                    raise GoogleError(
                        "Incomplete calendar sync; previous data is retained."
                    )
                return items, data["nextSyncToken"], full
            if page in seen_pages:
                raise GoogleError(
                    "Repeated Google page token; previous data is retained."
                )
            seen_pages.add(page)
            params["pageToken"] = page
        raise GoogleError(
            "Calendar sync exceeded the page limit; previous data is retained."
        )

    try:
        return fetch(full)
    except GoogleError as exc:
        if exc.status == 410 and not full:
            return fetch(True)
        raise


def sync_source(db, google, source):
    today = now().date()
    items, token, full = fetch_changes(db, google, source, today)
    existing = {
        e.external_event_id: e
        for e in db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.domain_id == DOMAIN, CalendarEvent.source_id == source.id
            )
        )
    }
    seen = set()
    changes = 0
    for raw in items:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise GoogleError("Invalid calendar event; previous data is retained.")
        key = raw["id"]
        seen.add(key)
        event = existing.get(key)
        if raw.get("status") == "cancelled":
            if event and event.status != "cancelled":
                event.status = "cancelled"
                event.revision += 1
                record_change(db, event, "cancelled", event.source_refs)
                changes += 1
            continue
        # Google expands recurrence and moved/cancelled exceptions; provider ID owns identity.
        normalized = dict(raw)
        for field in ("start", "end"):
            normalized[field] = {
                **raw.get(field, {}),
                "timeZone": raw.get(field, {}).get("timeZone", source.timezone),
            }
        route = google_calendar_route_payload(
            {"google_event": normalized, "calendar_id": source.external_calendar_id}
        )
        meta = route["metadata"]
        declined = any(
            a.get("self") and a.get("responseStatus") == "declined"
            for a in raw.get("attendees", [])
        )
        busy = (
            raw.get("transparency") != "transparent"
            and not declined
            and raw.get("eventType") != "workingLocation"
        )
        try:
            # Google may give a UTC timestamp with a distinct display timezone; normalize it first.
            for field in ("start_at", "end_at"):
                if not meta["all_day"]:
                    parsed = datetime.fromisoformat(meta[field].replace("Z", "+00:00"))
                    meta[field] = (
                        parsed.astimezone(ZoneInfo(meta["timezone"])).isoformat()
                        if parsed.tzinfo
                        else parsed.isoformat()
                    )
            body = EventBody(
                title=route["title"][:240],
                summary=route["content"][:4000],
                start=meta["start_at"],
                end=meta["end_at"],
                timezone=meta["timezone"],
                all_day=meta["all_day"],
                blocks_time=busy,
                location=(meta.get("location") or "")[:320],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise GoogleError(
                "Google returned an unsupported event time; previous data is retained."
            ) from exc
        if event and event.external_etag and event.external_etag == raw.get("etag"):
            event.last_synced_at = now()
            continue
        start, end = body.times()
        action = "updated" if event else "created"
        if event is None:
            event = CalendarEvent(
                domain_id=DOMAIN,
                source_id=source.id,
                external_provider="google_calendar",
                external_calendar_id=source.external_calendar_id,
                external_event_id=key,
                title=body.title,
                start_at=start,
                end_at=end,
                provenance={"owner": "google_calendar", "schema_version": 1},
            )
            db.add(event)
            existing[key] = event
        else:
            event.revision += 1
        for field in (
            "title",
            "summary",
            "timezone",
            "all_day",
            "blocks_time",
            "location",
        ):
            setattr(event, field, getattr(body, field))
        event.start_at, event.end_at = start, end
        event.status = (
            "declined"
            if declined
            else ("tentative" if raw.get("status") == "tentative" else "scheduled")
        )
        event.scheduling_effect = "hard" if busy else "informational"
        event.external_etag = raw.get("etag")
        event.last_synced_at = now()
        event.sync_status = "synced"
        event.source_refs = route["source_refs"]
        event.attendees = meta.get("attendees", [])
        event.metadata_ = {
            "recurring_event_id": raw.get("recurringEventId"),
            "original_start": raw.get("originalStartTime"),
            "source_status": raw.get("status", "confirmed"),
        }
        db.flush()
        record_change(db, event, action, event.source_refs)
        changes += 1
    if full:
        for key, event in existing.items():
            if key not in seen and event.status != "cancelled":
                event.status = "cancelled"
                event.revision += 1
                record_change(db, event, "removed_from_mirror", event.source_refs)
                changes += 1
    if changes:
        db.get(LocalState, 1).context_reset_at = now()
    source.sync_token = token
    source.window_date = today.isoformat()
    source.last_synced_at = now()
    source.next_sync_at = now() + timedelta(minutes=5)
    source.failure_count = 0
    source.error = None
    return {"source_id": str(source.id), "changes": changes, "full_sync": full}


def run_sync(sessions, google, source_id, *, force=False):
    from .chat import report

    with sessions() as db:
        source = db.scalar(
            select(CalendarSource).where(
                CalendarSource.id == source_id, CalendarSource.domain_id == DOMAIN
            )
        )
        if not source or not source.enabled:
            return {"status": "paused"}
        if not force and source.next_sync_at and source.next_sync_at > now():
            return {"status": "waiting"}
        try:
            result = audited(
                db,
                "calendar.sync",
                {"source_id": str(source.id)},
                lambda: sync_source(db, google, source),
            )
            r = report(
                db,
                "Calendar sync completed.",
                operation="calendar_sync",
                changes=[result],
                source_refs=[],
            )
            db.commit()
            return {"status": "completed", "report_id": str(r.id), **result}
        except Exception as exc:
            restore_audit_after_rollback(db)
            source = db.get(CalendarSource, source_id)
            source.failure_count += 1
            source.next_sync_at = now() + timedelta(
                seconds=min(3600, 60 * 2 ** min(source.failure_count, 6))
            )
            source.error = (
                str(exc)
                if isinstance(exc, GoogleError)
                else "Calendar sync failed; previous data is retained."
            )
            r = report(
                db,
                source.error,
                operation="calendar_sync",
                changes=[],
                source_refs=[],
                status="failed",
            )
            db.commit()
            return {"status": "failed", "error": source.error, "report_id": str(r.id)}
