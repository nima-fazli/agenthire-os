"""Separate applicant identities and durable, organization-scoped agent runs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CareerPublication(Base):
    __tablename__ = "career_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"]
        ),
    )
    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    public_description: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicantIdentity(Base):
    __tablename__ = "applicant_identities"
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    challenge_hash: Mapped[str | None] = mapped_column(String(64))
    challenge_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ApplicantSubmission(Base):
    __tablename__ = "applicant_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_applicant_user_job"),
        UniqueConstraint("organization_id", "id", name="uq_applicant_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
        ),
        CheckConstraint("state IN ('draft','submitted')", name="submission_state"),
        CheckConstraint(
            "(state='draft' AND candidate_id IS NULL AND application_id IS NULL) OR (state='submitted' AND candidate_id IS NOT NULL AND application_id IS NOT NULL)",
            name="submission_link",
        ),
        Index("ix_applicant_user_created", "user_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    candidate_id: Mapped[UUID | None] = mapped_column(Uuid)
    application_id: Mapped[UUID | None] = mapped_column(Uuid)
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("candidate_documents.id")
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    pdf_filename: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    public_question: Mapped[str | None] = mapped_column(Text)
    question_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicantAnswer(Base):
    __tablename__ = "applicant_answers"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "question_revision", name="uq_answer_revision"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applicant_submissions.id"), nullable=False
    )
    question_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "submission_id"],
            ["applicant_submissions.organization_id", "applicant_submissions.id"],
        ),
        CheckConstraint("kind IN ('recruiter','applicant')", name="agent_kind"),
        CheckConstraint("mode IN ('live','replay')", name="agent_mode"),
        CheckConstraint(
            "status IN ('queued','running','waiting_approval','completed','failed','cancelled')",
            name="agent_status",
        ),
        CheckConstraint("steps>=0 AND attempts>=0", name="agent_counters"),
        Index("ix_agent_queue", "status", "lease_expires_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    checkpoint: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report: Mapped[dict | None] = mapped_column(JSON)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_event_sequence"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentNotification(Base):
    __tablename__ = "agent_notifications"
    __table_args__ = (Index("ix_agent_notice_user", "user_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentOutbox(Base):
    __tablename__ = "agent_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_agent_outbox_dedupe"),
        CheckConstraint(
            "status IN ('pending','sending','sent','failed')", name="mail_status"
        ),
        Index("ix_agent_mail_queue", "status", "lease_expires_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
