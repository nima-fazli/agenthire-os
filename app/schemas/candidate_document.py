import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=5, max_length=200)

    @field_validator("filename")
    @classmethod
    def require_pdf_filename(cls, value: str) -> str:
        value = value.strip()
        if (
            not value.lower().endswith(".pdf")
            or not value[:-4].strip()
            or any(character in value for character in "/\\")
            or any(
                unicodedata.category(character).startswith("C") for character in value
            )
        ):
            raise ValueError("Use a PDF filename without paths or control characters.")
        return value


class CandidateDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    candidate_id: UUID
    uploaded_by_user_id: UUID
    filename: str
    content_type: Literal["application/pdf"]
    size_bytes: int
    sha256: str
    status: Literal["ready"]
    created_at: datetime
    updated_at: datetime
