from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"


class ApplicationCreate(BaseModel):
    job_id: UUID
    candidate_id: UUID


class ApplicationRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    organization_id: UUID
    job_id: UUID
    candidate_id: UUID
    created_at: datetime
    updated_at: datetime
