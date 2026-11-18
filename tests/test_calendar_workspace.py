import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import select, func
from airlock.calendar import EventBody, list_events, save_event
from airlock.calendar_sync import run_sync
from airlock.google import GoogleError, GoogleCalendar, SCOPES
from airlock.memory import DOMAIN
from airlock.models import (
    CalendarEvent,
    CalendarSource,
    MemoryItem,
    RoutedItem,
    ToolCall,
)


def event(**changes):
    return {
        "title": "Synthetic review",
        "start": "2026-11-01T10:00",
        "end": "2026-11-01T11:00",
        "timezone": "America/New_York",
        **changes,
    }


def test_calendar_crud_is_routed_not_fact_memory_and_stale_edit_fails(workspace):
    c, _, sessions, _ = workspace
    first = c.post("/api/calendar", json=event())
    assert first.status_code == 200, first.text
    key = first.json()["event_id"]
    duplicate = c.post("/api/calendar", json=event()).json()
    assert duplicate["outcome"] == "duplicate_skipped"
    changed = c.put(
        "/api/calendar/" + key,
        json=event(
            start="2026-11-02T10:00", end="2026-11-02T11:00", expected_revision=1
        ),
    )
    assert changed.status_code == 200
    assert (
        c.put("/api/calendar/" + key, json=event(expected_revision=1)).status_code
        == 409
    )
    assert (
        c.post(
            "/api/calendar/" + key + "/cancel", json={"expected_revision": 2}
        ).status_code
        == 200
    )
    with sessions() as db:
        assert db.get(CalendarEvent, uuid.UUID(key)).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(RoutedItem)) == 3
        assert db.scalar(select(func.count()).select_from(MemoryItem)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-03-08T02:30", "end": "2026-03-08T03:30"},
        {"start": "2026-11-01T01:30", "end": "2026-11-01T02:30"},
        {"start": "2026-11-01T10:00-04:00", "end": "2026-11-01T11:00-04:00"},
        {"all_day": True, "start": "2026-11-01", "end": "2026-11-01"},
        {"start": "2026-11-01T10:00", "end": "2026-11-01T10:00", "blocks_time": False},
        {"recurrence_rule": "FREQ=SECONDLY"},
    ],
)
def test_invalid_calendar_times_and_unbounded_frequency_are_rejected(changes):
    with pytest.raises(ValueError):
        EventBody(**event(**changes))


def test_all_day_exclusive_end_and_recurrence_preserve_dst_wall_time(workspace):
    _, _, sessions, _ = workspace
    with sessions() as db:
        body = EventBody(
            **event(
                start="2026-10-25T09:00",
                end="2026-10-25T10:00",
                recurrence_rule="FREQ=WEEKLY;COUNT=3",
            )
        )
        save_event(db, body, [])
        db.commit()
        rows = list_events(
            db, datetime(2026, 10, 24, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC)
        )
        assert len(rows) == 3
        assert all("T09:00" in r["start"] for r in rows)
        assert rows[0]["start"].endswith("-04:00") and rows[1]["start"].endswith(
            "-05:00"
        )
    all_day = EventBody(**event(all_day=True, start="2026-11-01", end="2026-11-02"))
    start, end = all_day.times()
    assert end - start == timedelta(hours=25)


class Provider:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def event_page(self, calendar_id, params):
        self.requests.append(dict(params))
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def raw(key="event-one", **changes):
    return {
        "id": key,
        "etag": "v1",
        "summary": "Provider meeting",
        "start": {"dateTime": "2026-11-02T14:00:00Z"},
        "end": {"dateTime": "2026-11-02T15:00:00Z"},
        **changes,
    }


def source(sessions):
    with sessions() as db:
        s = CalendarSource(
            domain_id=DOMAIN,
            external_calendar_id="synthetic@example.invalid",
            name="Synthetic calendar",
            timezone="America/New_York",
        )
        db.add(s)
        db.commit()
        return s.id


@pytest.mark.parametrize("offsetless", [False, True])
def test_google_point_events_preserve_instants_and_never_release(workspace, offsetless):
    c, _, sessions, _ = workspace
    key = source(sessions)
    point = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    from zoneinfo import ZoneInfo
    stamp = (point.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None).isoformat()
             if offsetless else point.isoformat())
    item = raw(start={"dateTime": stamp}, end={"dateTime": stamp})
    result = run_sync(sessions, Provider([{"items": [item], "nextSyncToken": "point1"}]), key, force=True)
    assert result["status"] == "completed"
    with sessions() as db:
        row = db.scalar(select(CalendarEvent))
        identity = row.id
        assert row.start_at == row.end_at == point
        assert not row.blocks_time and row.scheduling_effect == "informational"
        assert row.source_refs[0]["event_id"] == "event-one"
        # Include a point at the window start, exclude one exactly at its end.
        assert len(list_events(db, point, point + timedelta(hours=1))) == 1
        assert list_events(db, point - timedelta(hours=1), point) == []
    policy = c.get("/api/release-policy").json()
    assert c.put("/api/release-policy", json={
        "expected_revision": policy["revision"], "paused": False,
        "rules": {str(key): "busy"}, "type_rules": {"calendar": "busy"},
    }).status_code == 200
    preview = c.get("/api/release-preview").json()
    assert preview["eligible_count"] == 0
    assert len(preview["items"]) == 1 and preview["items"][0]["candidate"] is None
    # A later provider duration restores normal busy semantics on the same record.
    item.update(etag="v2", start={"dateTime": point.isoformat()},
                end={"dateTime": (point + timedelta(hours=1)).isoformat()})
    assert run_sync(sessions, Provider([{"items": [item], "nextSyncToken": "point2"}]), key, force=True)["status"] == "completed"
    with sessions() as db:
        row = db.get(CalendarEvent, identity)
        assert row.blocks_time and row.scheduling_effect == "hard"
        assert row.end_at - row.start_at == timedelta(hours=1)
    assert c.get("/api/release-preview").json()["eligible_count"] == 1
    item.update(etag="v3", end={"dateTime": point.isoformat()})
    assert run_sync(sessions, Provider([{"items": [item], "nextSyncToken": "point3"}]), key, force=True)["status"] == "completed"
    assert c.get("/api/release-preview").json()["eligible_count"] == 0
    with sessions() as db:
        assert db.get(CalendarEvent, identity).start_at == db.get(CalendarEvent, identity).end_at


@pytest.mark.parametrize("invalid", [
    {"end": {"dateTime": "2026-11-02T13:00:00Z"}},
    {"start": {"date": "2026-11-02"}, "end": {"date": "2026-11-02"}},
    {"end": {"dateTime": "not-a-date"}},
    {"end": {"dateTime": "2028-11-02T14:00:00Z"}},
])
def test_invalid_google_intervals_still_roll_back_entire_sync(workspace, invalid):
    _, _, sessions, _ = workspace
    key = source(sessions)
    assert run_sync(sessions, Provider([{"items": [raw()], "nextSyncToken": "old"}]), key, force=True)["status"] == "completed"
    items = [raw(etag="v2", summary="Should roll back"), raw("invalid", **invalid)]
    assert run_sync(sessions, Provider([{"items": items, "nextSyncToken": "bad"}]), key, force=True)["status"] == "failed"
    with sessions() as db:
        row = db.scalar(select(CalendarEvent))
        assert row.title == "Provider meeting" and row.revision == 1
        assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 1
        assert db.get(CalendarSource, key).sync_token == "old"


@pytest.mark.parametrize("change", [
    {"source_id": None}, {"external_provider": None},
    {"external_provider": "other"}, {"external_event_id": None},
    {"all_day": True}, {"blocks_time": True}, {"recurrence_rule": "FREQ=DAILY"},
])
def test_database_only_allows_nonblocking_google_point_events(workspace, change):
    from sqlalchemy.exc import IntegrityError
    _, _, sessions, _ = workspace
    key = source(sessions)
    point = datetime(2026, 11, 2, 14, tzinfo=UTC)
    fields = dict(domain_id=DOMAIN, source_id=key, external_provider="google_calendar",
                  external_event_id="point", title="Synthetic point", start_at=point,
                  end_at=point, blocks_time=False, all_day=False)
    fields.update(change)
    with sessions() as db:
        db.add(CalendarEvent(**fields))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_google_pagination_incremental_move_cancel_and_ownership(workspace):
    c, _, sessions, _ = workspace
    key = source(sessions)
    provider = Provider(
        [
            {"items": [raw()], "nextPageToken": "page2"},
            {"items": [], "nextSyncToken": "cursor1"},
        ]
    )
    assert run_sync(sessions, provider, key, force=True)["status"] == "completed"
    assert provider.requests[1]["pageToken"] == "page2"
    with sessions() as db:
        e = db.scalar(select(CalendarEvent))
        event_id = e.id
        assert e.start_at.hour == 14 and e.blocks_time
        e.local_note = "Keep this local note"
        db.commit()
    assert (
        c.put(
            "/api/calendar/" + str(event_id), json=event(expected_revision=1)
        ).status_code
        == 409
    )
    updated = raw(
        etag="v2",
        start={"dateTime": "2026-11-02T16:00:00Z"},
        end={"dateTime": "2026-11-02T17:00:00Z"},
        transparency="transparent",
    )
    incremental = Provider([{"items": [updated], "nextSyncToken": "cursor2"}])
    assert run_sync(sessions, incremental, key, force=True)["status"] == "completed"
    assert (
        incremental.requests[0]["syncToken"] == "cursor1"
        and "timeMin" not in incremental.requests[0]
    )
    with sessions() as db:
        e = db.get(CalendarEvent, event_id)
        assert e.start_at.hour == 16 and not e.blocks_time
        assert e.local_note == "Keep this local note"
        assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 1
    assert (
        run_sync(
            sessions,
            Provider(
                [
                    {
                        "items": [{"id": "event-one", "status": "cancelled"}],
                        "nextSyncToken": "cursor3",
                    }
                ]
            ),
            key,
            force=True,
        )["status"]
        == "completed"
    )
    with sessions() as db:
        assert db.get(CalendarEvent, event_id).status == "cancelled"


def test_failed_resync_keeps_mirror_and_cursor_then_atomic_410_rebuild(workspace):
    _, _, sessions, _ = workspace
    key = source(sessions)
    assert (
        run_sync(
            sessions,
            Provider([{"items": [raw()], "nextSyncToken": "old"}]),
            key,
            force=True,
        )["status"]
        == "completed"
    )
    with sessions() as db:
        local = save_event(db, EventBody(**event()), [])
        db.commit()
    failed = Provider(
        [
            GoogleError("expired", 410),
            {"items": [], "nextPageToken": "next"},
            GoogleError("Offline"),
        ]
    )
    assert run_sync(sessions, failed, key, force=True)["status"] == "failed"
    with sessions() as db:
        assert db.get(CalendarSource, key).sync_token == "old"
        assert (
            db.scalar(
                select(CalendarEvent).where(CalendarEvent.source_id == key)
            ).status
            == "scheduled"
        )
        assert db.scalar(
            select(ToolCall).where(
                ToolCall.tool_name == "google.events.list", ToolCall.status == "failed"
            )
        )
    rebuild = Provider(
        [GoogleError("expired", 410), {"items": [], "nextSyncToken": "new"}]
    )
    assert run_sync(sessions, rebuild, key, force=True)["status"] == "completed"
    with sessions() as db:
        assert (
            db.scalar(
                select(CalendarEvent).where(CalendarEvent.source_id == key)
            ).status
            == "cancelled"
        )
        assert db.get(CalendarEvent, uuid.UUID(local["event_id"])).status == "scheduled"


def test_declined_and_free_all_day_google_events_do_not_block(workspace):
    _, _, sessions, _ = workspace
    key = source(sessions)
    items = [
        raw(
            "declined",
            attendees=[
                {
                    "self": True,
                    "email": "test@example.invalid",
                    "responseStatus": "declined",
                }
            ],
        ),
        raw(
            "allday",
            start={"date": "2026-11-02"},
            end={"date": "2026-11-03"},
            transparency="transparent",
        ),
    ]
    assert (
        run_sync(
            sessions,
            Provider([{"items": items, "nextSyncToken": "cursor"}]),
            key,
            force=True,
        )["status"]
        == "completed"
    )
    with sessions() as db:
        events = list(db.scalars(select(CalendarEvent)))
        assert len(events) == 2 and all(not e.blocks_time for e in events)
        assert any(e.status == "declined" for e in events)


class Vault:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


def test_oauth_pkce_state_scope_and_no_secrets_in_status(workspace):
    from urllib.parse import urlsplit, parse_qs

    _, _, _, settings = workspace
    vault = Vault()
    calls = []

    def transport(host, path, **kwargs):
        calls.append((host, path, kwargs))
        if host == "www.googleapis.com":
            return {"items": [{"primary": True, "id": "test@example.com"}]}
        return {
            "scope": " ".join(SCOPES),
            "refresh_token": "synthetic-refresh",
            "access_token": "synthetic-access",
            "expires_in": 3600,
        }

    google = GoogleCalendar(settings, vault=vault, transport=transport)
    google.configure(
        {
            "installed": {
                "client_id": "synthetic.apps.googleusercontent.com",
                "client_secret": "synthetic-client",
            }
        }
    )
    query = parse_qs(urlsplit(google.begin()).query)
    assert query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == SCOPES
    with pytest.raises(GoogleError):
        google.complete("wrong", "synthetic-code")
    google.complete(query["state"][0], "synthetic-code")
    assert google.status()["connected"] and "synthetic" not in str(google.status())
    assert calls[0][2]["form"]["code_verifier"]
    with pytest.raises(GoogleError):
        google.complete(query["state"][0], "replay")
    google.disconnect()
    assert not google.status()["connected"]


def test_chat_create_cannot_overwrite_a_model_supplied_existing_target(workspace):
    c, llm, sessions, _ = workspace
    from airlock.models import now

    start = (now() + timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    body = event(
        start=start.isoformat(),
        end=(start + timedelta(hours=1)).isoformat(),
        timezone="UTC",
    )
    original = c.post("/api/calendar", json=body).json()
    llm.decision = dict(
        answer="I will add the event.",
        action="calendar_create",
        target_id=original["event_id"],
        title="",
        content="",
        memory_type="fact",
        impact_level="low",
        event={
            **body,
            "title": "Wrong replacement",
            "all_day": False,
            "blocks_time": True,
        },
    )
    response = c.post(
        "/api/chat", json={"message": "Add a calendar event tomorrow."}
    ).json()
    assert response["status"] == "failed"
    assert "cannot target an existing record" in response["answer"]
    assert response["changes"] == []
    with sessions() as db:
        saved = db.get(CalendarEvent, uuid.UUID(original["event_id"]))
        assert saved.title == "Synthetic review"
        assert saved.revision == 1
        assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 1


def test_calendar_orders_different_timezones_by_actual_start(workspace):
    _, _, sessions, _ = workspace
    with sessions() as db:
        save_event(
            db,
            EventBody(
                **event(
                    title="Later",
                    start="2026-10-15T09:00",
                    end="2026-10-15T10:00",
                    timezone="America/Los_Angeles",
                )
            ),
            [],
        )
        save_event(
            db,
            EventBody(
                **event(
                    title="Earlier",
                    start="2026-10-15T11:00",
                    end="2026-10-15T12:00",
                    timezone="Europe/London",
                )
            ),
            [],
        )
        db.commit()
        rows = list_events(
            db, datetime(2026, 10, 15, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC)
        )
        assert [r["title"] for r in rows] == ["Earlier", "Later"]
