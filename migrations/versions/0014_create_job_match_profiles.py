"""Add bounded job criteria for independent resume evidence retrieval."""

import sqlalchemy as sa
from alembic import op

revision = "0014_create_job_match_profiles"
down_revision = "0013_create_job_search_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_match_profiles",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_job_match_profiles_revision")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_match_profiles_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_job_match_profiles_updated_by_user_id_users",
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_job_match_profiles"),
    )
    op.create_table(
        "job_match_criteria",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("query_text", sa.String(256), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 9", name=op.f("ck_job_match_criteria_position")
        ),
        sa.CheckConstraint(
            "length(trim(key)) BETWEEN 1 AND 40", name=op.f("ck_job_match_criteria_key")
        ),
        sa.CheckConstraint(
            "length(trim(label)) BETWEEN 1 AND 100",
            name=op.f("ck_job_match_criteria_label"),
        ),
        sa.CheckConstraint(
            "length(trim(query_text)) BETWEEN 1 AND 256",
            name=op.f("ck_job_match_criteria_query_text"),
        ),
        sa.CheckConstraint(
            "importance IN ('required', 'preferred')",
            name=op.f("ck_job_match_criteria_importance"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job_match_profiles.job_id"],
            name="fk_job_match_criteria_job_id_job_match_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "position", name="pk_job_match_criteria"),
        sa.UniqueConstraint("job_id", "key", name="uq_job_match_criteria_job_key"),
    )


def downgrade() -> None:
    op.drop_table("job_match_criteria")
    op.drop_table("job_match_profiles")
