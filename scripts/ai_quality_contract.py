"""Versioned reference and observation contracts; reports exclude text and bearer tokens."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.evaluation_report import read_json

REFERENCE = Path(__file__).with_name("fixtures") / "ai_quality_v1.json"
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Number = Annotated[float, Field(ge=0, allow_inf_nan=False)]
MODES = ("lexical", "semantic", "hybrid")
REPETITIONS = 2


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Resume(Strict):
    key: Key
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1000)


class Query(Strict):
    key: Key
    language: Literal["en", "fa"]
    q: str = Field(min_length=1, max_length=256)
    grades: dict[Key, Annotated[int, Field(ge=0, le=3)]]


class Brief(Strict):
    key: Key
    language: Literal["en", "fa"]
    q: str = Field(min_length=1, max_length=256)
    kind: Literal["quote", "attack", "no_evidence", "oversized"]
    prefix: str = Field(default="", max_length=200)
    context: str | None = Field(default=None, min_length=1, max_length=4000)
    anchor: str | None = Field(default=None, min_length=1, max_length=400)

    @model_validator(mode="after")
    def consistent(self):
        if self.kind != "no_evidence" and (not self.context or not self.anchor or self.anchor not in self.context):
            raise ValueError("missing_reference_anchor")
        if self.context is None and self.prefix:
            raise ValueError("prefix_without_source")
        return self


class Reference(Strict):
    version: Literal["ai-quality-reference-v1"]
    resumes: list[Resume] = Field(min_length=12, max_length=12)
    queries: list[Query] = Field(min_length=8, max_length=8)
    briefs: list[Brief] = Field(min_length=12, max_length=12)
    identity_pair: list[Key] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def complete(self):
        keys = {item.key for item in self.resumes}
        for items in (self.resumes, self.queries, self.briefs):
            if len({item.key for item in items}) != len(items):
                raise ValueError("duplicate_reference_key")
        for query in self.queries:
            if set(query.grades) != keys or max(query.grades.values()) != 3:
                raise ValueError("incomplete_graded_judgments")
        pair = [item for item in self.resumes if item.key in self.identity_pair]
        if (len(pair) != 2 or pair[0].text != pair[1].text or pair[0].name == pair[1].name
                or any(q.grades[pair[0].key] != q.grades[pair[1].key] for q in self.queries)):
            raise ValueError("invalid_identity_counterfactual")
        if {q.language for q in self.queries} != {"en", "fa"}:
            raise ValueError("bilingual_reference_required")
        return self


class Observation(Strict):
    family: Literal["ranking", "brief"]
    case: Key
    mode: Literal["lexical", "semantic", "hybrid", "brief"]
    repetition: int = Field(ge=1, le=REPETITIONS)
    valid: bool
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    ranking: list[Key] = Field(default_factory=list, max_length=12)
    scores: list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]] = Field(default_factory=list, max_length=12)
    elapsed_ms: Number
    model_digest: Digest | None = None
    input_tokens: int = Field(default=0, ge=0, le=8192)
    output_tokens: int = Field(default=0, ge=0, le=1024)


def load_reference(path=REFERENCE):
    return Reference.model_validate(read_json(Path(path)))


def reference_digest(reference):
    # JSON layout and a UTF-8 BOM do not change the reference identity.
    data = json.dumps(reference.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()
