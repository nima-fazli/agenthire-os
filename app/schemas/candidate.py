from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class CandidateCreate(BaseModel):
    full_name: str = Field(
        min_length=1,
        max_length=200,
    )

    email: str | None = Field(
        default=None,
        min_length=1,
        max_length=320,
    )

    phone: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    location: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    headline: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
    )

    summary: str | None = Field(
        default=None,
        min_length=1,
        max_length=20_000,
    )

    @field_validator(
        "full_name",
        "email",
        "phone",
        "location",
        "headline",
        "summary",
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

    @field_validator(
        "email",
    )
    @classmethod
    def normalize_email(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return value.lower()


class CandidateRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    organization_id: UUID
    full_name: str
    email: str | None
    phone: str | None
    location: str | None
    headline: str | None
    summary: str | None
    created_at: datetime
    updated_at: datetime
