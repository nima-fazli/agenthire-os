import unicodedata
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.text_search import validate_search_query
from app.schemas.document_search import DocumentSearchHit


class MatchCriterionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    label: str = Field(strict=True, min_length=1, max_length=100)
    q: str = Field(strict=True, min_length=1, max_length=256)
    importance: Literal["required", "preferred"] = "required"

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        value = value.strip()
        if not value or any(
            unicodedata.category(char) in {"Cc", "Cs"} for char in value
        ):
            raise ValueError("Criterion label must be nonblank text without controls.")
        return value

    @field_validator("q")
    @classmethod
    def require_query(cls, value: str) -> str:
        return validate_search_query(value)


class MatchCriterionRead(MatchCriterionInput):
    position: int = Field(ge=0, le=9)


class JobMatchProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[MatchCriterionInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def require_unique_keys(self) -> Self:
        if len({item.key for item in self.criteria}) != len(self.criteria):
            raise ValueError("Criterion keys must be unique within a job profile.")
        return self


class JobMatchProfileRead(BaseModel):
    job_id: UUID
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    criteria: list[MatchCriterionRead] = Field(min_length=1, max_length=10)


class MatchEvidenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionEvidence(MatchCriterionRead):
    evidence: DocumentSearchHit | None


class MatchEvidenceSummary(BaseModel):
    required_total: int = Field(ge=0)
    required_with_evidence: int = Field(ge=0)
    preferred_total: int = Field(ge=0)
    preferred_with_evidence: int = Field(ge=0)
    ready_documents: int = Field(ge=0)
    indexed_documents: int = Field(ge=0)
    source_status: Literal["no_documents", "not_indexed", "partial", "indexed"]


class JobMatchEvidenceRead(BaseModel):
    job_id: UUID
    candidate_id: UUID
    candidate_name: str
    profile_revision: int = Field(ge=1)
    profile_updated_at: datetime
    observed_at: datetime
    search_version: Literal["simple-fold-v1"] = "simple-fold-v1"
    matching_version: Literal["criterion-evidence-v1"] = "criterion-evidence-v1"
    evidence_kind: Literal["lexical_terms"] = "lexical_terms"
    criteria: list[CriterionEvidence] = Field(min_length=1, max_length=10)
    summary: MatchEvidenceSummary
