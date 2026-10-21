from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PublicationInput(StrictInput):
    published: bool
    public_description: str = Field(min_length=20, max_length=12000)


class DraftInput(StrictInput):
    job_id: UUID
    full_name: str = Field(min_length=2, max_length=200)
    resume_text: str = Field(default="", max_length=20000)


class VerifyInput(StrictInput):
    code: str = Field(pattern=r"^[0-9]{6}$")


class RunInput(StrictInput):
    mode: Literal["replay", "live"] = "replay"
    goal: str = Field(
        default="Review every saved criterion using source evidence. Clarify only unclear experience.",
        min_length=5,
        max_length=2000,
    )


class ApplicantQuestionInput(RunInput):
    goal: str = Field(min_length=3, max_length=1500)


class ApprovalInput(StrictInput):
    decision: Literal["approve", "dismiss"]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnswerInput(StrictInput):
    question_revision: int = Field(ge=1)
    text: str = Field(min_length=5, max_length=10000)
    mode: Literal["replay", "live"] = "replay"


class ActionFinding(StrictInput):
    assessment: Literal["supported", "unclear"]
    evidence_ids: list[str] = Field(max_length=3)


class ReviewAction(StrictInput):
    findings: dict[str, ActionFinding] = Field(min_length=1, max_length=10)
