"""The local Curator is the sole entry point for canonical-memory mutations."""
import hashlib
import re
import uuid
from datetime import UTC, datetime
from sqlalchemy import select, delete
from airlock_core.memory import MemoryCandidate, MemoryModels, MemoryService
from .config import DOMAIN_ID
from .models import MemoryItem, MemoryProposal, MemoryEmbedding, MemoryLink, LocalState, ToolCall, now

DOMAIN = uuid.UUID(DOMAIN_ID)


class ActionError(ValueError):
    pass


def audited(db, name, arguments, work):
    call = ToolCall(domain_id=DOMAIN, tool_name=name, input_payload=arguments)
    db.add(call)
    db.flush()
    try:
        result = work()
        call.status = "completed"
        return result
    except Exception:
        call.status = "failed"
        raise
    finally:
        call.completed_at = now()
        db.info.setdefault("audit_attempts", []).append(dict(
            id=call.id, domain_id=DOMAIN, tool_name=name, status=call.status,
            input_payload=arguments, output_payload={}, created_at=call.created_at,
            completed_at=call.completed_at))


def restore_audit_after_rollback(db):
    attempts = db.info.pop("audit_attempts", [])
    db.rollback()
    # A protected chat turn may commit its restriction before subsequent model/tool calls.
    # Those earlier audit rows already exist; replay only attempts from the rolled-back work.
    committed=set(db.scalars(select(ToolCall.id).where(ToolCall.id.in_([e['id'] for e in attempts])))) if attempts else set()
    for entry in attempts:
        if entry['id'] in committed: continue
        entry["output_payload"] = {"transaction_rolled_back": True}
        db.add(ToolCall(**entry))


def active_query():
    return select(MemoryItem).where(MemoryItem.domain_id == DOMAIN, MemoryItem.scope == "domain",
                                    MemoryItem.valid_until.is_(None))


def memory_payload(item):
    return {
        "id": str(item.id), "title": item.title, "content": item.content,
        "memory_type": item.memory_type, "impact_level": item.impact_level,
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
        "source_refs": (item.metadata_ or {}).get("source_refs", []),
        "embedding_status": (item.metadata_ or {}).get("embedding_status", "unknown"),
    }


class Embeddings:
    def __init__(self, db, llm):
        self.db, self.llm = db, llm

    def upsert_memory_embedding(self, item):
        text = f"{item.title}\n{item.content}"
        vector = audited(self.db, "ollama.embed", {"memory_id": str(item.id), "model": self.llm.embedding_model},
                         lambda: self.llm.embed(text))
        self.db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id))
        self.db.add(MemoryEmbedding(memory_item_id=item.id, model=self.llm.embedding_model,
                                    dimensions=len(vector), content_hash=hashlib.sha256(text.encode()).hexdigest(),
                                    embedding=vector))
        return type("EmbeddingResult", (), {"status": "written"})()


class LocalMemoryCurator:
    def __init__(self, db, llm):
        self.db, self.llm = db, llm
        self.service = MemoryService(db, models=MemoryModels(MemoryItem, MemoryProposal, MemoryLink),
                                     manage_transactions=False, embedding_service=Embeddings(db, llm))

    def get_active(self, memory_id):
        item = self.db.scalar(active_query().where(MemoryItem.id == memory_id))
        if item is None:
            raise ActionError("That memory is no longer active in this workspace. Refresh and choose a current memory.")
        return item

    def _reset_context(self):
        self.db.get(LocalState, 1).context_reset_at = now()
        from .knowledge import exclude_message_history
        exclude_message_history(self.db)

    def _invalidate(self, item, *, forgotten=False):
        item.valid_until = now()
        item.metadata_ = {**item.metadata_, "archived": True}
        self.db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_item_id == item.id))
        for p in self.db.scalars(select(MemoryProposal).where(MemoryProposal.domain_id == DOMAIN,
                                                              MemoryProposal.status == "pending_user_approval")):
            if p.metadata_.get("replaces") == str(item.id):
                p.status = "rejected"
                p.reviewed_at = now()
        if forgotten:
            item.title, item.content = "Forgotten memory", ""
            if item.created_from_proposal_id:
                p = self.db.get(MemoryProposal, item.created_from_proposal_id)
                p.title, p.content = "Forgotten memory", ""
                p.rationale = None
        self._reset_context()

    def forget(self, memory_id):
        item = self.get_active(memory_id)
        audited(self.db, "memory.forget", {"memory_id": str(item.id)}, lambda: self._invalidate(item, forgotten=True))
        return {"outcome": "forgotten", "memory_id": str(item.id)}

    def save(self, body, *, source_refs, replaces=None):
        old = self.get_active(replaces) if replaces else None
        impact = body.impact_level
        if body.memory_type == "standing_instruction" or re.search(
            r"\b(very.high|password|credential|approval|authorize|security policy)\b", body.content, re.I
        ):
            impact = "very_high"
        meta = {"curator": "airlock-local", "source_refs": source_refs}
        if old:
            meta.update(replaces=str(old.id), replaces_updated_at=old.updated_at.isoformat())
        candidate = MemoryCandidate(scope="domain", domain_id=DOMAIN, memory_type=body.memory_type,
                                    title=body.title, content=body.content, impact_level=impact,
                                    source_refs=source_refs, metadata=meta,
                                    rationale="Explicit local user request, validated by the local Curator.")
        result = audited(self.db, "memory.curate", {"operation": "correct" if old else "remember"},
                         lambda: self.service.write_candidate(candidate))
        item = result.memory_item or result.related_memory
        if result.outcome == "pending_user_approval":
            return {"outcome": result.outcome, "proposal_id": str(result.proposal.id)}
        if item and old and item.id != old.id:
            self._invalidate(old)
            self.db.add(MemoryLink(source_memory_id=item.id, target_memory_id=old.id, relation_type="supersedes"))
        return {"outcome": result.outcome, "memory_id": str(item.id) if item else None}

    def review(self, proposal_id, approve):
        p = self.db.scalar(select(MemoryProposal).where(MemoryProposal.id == proposal_id, MemoryProposal.domain_id == DOMAIN))
        if p is None or p.status != "pending_user_approval":
            raise ActionError("This proposal is not pending in the current workspace.")
        if not approve:
            audited(self.db, "memory.reject", {"proposal_id": str(p.id)}, lambda: self.service.reject_proposal(p.id))
            return {"outcome": "rejected", "proposal_id": str(p.id)}
        old = self.get_active(uuid.UUID(p.metadata_["replaces"])) if p.metadata_.get("replaces") else None
        if old and old.updated_at.isoformat() != p.metadata_.get("replaces_updated_at"):
            raise ActionError("The original memory changed. Reject this proposal and make a new correction.")
        item = audited(self.db, "memory.approve", {"proposal_id": str(p.id)}, lambda: self.service.approve_proposal(p.id))
        if old:
            self._invalidate(old)
            self.db.add(MemoryLink(source_memory_id=item.id, target_memory_id=old.id, relation_type="supersedes"))
        return {"outcome": "approved", "memory_id": str(item.id), "proposal_id": str(p.id)}


def retrieve(db, llm, query, limit=12):
    # Vector similarity handles paraphrases; exact word overlap boosts sparse proper nouns.
    active = list(db.scalars(active_query().order_by(MemoryItem.updated_at.desc()).limit(1000)))
    if not active:
        return []
    vector = audited(db, "ollama.embed_query", {"model": llm.embedding_model}, lambda: llm.embed(query))
    distance = MemoryEmbedding.embedding.cosine_distance(vector)
    rows = db.execute(select(MemoryItem.id, distance).join(MemoryEmbedding, MemoryEmbedding.memory_item_id == MemoryItem.id)
                      .where(MemoryItem.domain_id == DOMAIN, MemoryItem.valid_until.is_(None),
                             MemoryEmbedding.model == llm.embedding_model, MemoryEmbedding.dimensions == len(vector))
                      .order_by(distance).limit(1000)).all()
    scores = {key: 1-float(value) for key, value in rows}
    words = set(re.findall(r"\w{3,}", query.casefold()))
    ranked = sorted(active, key=lambda m: scores.get(m.id, 0)+0.1*len(words & set(re.findall(r"\w{3,}", (m.title+' '+m.content).casefold()))), reverse=True)
    return [memory_payload(m) for m in ranked[:limit]]
