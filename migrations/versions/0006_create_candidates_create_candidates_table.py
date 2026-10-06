"""create candidates table

Revision ID: 0006_create_candidates
Revises: 0005_create_jobs
Create Date: 2026-10-06 23:04:31.401932
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_create_candidates"
down_revision: str | None = "0005_create_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "candidates",
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
            "full_name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "email",
            sa.String(length=320),
            nullable=True,
        ),
        sa.Column(
            "phone",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            "location",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "headline",
            sa.String(length=300),
            nullable=True,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=True,
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
            ["organization_id"],
            ["organizations.id"],
            name=op.f(
                "fk_candidates_organization_id_organizations"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_candidates"),
        ),
    )

    op.create_index(
        "ix_candidates_organization_id",
        "candidates",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index(
        "ix_candidates_organization_id",
        table_name="candidates",
    )

    op.drop_table(
        "candidates"
    )
