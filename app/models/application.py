from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Application(Base):
    __tablename__ = "applications"

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "candidate_id",
            name="uq_applications_job_id_candidate_id",
        ),
        Index(
            "ix_applications_organization_id",
            "organization_id",
        ),
        Index(
            "ix_applications_job_id",
            "job_id",
        ),
        Index(
            "ix_applications_candidate_id",
            "candidate_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "organizations.id",
        ),
        nullable=False,
    )

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "jobs.id",
        ),
        nullable=False,
    )

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "candidates.id",
        ),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
