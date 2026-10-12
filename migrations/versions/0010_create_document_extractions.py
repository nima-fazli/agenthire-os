"""Create durable PDF extraction jobs and results."""

import sqlalchemy as sa
from alembic import op

revision = "0010_create_document_extractions"
down_revision = "0009_create_candidate_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_document_extractions"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["candidate_documents.id"],
            name="fk_document_extractions_document_id_candidate_documents",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_document_extractions_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_document_extractions_attempts")
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name=op.f("ck_document_extractions_page_count"),
        ),
        sa.CheckConstraint(
            "(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_document_extractions_lease"),
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (text IS NOT NULL AND length(text) > 0 AND page_count IS NOT NULL AND "
            "failure_code IS NULL AND completed_at IS NOT NULL)",
            name=op.f("ck_document_extractions_success"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR (failure_code IS NOT NULL AND completed_at IS NOT NULL AND text IS NULL)",
            name=op.f("ck_document_extractions_failure"),
        ),
    )
    op.create_index(
        "ix_document_extractions_queue",
        "document_extractions",
        ["status", "lease_expires_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_extractions_queue", table_name="document_extractions")
    op.drop_table("document_extractions")
