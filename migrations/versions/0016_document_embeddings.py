"""Versioned local embedding jobs and source-bound pgvector rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType

revision = "0016_document_embeddings"
down_revision = "0015_application_tenant_fks"
branch_labels = None
depends_on = None


class Vector1024(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "vector(1024)"


def upgrade() -> None:
    op.create_table(
        "document_embedding_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_set_id", sa.Uuid(), nullable=False),
        sa.Column("model_tag", sa.String(64), nullable=False),
        sa.Column("model_digest", sa.String(64), nullable=False),
        sa.Column("encoding_version", sa.String(32), nullable=False),
        sa.Column("source_text_sha256", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_document_embedding_jobs"),
        sa.ForeignKeyConstraint(["chunk_set_id"], ["document_chunk_sets.id"], ondelete="CASCADE", name="fk_document_embedding_jobs_chunk_set_id_document_chunk_sets"),
        sa.UniqueConstraint("chunk_set_id", "model_digest", "encoding_version", name="uq_embedding_jobs_source_model"),
        sa.UniqueConstraint("id", "chunk_set_id", name="uq_embedding_jobs_id_source"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed')", name=op.f("ck_document_embedding_jobs_status")),
        sa.CheckConstraint("attempts >= 0 AND chunk_count BETWEEN 1 AND 1000", name=op.f("ck_document_embedding_jobs_bounds")),
        sa.CheckConstraint("model_tag = 'qwen3-embedding:0.6b' AND encoding_version = 'qwen3-raw-l2-v1'", name=op.f("ck_document_embedding_jobs_space")),
        sa.CheckConstraint("model_digest ~ '^[0-9a-f]{64}$' AND source_text_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_embedding_jobs_digests")),
        sa.CheckConstraint("(status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)", name=op.f("ck_document_embedding_jobs_lease")),
        sa.CheckConstraint("status = 'running' OR (lease_token IS NULL AND lease_expires_at IS NULL)", name=op.f("ck_document_embedding_jobs_idle_lease")),
        sa.CheckConstraint("status <> 'succeeded' OR (completed_at IS NOT NULL AND failure_code IS NULL)", name=op.f("ck_document_embedding_jobs_success")),
        sa.CheckConstraint("status <> 'failed' OR (completed_at IS NOT NULL AND failure_code IS NOT NULL)", name=op.f("ck_document_embedding_jobs_failure")),
    )
    op.create_index("ix_embedding_jobs_queue", "document_embedding_jobs", ["status", "lease_expires_at", "created_at"])
    op.create_table(
        "document_embeddings",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("chunk_set_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_sha256", sa.String(64), nullable=False),
        sa.Column("embedding", Vector1024(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", "position", name="pk_document_embeddings"),
        sa.ForeignKeyConstraint(["job_id", "chunk_set_id"], ["document_embedding_jobs.id", "document_embedding_jobs.chunk_set_id"], ondelete="CASCADE", name="fk_document_embeddings_job_source"),
        sa.ForeignKeyConstraint(["chunk_set_id", "position"], ["document_chunks.chunk_set_id", "document_chunks.position"], ondelete="CASCADE", name="fk_document_embeddings_chunk"),
        sa.CheckConstraint("position >= 0", name=op.f("ck_document_embeddings_position")),
        sa.CheckConstraint("chunk_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_embeddings_digest")),
        sa.CheckConstraint("vector_dims(embedding) = 1024 AND vector_norm(embedding) BETWEEN 0.999 AND 1.001", name=op.f("ck_document_embeddings_vector")),
    )


def downgrade() -> None:
    op.drop_table("document_embeddings")
    op.drop_index("ix_embedding_jobs_queue", table_name="document_embedding_jobs")
    op.drop_table("document_embedding_jobs")
