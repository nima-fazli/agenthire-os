from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.schemas.application import ApplicationRead, ApplicationStatus
from app.schemas.candidate import CandidateCreate
from app.schemas.job import JobCreate


class PageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=120, pattern=r"^[^\x00]*$")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("q")
    @classmethod
    def query_text(cls, value: str) -> str:
        return value.strip()


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=10_000)


class ApplicationItem(ApplicationRead):
    candidate_name: str
    job_title: str
    allowed_statuses: list[ApplicationStatus]


class JobEdit(JobCreate):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime


class CandidateEdit(CandidateCreate):
    expected_updated_at: AwareDatetime
