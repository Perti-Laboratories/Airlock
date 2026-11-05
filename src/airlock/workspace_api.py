"""Calendar, connector setup and local orchestration routes for the isolated app."""

import uuid
from datetime import datetime, timedelta
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import select
from .schemas import StrictModel
from .calendar import (
    EventBody,
    EventNote,
    Revision,
    save_event,
    cancel_event,
    list_events,
    find_event,
    event_payload,
    record_change,
)
from .calendar_sync import source_payload, run_sync
from .agents import RunBody, ScheduleBody, AGENTS, queue_run, run_payload
from .models import CalendarSource, AgentRun, AgentSchedule, now, LocalState
from .memory import DOMAIN, ActionError, audited, restore_audit_after_rollback
from .chat import report


class GoogleClientBody(StrictModel):
    document: dict


class SelectCalendar(StrictModel):
    calendar_id: str = Field(min_length=1, max_length=320)


class Enabled(StrictModel):
    enabled: bool


def attach_workspace_routes(app, sessions, writer, google, compute_lock, settings):
    @app.get("/api/calendar")
    def calendar(start: datetime, end: datetime):
        from .exchange import availability_status
        with sessions() as db:
            return {
                "events": list_events(db, start, end, include_overlays=True),
                "incoming_availability": availability_status(db),
                "sources": [
                    source_payload(s)
                    for s in db.scalars(
                        select(CalendarSource).where(CalendarSource.domain_id == DOMAIN)
                    )
                ],
                "timezone": settings.workspace_timezone,
            }

    @app.post("/api/calendar")
    def create_event(body: EventBody):
        with writer() as db:
            refs = [{"type": "raw_note", "origin": "local_calendar_editor"}]
            change = save_event(db, body, refs)
            r = report(
                db,
                "Local calendar event saved.",
                operation="calendar_save",
                changes=[change],
                source_refs=refs,
            )
            db.commit()
            return {**change, "report_id": str(r.id)}

    @app.put("/api/calendar/{event_id}")
    def update_event(event_id: uuid.UUID, body: EventBody):
        with writer() as db:
            refs = [{"type": "raw_note", "origin": "local_calendar_editor"}]
            change = save_event(db, body, refs, event_id=event_id)
            r = report(
                db,
                "Local calendar event updated.",
                operation="calendar_update",
                changes=[change],
                source_refs=refs,
            )
            db.commit()
            return {**change, "report_id": str(r.id)}

    @app.post("/api/calendar/{event_id}/cancel")
    def cancel(event_id: uuid.UUID, body: Revision):
        with writer() as db:
            refs = [{"type": "raw_note", "origin": "local_calendar_editor"}]
            change = cancel_event(db, event_id, body.expected_revision, refs)
            r = report(
                db,
                "Local calendar event cancelled.",
                operation="calendar_cancel",
                changes=[change],
                source_refs=refs,
            )
            db.commit()
            return {**change, "report_id": str(r.id)}

    @app.put("/api/calendar/{event_id}/note")
    def note(event_id: uuid.UUID, body: EventNote):
        with writer() as db:
            event = find_event(db, event_id)
            if event.revision != body.expected_revision:
                raise ActionError("Event changed. Refresh before editing its note.")

            def apply():
                event.local_note = body.note
                event.revision += 1
                db.get(LocalState, 1).context_reset_at = now()
                record_change(
                    db,
                    event,
                    "annotated",
                    [{"type": "raw_note", "origin": "local_calendar_note"}],
                )

            audited(db, "calendar.annotate", {"event_id": str(event_id)}, apply)
            r = report(
                db,
                "Local calendar note saved.",
                operation="calendar_note",
                changes=[{"event_id": str(event_id)}],
                source_refs=[],
            )
            db.commit()
            return {"report_id": str(r.id)}

    @app.get("/api/google/status")
    def google_status():
        with sessions() as db:
            try:
                result = audited(db, "google.credentials.status", {}, google.status)
                db.commit()
                return result
            except ActionError as exc:
                restore_audit_after_rollback(db)
                db.commit()
                return {
                    "configured": False,
                    "connected": False,
                    "error": str(exc),
                    "sharing_enabled": False,
                }

    @app.post("/api/google/configure")
    def configure_client(body: GoogleClientBody):
        with writer() as db:
            if google.status()["connected"]:
                raise ActionError(
                    "Disconnect Google before replacing the app configuration."
                )
            audited(
                db,
                "google.client.configure",
                {},
                lambda: google.configure(body.document),
            )
            db.commit()
            return {"configured": True}

    @app.post("/api/google/reauthorize")
    def reauthorize():
        with writer() as db:
            result = audited(db, "google.oauth.reauthorize", {}, google.open_sign_in)
            db.commit()
            return result

    @app.post("/api/google/connect")
    def connect():
        with writer() as db:
            # Account switching must not merge another account into an existing provider mirror.
            if google.status()["connected"]:
                raise ActionError(
                    "Disconnect the current Google account before reconnecting."
                )
            result = audited(db, "google.oauth.begin", {}, google.open_sign_in)
            db.commit()
            return result

    @app.get("/oauth/google/callback")
    def callback(request: Request):
        try:
            with writer() as db:
                if request.query_params.get("error") or not request.query_params.get(
                    "code"
                ):
                    audited(
                        db,
                        "google.oauth.declined",
                        {},
                        lambda: google.reject_callback(
                            request.query_params.get("state", "")
                        ),
                    )
                    db.commit()
                    return RedirectResponse(
                        "/?view=connections&google=not_connected", status_code=303
                    )
                audited(
                    db,
                    "google.oauth.complete",
                    {},
                    lambda: google.complete(
                        request.query_params.get("state", ""),
                        request.query_params.get("code", ""),
                    ),
                )
                db.commit()
            return RedirectResponse(
                "/?view=connections&google=connected", status_code=303
            )
        except (ActionError, HTTPException):
            return RedirectResponse(
                "/?view=connections&google=not_connected", status_code=303
            )

    @app.post("/api/google/disconnect")
    def disconnect():
        with writer() as db:
            audited(db, "google.disconnect", {}, google.disconnect)
            for source in db.scalars(
                select(CalendarSource).where(CalendarSource.domain_id == DOMAIN)
            ):
                source.enabled = False
                source.sync_token = None
                source.error = "Google disconnected; retained calendar is stale."
            db.commit()
            return {"status": "disconnected"}

    @app.get("/api/google/calendars")
    def available_calendars():
        with writer() as db:
            result = audited(db, "google.calendars.list", {}, google.calendars)
            db.commit()
            return result

    @app.post("/api/calendar-sources")
    def add_source(body: SelectCalendar):
        with writer() as db:
            available = audited(db, "google.calendars.list", {}, google.calendars)
            selected = next((c for c in available if c["id"] == body.calendar_id), None)
            if not selected:
                raise ActionError(
                    "Choose a readable calendar from the connected account."
                )
            source = db.scalar(
                select(CalendarSource).where(
                    CalendarSource.domain_id == DOMAIN,
                    CalendarSource.external_calendar_id == body.calendar_id,
                )
            )
            if source is None:
                source = CalendarSource(
                    domain_id=DOMAIN,
                    external_calendar_id=body.calendar_id,
                    name=selected["name"],
                    timezone=selected["timezone"],
                )
                db.add(source)
            else:
                source.enabled = True
                source.sync_token = None
                source.next_sync_at = None
                source.error = None
            db.commit()
            return source_payload(source)

    @app.patch("/api/calendar-sources/{source_id}")
    def enable_source(source_id: uuid.UUID, body: Enabled):
        with writer() as db:
            source = db.scalar(
                select(CalendarSource).where(
                    CalendarSource.id == source_id, CalendarSource.domain_id == DOMAIN
                )
            )
            if not source:
                raise HTTPException(404)
            if body.enabled:
                available = audited(db, "google.calendars.list", {}, google.calendars)
                if not any(c["id"] == source.external_calendar_id for c in available):
                    raise ActionError("This account cannot read the selected calendar.")
                source.sync_token = None
                source.next_sync_at = None
            source.enabled = body.enabled
            db.commit()
            return source_payload(source)

    @app.post("/api/calendar-sources/{source_id}/sync")
    def synchronize(source_id: uuid.UUID):
        if not compute_lock.acquire(blocking=False):
            raise ActionError(
                "Local processing is busy. Automatic sync will retry shortly."
            )
        try:
            return run_sync(sessions, google, source_id, force=True)
        finally:
            compute_lock.release()

    @app.get("/api/agents")
    def agents():
        return {
            "agents": AGENTS,
            "domain": "local",
            "model": settings.model,
            "max_steps": 3,
            "remote_dispatch_enabled": False,
        }

    @app.get("/api/agent-runs")
    def runs():
        with sessions() as db:
            return [
                run_payload(r)
                for r in db.scalars(
                    select(AgentRun)
                    .where(AgentRun.domain_id == DOMAIN)
                    .order_by(AgentRun.created_at.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/agent-runs")
    def enqueue(body: RunBody):
        with writer() as db:
            run = queue_run(
                db,
                body.instruction,
                [{"type": "raw_note", "origin": "local_agent_console"}],
            )
            db.commit()
            return run_payload(run)

    @app.post("/api/agent-runs/{run_id}/cancel")
    def cancel_run(run_id: uuid.UUID):
        # Cancellation can be requested while the worker is waiting for a model response.
        with sessions() as db:
            run = db.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.domain_id == DOMAIN)
                .with_for_update()
            )
            if not run:
                raise HTTPException(404)
            if run.status in {"queued", "running"}:
                run.cancel_requested = True
                if run.status == "queued":
                    run.status = "cancelled"
                    run.completed_at = now()
                r = report(
                    db,
                    "Local agent cancellation requested.",
                    operation="agent_cancel",
                    changes=[{"run_id": str(run.id)}],
                    source_refs=[],
                )
                run.report_id = r.id
                db.commit()
            return run_payload(run)

    @app.get("/api/agent-schedules")
    def schedules():
        with sessions() as db:
            return [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "instruction": s.instruction,
                    "interval_minutes": s.interval_minutes,
                    "enabled": s.enabled,
                    "next_run_at": s.next_run_at.isoformat(),
                }
                for s in db.scalars(
                    select(AgentSchedule).where(AgentSchedule.domain_id == DOMAIN)
                )
            ]

    @app.post("/api/agent-schedules")
    def add_schedule(body: ScheduleBody):
        with writer() as db:
            item = AgentSchedule(
                domain_id=DOMAIN,
                **body.model_dump(),
                next_run_at=now() + timedelta(minutes=body.interval_minutes),
            )
            db.add(item)
            db.flush()
            r = report(
                db,
                "Local agent schedule created.",
                operation="agent_schedule",
                changes=[{"schedule_id": str(item.id)}],
                source_refs=[],
            )
            db.commit()
            return {"id": str(item.id), "report_id": str(r.id)}

    @app.patch("/api/agent-schedules/{schedule_id}")
    def enable_schedule(schedule_id: uuid.UUID, body: Enabled):
        with writer() as db:
            item = db.scalar(
                select(AgentSchedule).where(
                    AgentSchedule.id == schedule_id, AgentSchedule.domain_id == DOMAIN
                )
            )
            if not item:
                raise HTTPException(404)
            item.enabled = body.enabled
            if body.enabled:
                item.next_run_at = now() + timedelta(minutes=item.interval_minutes)
            db.commit()
            return {"enabled": item.enabled}
