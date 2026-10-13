from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text_search import validate_search_query
from app.schemas.document_search import DocumentSearchHit


class SemanticOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["semantic", "hybrid"] = "hybrid"
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    min_similarity: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False, strict=True)


class SemanticDocumentQuery(SemanticOptions):
    q: str = Field(min_length=1, max_length=256, strict=True)
    candidate_id: UUID | None = None
    document_id: UUID | None = None

    @field_validator("q")
    @classmethod
    def searchable(cls, value: str) -> str:
        return validate_search_query(value)


class SemanticJobQuery(SemanticOptions):
    applicants_only: bool = Field(default=False, strict=True)


class RankedEvidence(DocumentSearchHit):
    branch: Literal["semantic", "lexical"]
    embedding_job_id: UUID | None


class SemanticHit(BaseModel):
    candidate_id: UUID
    candidate_name: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    lexical_rank: int | None = Field(default=None, ge=1)
    semantic_rank: int | None = Field(default=None, ge=1)
    evidence: list[RankedEvidence] = Field(min_length=1, max_length=2)


class SemanticPage(BaseModel):
    retrieval_version: Literal["local-cosine-rrf-v1"] = "local-cosine-rrf-v1"
    query_version: Literal["qwen3-resume-query-v1"] = "qwen3-resume-query-v1"
    encoding_version: Literal["qwen3-raw-l2-v1"] = "qwen3-raw-l2-v1"
    model_tag: Literal["qwen3-embedding:0.6b"] = "qwen3-embedding:0.6b"
    dimensions: Literal[1024] = 1024
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["semantic", "hybrid"]
    score_kind: Literal["cosine_similarity", "reciprocal_rank_fusion"]
    unit: Literal["chunk", "candidate"]
    job_id: UUID | None = None
    profile_revision: int | None = Field(default=None, ge=1)
    profile_updated_at: datetime | None = None
    applicants_only: bool = False
    eligible_chunks: int = Field(ge=0)
    embedded_chunks: int = Field(ge=0)
    branch_window: Literal[100] = 100
    pool_truncated: bool
    pooled_count: int = Field(ge=0, le=200)
    limit: int
    items: list[SemanticHit]
