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

from app.core.semantic_embeddings import EmbeddingVector
from app.db.base import Base


class DocumentEmbeddingJob(Base):
    __tablename__ = "document_embedding_jobs"
    __table_args__ = (
        UniqueConstraint("chunk_set_id", "model_digest", "encoding_version", name="uq_embedding_jobs_source_model"),
        UniqueConstraint("id", "chunk_set_id", name="uq_embedding_jobs_id_source"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="status"),
        CheckConstraint("attempts >= 0 AND chunk_count BETWEEN 1 AND 1000", name="bounds"),
        CheckConstraint("model_tag = 'qwen3-embedding:0.6b' AND encoding_version = 'qwen3-raw-l2-v1'", name="space"),
        CheckConstraint("model_digest ~ '^[0-9a-f]{64}$' AND source_text_sha256 ~ '^[0-9a-f]{64}$'", name="digests"),
        CheckConstraint("(status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)", name="lease"),
        CheckConstraint("status = 'running' OR (lease_token IS NULL AND lease_expires_at IS NULL)", name="idle_lease"),
        CheckConstraint("status <> 'succeeded' OR (completed_at IS NOT NULL AND failure_code IS NULL)", name="success"),
        CheckConstraint("status <> 'failed' OR (completed_at IS NOT NULL AND failure_code IS NOT NULL)", name="failure"),
        Index("ix_embedding_jobs_queue", "status", "lease_expires_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    chunk_set_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("document_chunk_sets.id", ondelete="CASCADE"), nullable=False)
    model_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    encoding_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "chunk_set_id"], ["document_embedding_jobs.id", "document_embedding_jobs.chunk_set_id"], ondelete="CASCADE", name="fk_document_embeddings_job_source"),
        ForeignKeyConstraint(["chunk_set_id", "position"], ["document_chunks.chunk_set_id", "document_chunks.position"], ondelete="CASCADE", name="fk_document_embeddings_chunk"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("chunk_sha256 ~ '^[0-9a-f]{64}$'", name="digest"),
        CheckConstraint("vector_dims(embedding) = 1024 AND vector_norm(embedding) BETWEEN 0.999 AND 1.001", name="vector"),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_set_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    chunk_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[tuple[float, ...]] = mapped_column(EmbeddingVector(1024), nullable=False)
