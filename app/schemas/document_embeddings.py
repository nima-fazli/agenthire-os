from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retry: bool = Field(default=False, strict=True)


class EmbeddingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    chunk_set_id: UUID
    model_tag: Literal["qwen3-embedding:0.6b"]
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoding_version: Literal["qwen3-raw-l2-v1"]
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(ge=1, le=1000)
    dimensions: Literal[1024] = 1024
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int = Field(ge=0)
    failure_code: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
