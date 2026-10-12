from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text_search import validate_search_query


class DocumentSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1, max_length=256, strict=True)
    candidate_id: UUID | None = None
    document_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=1000)

    @field_validator("q")
    @classmethod
    def require_searchable_query(cls, value: str) -> str:
        return validate_search_query(value)


class DocumentSearchHit(BaseModel):
    document_id: UUID
    candidate_id: UUID
    candidate_name: str
    filename: str
    chunk_set_id: UUID
    chunk_position: int
    start_offset: int
    end_offset: int
    text: str
    chunk_sha256: str
    source_document_sha256: str
    source_text_sha256: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class DocumentSearchPage(BaseModel):
    search_version: Literal["simple-fold-v1"] = "simple-fold-v1"
    items: list[DocumentSearchHit]
    total: int
    limit: int
    offset: int
