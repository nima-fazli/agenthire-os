"""create applications table

Revision ID: 0007_create_applications
Revises: 0006_create_candidates
Create Date: 2026-10-07 00:02:18.737137
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_create_applications"
down_revision: str | None = "0006_create_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "applications",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f(
                "fk_applications_candidate_id_candidates"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f(
                "fk_applications_job_id_jobs"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(
                "fk_applications_organization_id_organizations"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_applications"),
        ),
        sa.UniqueConstraint(
            "job_id",
            "candidate_id",
            name="uq_applications_job_id_candidate_id",
        ),
    )

    op.create_index(
        "ix_applications_candidate_id",
        "applications",
        ["candidate_id"],
        unique=False,
    )

    op.create_index(
        "ix_applications_job_id",
        "applications",
        ["job_id"],
        unique=False,
    )

    op.create_index(
        "ix_applications_organization_id",
        "applications",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index(
        "ix_applications_organization_id",
        table_name="applications",
    )

    op.drop_index(
        "ix_applications_job_id",
        table_name="applications",
    )

    op.drop_index(
        "ix_applications_candidate_id",
        table_name="applications",
    )

    op.drop_table(
        "applications"
    )
