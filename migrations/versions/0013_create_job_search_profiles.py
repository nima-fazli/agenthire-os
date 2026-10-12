"""Add explicit versioned search profiles for job candidate retrieval."""

import sqlalchemy as sa
from alembic import op

revision = "0013_create_job_search_profiles"
down_revision = "0012_add_document_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_search_profiles",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.String(256), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(query_text)) BETWEEN 1 AND 256",
            name=op.f("ck_job_search_profiles_query_text"),
        ),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_job_search_profiles_revision")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_search_profiles_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_job_search_profiles_updated_by_user_id_users",
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_job_search_profiles"),
    )


def downgrade() -> None:
    op.drop_table("job_search_profiles")
