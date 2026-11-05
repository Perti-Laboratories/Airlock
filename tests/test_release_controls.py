import json
import uuid
from datetime import timedelta
from sqlalchemy import select
from airlock.models import CalendarSource, CalendarEvent, ToolCall, now
from airlock.memory import DOMAIN


def create_event(c, **changes):
    start = (now() + timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    body = dict(
        title="PRIVATE_TITLE",
        start=start.isoformat(),
        end=(start + timedelta(hours=1)).isoformat(),
        timezone="UTC",
        summary="PRIVATE_DESCRIPTION",
        location="PRIVATE_LOCATION",
        **changes,
    )
    return c.post("/api/calendar", json=body).json(), body


def policy(c, **changes):
    return c.put(
        "/api/release-policy",
        json=dict(
            expected_revision=c.get("/api/release-policy").json()["revision"],
            paused=False,
            rules={"local": "busy"},
            **changes,
        ),
    )


def test_default_closed_busy_allowlist_and_persistent_revision(workspace):
    c, _, sessions, _ = workspace
    create_event(c)
    assert c.get("/api/release-preview").json()["eligible_count"] == 0
    saved = policy(c).json()
    assert saved["revision"] == 1 and not saved["transport_connected"]
    preview = c.get("/api/release-preview").json()
    payload = preview["items"][0]["candidate"]
    assert set(payload) == {"title", "busy", "all_day", "start", "end", "timezone"}
    assert payload["title"] == "Busy"
    assert "PRIVATE" not in json.dumps(payload)
    assert c.get("/api/release-policy").json()["rules"] == {"local": "busy"}
    assert (
        c.put(
            "/api/release-policy",
            json={"expected_revision": 0, "paused": False, "rules": {}},
        ).status_code
        == 409
    )
    with sessions() as db:
        assert db.scalar(
            select(ToolCall).where(ToolCall.tool_name == "release.policy.save")
        )


def test_unknown_sources_extra_fields_and_unacknowledged_titles_are_denied(workspace):
    c, _, _, _ = workspace
    for body in [
        {"rules": {"other-domain": "busy"}},
        {"rules": {"local": "original"}},
        {"rules": {"local": "busy"}, "endpoint": "https://example.com"},
    ]:
        response = c.put(
            "/api/release-policy",
            json={"expected_revision": 0, "paused": False, **body},
        )
        assert response.status_code in (409, 422)
    assert c.get("/api/release-policy").json()["revision"] == 0
    saved = c.put(
        "/api/release-policy",
        json={
            "expected_revision": 0,
            "paused": False,
            "rules": {"local": "original"},
            "acknowledge_titles": True,
        },
    )
    assert saved.status_code == 200


def test_event_changes_and_policy_changes_invalidate_reviewed_title(workspace):
    c, _, _, _ = workspace
    event, body = create_event(c)
    policy(c)
    exception = {
        "expected_event_revision": 1,
        "expected_policy_revision": 1,
        "mode": "reviewed",
        "display_title": "Approved meeting",
    }
    url = "/api/release-policy/events/" + event["event_id"]
    assert c.put(url, json=exception).status_code == 200
    assert (
        c.get("/api/release-preview").json()["items"][0]["candidate"]["title"]
        == "Approved meeting"
    )
    c.put(
        "/api/calendar/" + event["event_id"],
        json={**body, "title": "Changed private title", "expected_revision": 1},
    )
    item = c.get("/api/release-preview").json()["items"][0]
    assert item["review_needed"] and item["candidate"] is None
    assert c.put(url, json=exception).status_code == 409
    exception["expected_event_revision"] = 2
    assert c.put(url, json=exception).status_code == 200
    policy(c)
    assert c.get("/api/release-preview").json()["items"][0]["candidate"] is None


def test_private_exception_remains_closed_after_rule_changes_and_pause_wins(workspace):
    c, _, _, _ = workspace
    event, _ = create_event(c)
    policy(c)
    c.put(
        "/api/release-policy/events/" + event["event_id"],
        json={
            "expected_event_revision": 1,
            "expected_policy_revision": 1,
            "mode": "private",
        },
    )
    c.put(
        "/api/release-policy",
        json={
            "expected_revision": 1,
            "paused": False,
            "rules": {"local": "original"},
            "acknowledge_titles": True,
        },
    )
    assert c.get("/api/release-preview").json()["eligible_count"] == 0
    c.put(
        "/api/release-policy/events/" + event["event_id"],
        json={
            "expected_event_revision": 1,
            "expected_policy_revision": 2,
            "mode": "inherit",
        },
    )
    assert c.get("/api/release-preview").json()["eligible_count"] == 1
    c.put(
        "/api/release-policy",
        json={"expected_revision": 2, "paused": True, "rules": {"local": "busy"}},
    )
    assert c.get("/api/release-preview").json()["eligible_count"] == 0


def test_stale_provider_and_free_events_cannot_release(workspace):
    c, _, sessions, _ = workspace
    event, _ = create_event(c)
    free, _ = create_event(c, blocks_time=False)
    with sessions() as db:
        source = CalendarSource(
            domain_id=DOMAIN,
            external_calendar_id="PRIVATE_SOURCE",
            name="Source",
            timezone="UTC",
            enabled=True,
        )
        db.add(source)
        db.flush()
        row = db.get(CalendarEvent, uuid.UUID(event["event_id"]))
        row.source_id = source.id
        db.commit()
        source_id = str(source.id)
    c.put(
        "/api/release-policy",
        json={
            "expected_revision": 0,
            "paused": False,
            "rules": {"local": "busy", source_id: "busy"},
        },
    )
    preview = c.get("/api/release-preview").json()
    assert preview["eligible_count"] == 0
    assert any("stale" in i["reason"] for i in preview["items"])
    with sessions() as db:
        db.get(CalendarSource, uuid.UUID(source_id)).last_synced_at = now()
        db.commit()
    assert c.get("/api/release-preview").json()["eligible_count"] == 1


def test_type_rules_strict_defaults_and_legacy_clients_cannot_reset_ceiling(workspace):
    c, _, _, _ = workspace
    initial = c.get('/api/release-policy').json()
    assert set(initial['type_rules'].values()) == {'private'}
    for invalid in [{'calendar': 'title_due'}, {'todo': 'busy'}, {'contacts': 'title'},
                    {'memory': 'title'}, {'company_memory': 'title'}, {'unknown': 'private'}]:
        assert policy(c, type_rules=invalid).status_code == 422
    assert policy(c, type_rules={'calendar': 'busy'}).status_code == 200
    saved = c.get('/api/release-policy').json()['type_rules']
    assert saved['todo'] == 'private'
    # An old pause/resume client that omits type_rules must preserve the ceiling.
    assert policy(c).status_code == 200
    assert c.get('/api/release-policy').json()['type_rules'] == saved
    assert c.put('/api/release-policy', json={'expected_revision': 0,
        'paused': False, 'rules': {}, 'type_rules': {'calendar': 'original'}}).status_code == 409


def test_type_off_blocks_fresh_event_exception_and_private_source_stays_private(workspace):
    c, _, _, _ = workspace
    event, _ = create_event(c)
    saved = policy(c, type_rules={'calendar': 'private'}).json()
    assert c.put('/api/release-policy/events/' + event['event_id'], json={
        'expected_event_revision': 1, 'expected_policy_revision': saved['revision'],
        'mode': 'reviewed', 'display_title': 'Approved title'}).status_code == 200
    assert c.get('/api/release-preview').json()['eligible_count'] == 0
    p = c.get('/api/release-policy').json()
    assert c.put('/api/release-policy', json={'expected_revision': p['revision'],
        'paused': False, 'rules': {}, 'type_rules': {'calendar': 'original'}}).status_code == 200
    c.put('/api/release-policy/events/' + event['event_id'], json={
        'expected_event_revision': 1, 'expected_policy_revision': p['revision'] + 1,
        'mode': 'inherit'})
    assert c.get('/api/release-preview').json()['eligible_count'] == 0


def test_migration_preserves_legacy_permissions_and_downgrade_pauses(workspace):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    c, _, sessions, _ = workspace
    assert policy(c).status_code == 200
    spec = importlib.util.spec_from_file_location('type_migration', 'alembic/versions/0009_type_release_rules.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Exercise real PostgreSQL DDL inside a rollback-only transaction on airlock_test.
    with sessions() as db:
        connection = db.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            old = connection.execute(text('SELECT paused, revision FROM release_policies')).one()
            assert old.paused and old.revision == 2
            connection.execute(text('UPDATE release_policies SET paused = false, revision = 7'))
            migration.upgrade()
            restored = connection.execute(text('SELECT paused, revision, rules, type_rules FROM release_policies')).one()
            assert not restored.paused and restored.revision == 7
            assert restored.rules == {'local': 'busy'}
            assert restored.type_rules == {'calendar': 'original', 'todo': 'title_due',
                'contacts': 'private', 'memory': 'private', 'company_memory': 'private'}
        db.rollback()
