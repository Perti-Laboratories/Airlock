import uuid
from pydantic import Field
from .schemas import StrictModel
from .models import Domain
from .exchange import status as exchange_status
from .memory import DOMAIN, audited
from .chat import report
from .releases import (
    PolicyBody,
    OverrideBody,
    policy_payload,
    save_policy,
    save_override,
    preview,
)


class WorkspaceBody(StrictModel):
    name: str = Field(min_length=1, max_length=160)


def attach_release_routes(app, sessions, writer):
    @app.get("/api/workspace")
    def workspace():
        with sessions() as db:
            row = db.get(Domain, DOMAIN)
            return {
                "id": str(row.id),
                "name": row.name,
                "mode": "local",
                "gateway_connected": exchange_status(db)["enabled"],
            }

    @app.put("/api/workspace")
    def rename(body: WorkspaceBody):
        with writer() as db:

            def apply():
                db.get(Domain, DOMAIN).name = body.name

            audited(db, "workspace.rename", {}, apply)
            r = report(
                db,
                "Local workspace name updated.",
                operation="workspace_update",
                changes=[],
                source_refs=[],
            )
            db.commit()
            return {"report_id": str(r.id)}

    @app.get("/api/release-policy")
    def rules():
        with sessions() as db:
            return policy_payload(db)

    @app.put("/api/release-policy")
    def update_rules(body: PolicyBody):
        with writer() as db:
            change = save_policy(db, body)
            r = report(
                db,
                "Local release rules updated. Enabled exchange will reconcile approved content.",
                operation="release_policy",
                changes=[change],
                source_refs=[],
            )
            db.commit()
            return {"report_id": str(r.id), **policy_payload(db)}

    @app.put("/api/release-policy/events/{event_id}")
    def update_exception(event_id: uuid.UUID, body: OverrideBody):
        with writer() as db:
            change = save_override(db, event_id, body)
            r = report(
                db,
                "Local release exception updated. Enabled exchange will reconcile approved content.",
                operation="release_override",
                changes=[change],
                source_refs=[],
            )
            db.commit()
            return {"report_id": str(r.id)}

    @app.get("/api/release-preview")
    def candidates():
        with sessions() as db:
            result = audited(db, "release.preview", {}, lambda: preview(db))
            db.commit()
            return result
