from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
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


class JobUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=20_000,
    )
    status: JobStatus | None = None

    @model_validator(
        mode="before"
    )
    @classmethod
    def reject_explicit_nulls(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, dict):
            for field_name in (
                "title",
                "description",
                "status",
            ):
                if (
                    field_name in value
                    and value[field_name] is None
                ):
                    raise ValueError(
                        "Job update fields cannot be null."
                    )

        return value

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

    @model_validator(
        mode="after"
    )
    def require_changes(
        self,
    ) -> Self:
        if not self.model_fields_set:
            raise ValueError(
                "At least one job field must be provided."
            )

        return self


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
