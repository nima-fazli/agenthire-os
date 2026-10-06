from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
