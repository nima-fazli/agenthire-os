from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retry: bool = Field(default=False, strict=True)


class ExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    page_count: int | None
    failure_code: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExtractionTextRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    text: str
    page_count: int
