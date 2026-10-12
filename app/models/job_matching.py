from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobMatchProfile(Base):
    __tablename__ = "job_match_profiles"
    __table_args__ = (CheckConstraint("revision > 0", name="revision"),)

    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    updated_by_user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
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


class JobMatchCriterion(Base):
    __tablename__ = "job_match_criteria"
    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 9", name="position"),
        CheckConstraint("length(trim(key)) BETWEEN 1 AND 40", name="key"),
        CheckConstraint("length(trim(label)) BETWEEN 1 AND 100", name="label"),
        CheckConstraint(
            "length(trim(query_text)) BETWEEN 1 AND 256", name="query_text"
        ),
        CheckConstraint("importance IN ('required', 'preferred')", name="importance"),
        UniqueConstraint("job_id", "key", name="uq_job_match_criteria_job_key"),
    )

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("job_match_profiles.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    query_text: Mapped[str] = mapped_column(String(256), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
