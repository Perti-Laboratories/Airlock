"""Source-grounded retrieval. Excerpts are evidence, never canonical facts or instructions."""
import hashlib
import re
import uuid
from sqlalchemy import select, delete, or_
from airlock_core.llm import LLMClientError
from .memory import DOMAIN, ActionError, audited
from .models import KnowledgeSource, KnowledgeChunk, LocalState, now

MAX_TEXT = 60_000


def chunks(text, size=1600, overlap=160):
    """Keep exact source text; prefer paragraph/sentence boundaries without an LLM rewrite."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n', start + size // 2, end), text.rfind('. ', start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        part = text[start:end].strip()
        if part:
            yield part
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def put_source(db, *, key, kind, title, content, refs):
    content = content.replace('\x00', '').strip()
    if not content or len(content) > MAX_TEXT:
        raise ActionError('Use a document containing between 1 and 60,000 extracted text characters.')
    source = db.scalar(select(KnowledgeSource).where(KnowledgeSource.domain_id == DOMAIN, KnowledgeSource.source_key == key))
    digest = hashlib.sha256(content.encode()).hexdigest()
    if source and source.content_hash == digest and source.status != 'removed':
        return source
    if not source:
        source = KnowledgeSource(domain_id=DOMAIN, source_key=key, kind=kind)
        db.add(source)
    else:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    source.title, source.content, source.content_hash = title[:240], content, digest
    source.source_refs, source.status, source.error = refs, 'pending', None
    db.flush()
    return source


def index_source(db, llm, source):
    def work():
        audited(db, 'ollama.check_models', {'origin': 'source_indexing'}, llm.check_models)
        parts = list(chunks(source.content))
        # Gather first: a failed embedding cannot leave a partially searchable document.
        vectors = [audited(db, 'ollama.embed_source', {'source_id': str(source.id), 'ordinal': i,
                    'model': llm.embedding_model}, lambda part=part: llm.embed(part)) for i, part in enumerate(parts)]
        if len({len(v) for v in vectors}) != 1:
            raise LLMClientError('Embedding dimensions changed while indexing.')
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
        for i, (part, vector) in enumerate(zip(parts, vectors)):
            db.add(KnowledgeChunk(domain_id=DOMAIN, source_id=source.id, ordinal=i,
                content=part, model=llm.embedding_model, dimensions=len(vector), embedding=vector))
        source.status, source.error = 'ready', None
        db.flush()
        return len(parts)
    try:
        return audited(db, 'knowledge.index', {'source_id': str(source.id)}, work)
    except LLMClientError:
        source.status, source.error = 'failed', 'Local embedding failed. Retry indexing when the model is available.'
        return 0


def payload(db, source, include_content=False):
    from sqlalchemy import func
    value = {'id': str(source.id), 'kind': source.kind, 'title': source.title, 'status': source.status,
        'error': source.error, 'source_refs': source.source_refs, 'created_at': source.created_at.isoformat(),
        'chunks': db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))}
    if include_content:
        value['content'] = source.content
    return value


def find(db, ident):
    row = db.get(KnowledgeSource, ident)
    if not row or row.domain_id != DOMAIN or row.status == 'removed':
        raise ActionError('Source is no longer available in this workspace.')
    return row


def remove(db, source):
    def work():
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
        source.status, source.content, source.error = 'removed', '', None
        db.get(LocalState, 1).context_reset_at = now()
    audited(db, 'knowledge.remove', {'source_id': str(source.id)}, work)


def exclude_message_history(db):
    """Corrections/deletions must not be undone by automatic conversation retrieval."""
    ids = select(KnowledgeSource.id).where(KnowledgeSource.domain_id == DOMAIN, KnowledgeSource.kind == 'message')
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id.in_(ids)))
    for row in db.scalars(select(KnowledgeSource).where(KnowledgeSource.id.in_(ids), KnowledgeSource.status != 'removed')):
        row.status = 'excluded'


def search(db, llm, query, limit=6, preferred_ids=()):
    reset = db.get(LocalState, 1).context_reset_at
    conditions = [KnowledgeSource.domain_id == DOMAIN, KnowledgeSource.status == 'ready',
                  or_(KnowledgeSource.company_restricted.is_(False), KnowledgeSource.id.in_(preferred_ids)),
                  or_(KnowledgeSource.kind != 'message', KnowledgeSource.created_at > reset),
                  KnowledgeChunk.domain_id == DOMAIN, KnowledgeChunk.model == llm.embedding_model]
    if not db.scalar(select(KnowledgeChunk.id).join(KnowledgeSource).where(*conditions).limit(1)):
        return []
    vector = audited(db, 'ollama.embed_source_query', {'model': llm.embedding_model}, lambda: llm.embed(query))
    conditions.append(KnowledgeChunk.dimensions == len(vector))
    base = select(KnowledgeChunk, KnowledgeSource).join(KnowledgeSource).where(*conditions)
    rows = list(db.execute(base.order_by(KnowledgeChunk.embedding.cosine_distance(vector)).limit(32)))
    words = set(re.findall(r'\w{3,}', query.casefold()))
    if words:
        rows += list(db.execute(base.where(or_(*[KnowledgeChunk.content.ilike('%'+w+'%') for w in sorted(words)[:12]])).limit(32)))
    if preferred_ids:
        rows += list(db.execute(base.where(KnowledgeSource.id.in_(preferred_ids)).order_by(KnowledgeChunk.ordinal).limit(16)))
    import math
    def score(row):
        chunk, source = row
        cosine = sum(a*b for a,b in zip(chunk.embedding,vector)) / max(1e-12, math.sqrt(sum(a*a for a in chunk.embedding)*sum(b*b for b in vector)))
        return cosine + .15*len(words & set(re.findall(r'\w{3,}', (source.title+' '+chunk.content).casefold()))) + (0.3 if source.id in preferred_ids else 0)
    unique = {c.id:(c,s) for c,s in rows}
    chosen = sorted(unique.values(), key=score, reverse=True)[:limit]
    return [{'source_id': str(s.id), 'chunk_id': str(c.id), 'title': s.title, 'kind': s.kind, 'company_restricted': s.company_restricted,
             'excerpt': c.content, 'source_refs': s.source_refs} for c,s in chosen]
