from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.job_matching import CriterionEvidence, MatchEvidenceSummary


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["fa", "en"] = "en"


class QuoteChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    criterion: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    source: str = Field(pattern=r"^s[0-9]{1,2}$")
    quote: str = Field(min_length=1, max_length=400)


class ExplanationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quotes: list[QuoteChoice] = Field(min_length=1, max_length=10)


class QuoteCitation(BaseModel):
    document_id: UUID
    chunk_set_id: UUID
    chunk_position: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    quote: str
    quote_sha256: str
    chunk_sha256: str
    source_document_sha256: str
    source_text_sha256: str


class CriterionExplanation(CriterionEvidence):
    state: Literal["mention_observed", "no_evidence"]
    text: str
    citation: QuoteCitation | None


class GroundedExplanation(BaseModel):
    explanation_version: Literal["extractive-brief-v2"] = "extractive-brief-v2"
    prompt_version: Literal["local-quote-selection-v2"] = "local-quote-selection-v2"
    citation_policy: Literal["assigned-chunk-context-v1"] = "assigned-chunk-context-v1"
    matching_version: Literal["criterion-evidence-v1"] = "criterion-evidence-v1"
    evidence_kind: Literal["lexical_terms"] = "lexical_terms"
    job_id: UUID
    candidate_id: UUID
    candidate_name: str
    profile_revision: int
    profile_updated_at: datetime
    observed_at: datetime
    validated_at: datetime
    language: Literal["fa", "en"]
    generator_used: bool
    model_tag: Literal["qwen3:0.6b"] | None = None
    model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_tokens: int = Field(default=0, ge=0, le=8192)
    output_tokens: int = Field(default=0, ge=0, le=1024)
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    summary: MatchEvidenceSummary
    summary_text: str
    scope_note: str
    criteria: list[CriterionExplanation] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def consistent_generation(self):
        if self.generator_used:
            if self.model_tag is None or self.model_digest is None or not self.input_tokens or not self.output_tokens:
                raise ValueError("Generation requires complete model and token provenance.")
        elif self.model_tag is not None or self.model_digest is not None or self.input_tokens or self.output_tokens:
            raise ValueError("Unused generation must not claim model or token observations.")
        return self
