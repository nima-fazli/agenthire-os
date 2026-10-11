"""Create private, tenant-scoped candidate document metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0009_create_candidate_documents"
down_revision = "0008_add_application_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidates_organization_id_id", "candidates", ["organization_id", "id"]
    )
    op.create_table(
        "candidate_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), server_default="ready", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_candidate_documents"),
        sa.ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            name="fk_candidate_documents_organization_id_candidate_id_candidates",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_candidate_documents_uploaded_by_user_id_users",
        ),
        sa.UniqueConstraint("storage_key", name="uq_candidate_documents_storage_key"),
        sa.UniqueConstraint(
            "organization_id",
            "candidate_id",
            "sha256",
            name="uq_candidate_documents_content",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name=op.f("ck_candidate_documents_size_bytes")
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name=op.f("ck_candidate_documents_sha256")
        ),
        sa.CheckConstraint(
            "content_type = 'application/pdf'",
            name=op.f("ck_candidate_documents_content_type"),
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'deleting')",
            name=op.f("ck_candidate_documents_status"),
        ),
    )
    op.create_index(
        "ix_candidate_documents_candidate",
        "candidate_documents",
        ["organization_id", "candidate_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_documents_candidate", table_name="candidate_documents")
    op.drop_table("candidate_documents")
    op.drop_constraint("uq_candidates_organization_id_id", "candidates", type_="unique")
