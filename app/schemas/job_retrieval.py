from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text_search import validate_search_query
from app.schemas.document_search import DocumentSearchHit


class JobSearchProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1, max_length=256, strict=True)

    @field_validator("q")
    @classmethod
    def require_searchable_query(cls, value: str) -> str:
        return validate_search_query(value)


class JobSearchProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    job_id: UUID
    q: str = Field(validation_alias="query_text")
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class JobCandidateQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicants_only: bool = False
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=1000)


class JobCandidatePage(BaseModel):
    job_id: UUID
    q: str
    profile_revision: int = Field(ge=1)
    profile_updated_at: datetime
    search_version: Literal["simple-fold-v1"] = "simple-fold-v1"
    retrieval_version: Literal["best-chunk-v1"] = "best-chunk-v1"
    score_kind: Literal["text_relevance"] = "text_relevance"
    applicants_only: bool
    items: list[DocumentSearchHit]
    total: int = Field(ge=0)
    limit: int
    offset: int
