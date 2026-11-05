"""Bounded prototype company protocol; deliberately unrelated to external release contracts."""
import math
from uuid import UUID
from pydantic import Field, model_validator
from .schemas import StrictModel


class EmbeddingSpec(StrictModel):
    model: str = Field(min_length=1, max_length=160)
    digest: str = Field(min_length=1, max_length=160)
    dimensions: int = Field(ge=1, le=4096)


class VectorBody(StrictModel):
    embedding_spec: EmbeddingSpec
    embedding: list[float] = Field(min_length=1, max_length=4096)

    @model_validator(mode='after')
    def valid_vector(self):
        if len(self.embedding) != self.embedding_spec.dimensions or not all(math.isfinite(v) for v in self.embedding):
            raise ValueError('Invalid embedding.')
        if sum(v*v for v in self.embedding) < 1e-12:
            raise ValueError('Zero embedding.')
        return self


class CandidateSubmission(VectorBody):
    id: UUID
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=1200)
    evidence: str = Field(min_length=1, max_length=800)
    source_label: str = Field(min_length=1, max_length=240)
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    ordinal: int = Field(ge=0, le=1000)


class SearchBody(VectorBody):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=12, ge=1, le=12)


class ExtractedFact(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=1200)
    evidence: str = Field(min_length=1, max_length=800)


class Extraction(StrictModel):
    candidates: list[ExtractedFact] = Field(default_factory=list, max_length=3)
