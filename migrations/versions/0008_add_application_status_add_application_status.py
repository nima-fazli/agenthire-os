"""add application status

Revision ID: 0008_add_application_status
Revises: 0007_create_applications
Create Date: 2026-10-07 00:41:35.492671
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_application_status"
down_revision: str | None = "0007_create_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "applications",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="applied",
            nullable=False,
        ),
    )

    op.create_check_constraint(
        op.f("ck_applications_status"),
        "applications",
        (
            "status IN ("
            "'applied', "
            "'screening', "
            "'interview', "
            "'offer', "
            "'hired', "
            "'rejected'"
            ")"
        ),
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_constraint(
        op.f("ck_applications_status"),
        "applications",
        type_="check",
    )

    op.drop_column(
        "applications",
        "status",
    )
