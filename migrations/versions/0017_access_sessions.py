"""Revocable sessions, organization roles, private invitations and access history."""

import sqlalchemy as sa
from alembic import op

revision = "0017_access_sessions"
down_revision = "0016_document_embeddings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organization_memberships", sa.Column("role", sa.String(16), nullable=False, server_default="recruiter"))
    # Existing organizations have no owner column. Prefer their earliest active member.
    op.execute("""
        WITH ranked AS (
            SELECT m.id, row_number() OVER (
                PARTITION BY m.organization_id ORDER BY u.is_active DESC, m.created_at, m.id
            ) AS position FROM organization_memberships m JOIN users u ON u.id = m.user_id
        ) UPDATE organization_memberships m SET role = 'owner'
          FROM ranked r WHERE m.id = r.id AND r.position = 1
    """)
    op.create_check_constraint(op.f("ck_organization_memberships_role"), "organization_memberships", "role IN ('owner','recruiter','viewer')")
    op.create_table("user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_user_sessions_expiry")))
    op.create_index("ix_user_sessions_user_expiry", "user_sessions", ["user_id", "expires_at"])
    op.create_table("login_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name=op.f("ck_login_throttles_attempts")))
    op.create_index("ix_login_throttles_expires_at", "login_throttles", ["expires_at"])
    op.create_table("organization_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('recruiter','viewer')", name=op.f("ck_organization_invitations_role")))
    op.create_index("ix_organization_invitations_scope_expiry", "organization_invitations", ["organization_id", "expires_at"])
    op.create_table("access_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("previous_role", sa.String(16)),
        sa.Column("new_role", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_access_events_scope_created", "access_events", ["organization_id", "created_at"])


def downgrade():
    op.drop_table("access_events")
    op.drop_table("organization_invitations")
    op.drop_table("login_throttles")
    op.drop_table("user_sessions")
    op.drop_constraint(op.f("ck_organization_memberships_role"), "organization_memberships", type_="check")
    op.drop_column("organization_memberships", "role")
