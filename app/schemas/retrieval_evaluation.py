from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.text_search import validate_search_query
from app.schemas.job_matching import MatchCriterionInput

EvalKey = Annotated[str, Field(strict=True, pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")]
Grade = Annotated[int, Field(strict=True, ge=0, le=3)]
Rate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
SourceStatus = Literal["no_documents", "not_indexed", "partial", "indexed"]
SourceKind = Literal["example", "real_stack", "imported"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankingCase(StrictModel):
    key: EvalKey
    q: str = Field(strict=True, min_length=1, max_length=256)
    k: int = Field(strict=True, ge=1, le=50)
    judgments: dict[EvalKey, Grade] = Field(min_length=1, max_length=200)
    forbidden: list[EvalKey] = Field(default_factory=list, max_length=200)

    @field_validator("q")
    @classmethod
    def query(cls, value):
        return validate_search_query(value)

    @model_validator(mode="after")
    def forbidden_items(self) -> Self:
        if len(set(self.forbidden)) != len(self.forbidden) or any(
            self.judgments.get(item) != 0 for item in self.forbidden
        ):
            raise ValueError("Forbidden items must have unique zero-grade judgments.")
        return self


class EvidenceCase(StrictModel):
    key: EvalKey
    item_id: EvalKey
    expected: dict[EvalKey, bool] = Field(min_length=1, max_length=10)
    source_status: SourceStatus
    profile_revision: int = Field(strict=True, ge=1)

    @field_validator("expected", mode="before")
    @classmethod
    def literal_booleans(cls, value):
        if isinstance(value, dict) and any(
            type(item) is not bool for item in value.values()
        ):
            raise ValueError("Expected evidence labels must be booleans.")
        return value


class QualityThresholds(StrictModel):
    mean_precision_at_k: Rate | None = None
    mean_recall_at_k: Rate | None = None
    mean_ndcg_at_k: Rate | None = None
    mean_reciprocal_rank_at_k: Rate | None = None
    evidence_precision: Rate | None = None
    evidence_recall: Rate | None = None


class EvaluationSuite(StrictModel):
    protocol_version: Literal["retrieval-quality-v1"] = "retrieval-quality-v1"
    suite_id: EvalKey
    corpus_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    label_kind: Literal["synthetic_reference", "reviewed_reference"]
    criteria: list[MatchCriterionInput] = Field(default_factory=list, max_length=10)
    ranking: list[RankingCase] = Field(default_factory=list, max_length=100)
    evidence: list[EvidenceCase] = Field(default_factory=list, max_length=100)
    thresholds: QualityThresholds

    @model_validator(mode="after")
    def consistent_cases(self) -> Self:
        keys = [case.key for case in self.ranking] + [
            case.key for case in self.evidence
        ]
        criteria = [item.key for item in self.criteria]
        if (
            not keys
            or len(set(keys)) != len(keys)
            or len(set(criteria)) != len(criteria)
        ):
            raise ValueError("Cases and criterion keys must be nonempty and unique.")
        if any(set(case.expected) != set(criteria) for case in self.evidence):
            raise ValueError("Evidence labels must cover the configured criteria.")
        if not any(
            value is not None for value in self.thresholds.model_dump().values()
        ):
            raise ValueError("At least one quality threshold must be configured.")
        return self


class RankingObservation(StrictModel):
    key: EvalKey
    ranked_ids: list[EvalKey] = Field(max_length=200)
    provenance_failures: int = Field(default=0, strict=True, ge=0, le=200)

    @field_validator("ranked_ids")
    @classmethod
    def unique_results(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Retrieved candidate identifiers must be unique.")
        return values


class ObservedCriterion(StrictModel):
    key: EvalKey
    found: bool = Field(strict=True)
    provenance_valid: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def require_provenance_result(self) -> Self:
        if (self.found and self.provenance_valid is None) or (
            not self.found and self.provenance_valid is not None
        ):
            raise ValueError(
                "Provenance validation is required only for found evidence."
            )
        return self


class EvidenceObservation(StrictModel):
    key: EvalKey
    profile_revision: int = Field(strict=True, ge=1)
    source_status: SourceStatus
    criteria: list[ObservedCriterion] = Field(min_length=1, max_length=10)

    @field_validator("criteria")
    @classmethod
    def unique_criteria(cls, values):
        if len({item.key for item in values}) != len(values):
            raise ValueError("Observed criterion keys must be unique.")
        return values


class ChunkPolicy(StrictModel):
    chunker_version: EvalKey
    max_chars: int = Field(strict=True, ge=1, le=100000)
    overlap_chars: int = Field(strict=True, ge=0, le=100000)

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.overlap_chars >= self.max_chars:
            raise ValueError("Chunk overlap must be smaller than the window.")
        return self


class EvaluationObservations(StrictModel):
    suite_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    source_kind: SourceKind
    search_version: EvalKey
    retrieval_version: EvalKey
    matching_version: EvalKey
    chunk_policies: list[ChunkPolicy] = Field(min_length=1, max_length=20)
    ranking: list[RankingObservation] = Field(default_factory=list, max_length=100)
    evidence: list[EvidenceObservation] = Field(default_factory=list, max_length=100)

    @field_validator("chunk_policies")
    @classmethod
    def unique_policies(cls, values):
        keys = [
            (item.chunker_version, item.max_chars, item.overlap_chars)
            for item in values
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Observed chunk policies must be unique.")
        return values

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        keys = [case.key for case in self.ranking] + [
            case.key for case in self.evidence
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Observed case keys must be unique.")
        return self


class RankingResult(StrictModel):
    key: EvalKey
    k: int
    retrieved_count: int
    returned_at_k: int
    relevant_count: int
    hits_at_k: int
    unjudged_count: int
    provenance_failures: int
    precision_at_k: Rate
    recall_at_k: Rate | None
    ndcg_at_k: Rate | None
    reciprocal_rank_at_k: Rate | None


class EvidenceResult(StrictModel):
    key: EvalKey
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    provenance_failures: int
    source_status_matches: bool


class AggregateQuality(StrictModel):
    ranking_cases: int
    empty_ranking_cases: int
    mean_precision_at_k: Rate | None
    mean_recall_at_k: Rate | None
    mean_ndcg_at_k: Rate | None
    mean_reciprocal_rank_at_k: Rate | None
    evidence_checks: int
    evidence_precision: Rate | None
    evidence_recall: Rate | None
    evidence_accuracy: Rate | None


class GateFailure(StrictModel):
    scope: EvalKey
    code: Literal[
        "UNJUDGED_RESULT",
        "FORBIDDEN_RESULT",
        "EXPECTED_EMPTY",
        "INVALID_PROVENANCE",
        "SOURCE_STATUS_CHANGED",
        "BELOW_THRESHOLD",
        "UNDEFINED_METRIC",
    ]
    metric: EvalKey | None = None
    actual: Rate | None = None
    minimum: Rate | None = None


class EvaluationReport(StrictModel):
    protocol_version: Literal["retrieval-quality-v1"] = "retrieval-quality-v1"
    suite_id: EvalKey
    suite_sha256: str
    corpus_sha256: str
    label_kind: Literal["synthetic_reference", "reviewed_reference"]
    source_kind: SourceKind
    search_version: EvalKey
    retrieval_version: EvalKey
    matching_version: EvalKey
    chunk_policies: list[ChunkPolicy]
    evaluated_at: datetime
    ranking: list[RankingResult]
    evidence: list[EvidenceResult]
    aggregate: AggregateQuality
    failures: list[GateFailure]
    gate_passed: bool
