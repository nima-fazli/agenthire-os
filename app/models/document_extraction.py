from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status"
        ),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count"),
        CheckConstraint(
            "(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="lease",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR (text IS NOT NULL AND length(text) > 0 AND page_count IS NOT NULL AND "
            "failure_code IS NULL AND completed_at IS NOT NULL)",
            name="success",
        ),
        CheckConstraint(
            "status <> 'failed' OR (failure_code IS NOT NULL AND completed_at IS NOT NULL AND text IS NULL)",
            name="failure",
        ),
        Index(
            "ix_document_extractions_queue", "status", "lease_expires_at", "created_at"
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("candidate_documents.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
