"""Provider normalization for local Airlock workspaces."""
from datetime import UTC, datetime
from typing import Any

def google_calendar_route_payload(event_payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one provider event into connected planner's routed-event contract."""
    google_event = event_payload.get("google_event")
    if not isinstance(google_event, dict):
        raise TypeError("Calendar event payload is missing google_event.")
    event_id = str(event_payload.get("event_id") or google_event.get("id") or "").strip()
    if not event_id:
        raise ValueError("Calendar event payload is missing event_id.")

    start = google_event.get("start") if isinstance(google_event.get("start"), dict) else {}
    end = google_event.get("end") if isinstance(google_event.get("end"), dict) else {}
    original_start = (
        google_event.get("originalStartTime")
        if isinstance(google_event.get("originalStartTime"), dict)
        else {}
    )
    all_day = bool(start.get("date") and not start.get("dateTime"))
    attendees = [
        {
            "name": str(item.get("displayName") or item.get("email") or "").strip(),
            "email": item.get("email"),
            "response_status": item.get("responseStatus") or "needs_action",
            "is_organizer": bool(item.get("organizer")),
            "is_user": bool(item.get("self")),
        }
        for item in google_event.get("attendees") or []
        if isinstance(item, dict) and (item.get("displayName") or item.get("email"))
    ]
    organizer = (
        google_event.get("organizer")
        if isinstance(google_event.get("organizer"), dict)
        else {}
    )
    recurrence = next(
        (
            str(item).removeprefix("RRULE:")
            for item in google_event.get("recurrence") or []
            if str(item).startswith("RRULE:")
        ),
        None,
    )
    conferencing_url = str(google_event.get("hangoutLink") or "").strip() or None
    if not conferencing_url:
        conference_data = (
            google_event.get("conferenceData")
            if isinstance(google_event.get("conferenceData"), dict)
            else {}
        )
        conferencing_url = next(
            (
                str(item.get("uri") or "").strip()
                for item in conference_data.get("entryPoints") or []
                if isinstance(item, dict)
                and item.get("entryPointType") == "video"
                and item.get("uri")
            ),
            None,
        )

    calendar_id = str(event_payload.get("calendar_id") or "primary")
    source_policy = (
        event_payload.get("source_policy")
        if isinstance(event_payload.get("source_policy"), dict)
        else {}
    )
    source_ref = {
        "type": "google_calendar_event",
        "provider": "google_calendar",
        "calendar_id": calendar_id,
        "event_id": event_id,
        "event_version": event_payload.get("event_version"),
        "recurring_event_id": google_event.get("recurringEventId"),
        "original_start_at": original_start.get("dateTime") or original_start.get("date"),
        "html_link": google_event.get("htmlLink"),
        "updated": google_event.get("updated"),
    }
    return {
        "route_type": "event",
        "title": str(google_event.get("summary") or "Untitled calendar event"),
        "content": str(
            google_event.get("description")
            or google_event.get("summary")
            or "Calendar event"
        ),
        "status": "cancelled" if google_event.get("status") == "cancelled" else "open",
        "source_refs": [source_ref],
        "metadata": {
            "start_at": start.get("dateTime") or start.get("date"),
            "end_at": end.get("dateTime") or end.get("date"),
            "timezone": start.get("timeZone") or end.get("timeZone") or "America/New_York",
            "all_day": all_day,
            "recurrence_rule": recurrence,
            "location": google_event.get("location"),
            "conferencing_url": conferencing_url,
            "organizer_name": organizer.get("displayName"),
            "organizer_email": organizer.get("email"),
            "attendees": attendees,
            "external_provider": "google_calendar",
            "external_calendar_id": calendar_id,
            "external_event_id": event_id,
            "external_etag": google_event.get("etag"),
            "sync_status": "synced",
            "provider_updated_at": google_event.get("updated"),
            "recurring_event_id": google_event.get("recurringEventId"),
            "recurrence_original_start_at": (
                original_start.get("dateTime") or original_start.get("date")
            ),
            "item_kind": source_policy.get("item_kind") or "event",
            "context_type": source_policy.get("context_type"),
            "scheduling_effect": source_policy.get("scheduling_effect") or "hard",
            "blocks_time": source_policy.get("blocks_time", True),
            "source_calendar_summary": source_policy.get("calendar_summary"),
            "source_inclusion_policy": source_policy.get("inclusion_policy"),
            # Provider payloads are already structured; skip the generic LLM enricher.
            "enriched_at": datetime.now(UTC).isoformat(),
            "enrichment_source": "google_calendar_adapter",
        },
    }
