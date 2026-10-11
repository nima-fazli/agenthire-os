from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            name="fk_candidate_documents_organization_id_candidate_id_candidates",
        ),
        UniqueConstraint("storage_key", name="uq_candidate_documents_storage_key"),
        UniqueConstraint(
            "organization_id",
            "candidate_id",
            "sha256",
            name="uq_candidate_documents_content",
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes"),
        CheckConstraint("length(sha256) = 64", name="sha256"),
        CheckConstraint("content_type = 'application/pdf'", name="content_type"),
        CheckConstraint("status IN ('ready', 'deleting')", name="status"),
        Index(
            "ix_candidate_documents_candidate",
            "organization_id",
            "candidate_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ready"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
