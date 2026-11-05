import hmac
import threading
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import Query
from contextlib import contextmanager, asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from airlock_core.llm import LLMClientError
from . import __version__
from .config import Settings
from .db import database
from .llm import LocalOllama
from .memory import DOMAIN, ActionError, LocalMemoryCurator, active_query, memory_payload, audited, restore_audit_after_rollback
from .models import Conversation, Message, MemoryProposal, Report, ToolCall, MemoryItem, LocalState
from .chat import run_chat, conversation, report
from .schemas import ChatBody, MemoryBody, FeedAckBody
from .security import new_session, valid_session, csrf

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, *, llm=None, sessions=None, google=None):
    settings = settings or Settings()
    # Browser cookies are scoped by host/path, not port. Concurrent local
    # workspaces must not overwrite each other's session cookie.
    session_cookie = f"airlock_session_{settings.port}"
    if sessions is None:
        _, sessions = database(settings)
    llm = llm or LocalOllama(settings)
    with sessions() as db:
        local_state = db.get(LocalState, 1)
        if local_state and local_state.chat_model:
            llm.model = local_state.chat_model
    from .google import GoogleCalendar
    from .workers import LocalWorker
    google = google or GoogleCalendar(settings)
    lock = threading.Lock()
    from . import release_guard
    release_lock = threading.RLock()
    sessions.configure(info={'release_lock': release_lock})
    from .progress import TurnProgress
    chat_progress = TurnProgress()
    worker = LocalWorker(sessions,llm,google,lock,release_lock)
    @asynccontextmanager
    async def lifespan(app):
        if settings.workers_enabled: worker.start()
        try: yield
        finally:
            if settings.workers_enabled: worker.stop()
    app = FastAPI(title="Airlock", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.sessions, app.state.llm = settings, sessions, llm

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.headers.get("host") != f"127.0.0.1:{settings.port}":
            return JSONResponse({"detail": "Unexpected host."}, status_code=403)
        if request.url.path.startswith("/api/"):
            if request.headers.get("sec-fetch-site") not in {None, "none", "same-origin"}:
                return JSONResponse({"detail": "Cross-origin requests are disabled."}, status_code=403)
            cookie = request.cookies.get(session_cookie)
            if not valid_session(settings.session_secret, cookie):
                return JSONResponse({"detail": "Your local session expired. Refresh Airlock to continue.",
                                     "code": "local_session_expired"}, status_code=401)
            if request.method not in {"GET", "HEAD"}:
                if request.headers.get("origin") != settings.origin:
                    return JSONResponse({"detail": "Request must come from this Airlock window."}, status_code=403)
                if not hmac.compare_digest(
                    request.headers.get("x-airlock-csrf", ""), csrf(settings.session_secret, cookie)
                ):
                    return JSONResponse({"detail": "Your local session changed. Refresh Airlock to continue.",
                                         "code": "local_csrf_changed"}, status_code=403)
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    return JSONResponse({"detail": "JSON is required."}, status_code=415)
                try:
                    size = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    size = -1
                max_body = 2_810_000 if request.url.path == '/api/knowledge/upload' else 32768
                if size < 0 or size > max_body:
                    return JSONResponse({"detail": "Request body is missing or too large."}, status_code=413)
                total = 0
                parts = []
                async for part in request.stream():
                    total += len(part)
                    if total > max_body:
                        return JSONResponse({"detail": "Request body is too large."}, status_code=413)
                    parts.append(part)
                request._body = b''.join(parts)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"})
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "Invalid request fields. No action was applied."}, status_code=422)

    @app.exception_handler(ActionError)
    async def invalid_action(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(LLMClientError)
    async def model_failure(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def database_failure(request, exc):
        return JSONResponse({"detail": "Local database operation failed. No partial action was committed."}, status_code=503)

    @contextmanager
    def writer():
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Airlock is finishing another change. Try again shortly.")
        try:
            with sessions() as db:
                try:
                    yield db
                except (LLMClientError, ActionError, SQLAlchemyError):
                    restore_audit_after_rollback(db)
                    report(db, "Local action failed; no memory change was committed.",
                           operation="local_action", changes=[], source_refs=[], status="failed")
                    db.commit()
                    raise
        finally:
            lock.release()

    @contextmanager
    def release_writer():
        # Policy changes and publication must be serialized, even during inference.
        with release_lock, sessions() as db:
            try:
                yield db
            except (LLMClientError, ActionError, SQLAlchemyError):
                restore_audit_after_rollback(db)
                report(db, "Release action failed; no policy change was committed.",
                       operation="release_action", changes=[], source_refs=[], status="failed")
                db.commit()
                raise

    @app.get("/")
    def index(request: Request):
        response = FileResponse(STATIC / "index.html")
        if not valid_session(settings.session_secret, request.cookies.get(session_cookie)):
            response.set_cookie(session_cookie, new_session(settings.session_secret), httponly=True,
                                samesite="strict", max_age=86400, path="/")
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "airlock", "version": __version__}

    @app.get("/api/session")
    def session(request: Request):
        return {"csrf": csrf(settings.session_secret, request.cookies[session_cookie])}

    @app.get("/api/status")
    def status():
        with sessions() as db:
            db.execute(text("SELECT 1"))
        with sessions() as db:
            try:
                models = audited(db, "ollama.check_models", {"origin": "status"}, llm.check_models)
                model_status, error = "ready", None
                db.commit()
            except LLMClientError as exc:
                restore_audit_after_rollback(db)
                db.commit()
                models, model_status, error = {}, "unavailable", str(exc)
        from .exchange import status as exchange_status
        with sessions() as db:
            connected = exchange_status(db)["enabled"]
        return {"version": __version__, "workspace": settings.workspace_name, "database": "ready",
                "provider": "ollama", "model": llm.model, "embedding_model": llm.embedding_model,
                "model_status": model_status, "model_digests": models, "error": error,
                "exchange_enabled": connected, "connectors_enabled": True, "workspace_timezone": settings.workspace_timezone}

    @app.get("/api/feed")
    def assistant_feed(acknowledged: bool = False, before: datetime | None = None,
                       before_key: str | None = Query(default=None, max_length=80)):
        from .feed import listing
        if (before is None) != (before_key is None) or (before and before.tzinfo is None):
            raise HTTPException(422, "Invalid feed cursor.")
        with sessions() as db:
            return listing(db, acknowledged=acknowledged, before=before, before_key=before_key)

    @app.post("/api/feed/acknowledge")
    def acknowledge_visible_feed(body: FeedAckBody):
        from .feed import acknowledge
        with writer() as db:
            results = [acknowledge(db, key) for key in dict.fromkeys(body.keys)]
            db.commit()
            return {"results": results}

    @app.post("/api/feed/{key}/acknowledge")
    def acknowledge_feed_item(key: str):
        from .feed import acknowledge
        with writer() as db:
            result = acknowledge(db, key)
            db.commit()
            return result

    @app.get("/api/conversations")
    def conversations():
        with sessions() as db:
            rows = db.scalars(select(Conversation).where(Conversation.domain_id == DOMAIN)
                              .order_by(Conversation.updated_at.desc()).limit(100)).all()
            return [{"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows]

    @app.post("/api/conversations")
    def create_conversation():
        with writer() as db:
            c = conversation(db)
            db.commit()
            return {"id": str(c.id), "title": c.title}

    @app.get("/api/conversations/{conversation_id}")
    def messages(conversation_id: uuid.UUID):
        with sessions() as db:
            c = conversation(db, conversation_id)
            rows = db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)).all()
            return {"id": str(c.id), "title": c.title,
                    "messages": [{"id": str(m.id), "role": m.sender_type, "content": m.content,
                                  "metadata": m.metadata_, "created_at": m.created_at.isoformat()} for m in rows]}

    @app.get("/api/messages/{message_id}")
    def source_message(message_id: uuid.UUID):
        with sessions() as db:
            row = db.scalar(select(Message).join(Conversation).where(
                Message.id == message_id, Conversation.domain_id == DOMAIN))
            if row is None:
                raise HTTPException(404, "Message not found in this workspace.")
            return {"id": str(row.id), "content": row.content}

    @app.get("/api/chat-progress/{request_id}")
    def turn_progress(request_id: uuid.UUID):
        result=chat_progress.get(str(request_id))
        if result is None: raise HTTPException(404, "Turn progress is not available.")
        return result

    @app.post("/api/chat")
    def chat(body: ChatBody):
        request_id=str(body.request_id or uuid.uuid4())
        chat_progress.start(request_id)
        try:
            with writer() as db:
                result = run_chat(db, llm, body, timezone=settings.workspace_timezone,
                    progress=lambda steps:chat_progress.update(request_id,steps))
            chat_progress.finish(request_id,result['status'])
            return JSONResponse(result, status_code=200 if result["status"] == "completed" else 503)
        except Exception:
            chat_progress.finish(request_id,'failed')
            raise

    @app.get("/api/memories")
    def memories():
        with sessions() as db:
            return [memory_payload(m) for m in db.scalars(active_query().order_by(MemoryItem.updated_at.desc()))]

    def apply_memory(body=None, memory_id=None, forget=False):
        with writer() as db:
            curator = LocalMemoryCurator(db, llm)
            if forget:
                result = curator.forget(memory_id)
            else:
                audited(db, "ollama.check_models", {}, llm.check_models)
                result = curator.save(body, source_refs=[{"type": "raw_note", "origin": "local_memory_editor"}], replaces=memory_id)
            r = report(db, "Memory change recorded", operation="forget" if forget else "curate",
                       changes=[result], source_refs=[{"type": "raw_note", "origin": "local_memory_editor"}])
            db.commit()
            return {**result, "report_id": str(r.id)}

    @app.post("/api/memories")
    def remember(body: MemoryBody):
        return apply_memory(body)

    @app.patch("/api/memories/{memory_id}")
    def correct(memory_id: uuid.UUID, body: MemoryBody):
        return apply_memory(body, memory_id)

    @app.delete("/api/memories/{memory_id}")
    def forget(memory_id: uuid.UUID):
        return apply_memory(memory_id=memory_id, forget=True)

    @app.get("/api/proposals")
    def proposals():
        with sessions() as db:
            rows = db.scalars(select(MemoryProposal).where(MemoryProposal.domain_id == DOMAIN,
                              MemoryProposal.status == "pending_user_approval").order_by(MemoryProposal.created_at)).all()
            return [{"id": str(p.id), "title": p.title, "content": p.content, "impact_level": p.impact_level,
                     "memory_type": p.memory_type, "source_refs": p.source_refs} for p in rows]

    @app.post("/api/proposals/{proposal_id}/{decision}")
    def review(proposal_id: uuid.UUID, decision: str):
        if decision not in {"approve", "reject"}:
            raise HTTPException(404)
        with writer() as db:
            if decision == "approve":
                audited(db, "ollama.check_models", {}, llm.check_models)
            result = LocalMemoryCurator(db, llm).review(proposal_id, decision == "approve")
            r = report(db, f"Memory proposal {decision}d", operation=decision, changes=[result], source_refs=[])
            db.commit()
            return {**result, "report_id": str(r.id)}

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: uuid.UUID):
        with sessions() as db:
            r = db.scalar(select(Report).where(Report.id == report_id, Report.domain_id == DOMAIN))
            if r is None:
                raise HTTPException(404)
            return {"id": str(r.id), "title": r.title, "summary": r.summary, "structured_data": r.structured_data}

    @app.get("/api/activity")
    def activity():
        with sessions() as db:
            rows = db.scalars(select(ToolCall).where(ToolCall.domain_id == DOMAIN).order_by(ToolCall.created_at.desc()).limit(50))
            return [{"id": str(t.id), "tool": t.tool_name, "status": t.status, "created_at": t.created_at.isoformat()} for t in rows]

    from .workspace_api import attach_workspace_routes
    attach_workspace_routes(app,sessions,writer,google,lock,settings)
    from .release_api import attach_release_routes
    attach_release_routes(app, sessions, release_writer)
    from .exchange_api import attach_exchange_routes
    attach_exchange_routes(app, sessions, writer, settings, release_lock, release_writer)
    from .knowledge_api import attach_knowledge_routes
    attach_knowledge_routes(app, sessions, writer, llm)
    from .company_api import attach_company_routes
    attach_company_routes(app, sessions, writer, llm)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
