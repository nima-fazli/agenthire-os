"""create jobs table

Revision ID: 0005_create_jobs
Revises: 0004_create_memberships
Create Date: 2026-10-06 16:49:13.402781
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_create_jobs"
down_revision: str | None = "0004_create_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "jobs",
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
            "title",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="draft",
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
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'closed')",
            name=op.f("ck_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(
                "fk_jobs_organization_id_organizations"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_jobs"),
        ),
    )

    op.create_index(
        "ix_jobs_organization_id",
        "jobs",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index(
        "ix_jobs_organization_id",
        table_name="jobs",
    )

    op.drop_table(
        "jobs"
    )
