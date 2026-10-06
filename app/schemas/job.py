from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

JobStatus = Literal[
    "draft",
    "open",
    "closed",
]


class JobCreate(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
    )
    description: str = Field(
        min_length=1,
        max_length=20_000,
    )
    status: JobStatus = "draft"

    @field_validator(
        "title",
        "description",
        mode="before",
    )
    @classmethod
    def normalize_text(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, str):
            return value.strip()

        return value


class JobRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    organization_id: UUID
    title: str
    description: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
