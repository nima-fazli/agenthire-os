"""Audit Application ownership, then enforce both tenant relationships."""

from alembic import op

revision = "0015_application_tenant_fks"
down_revision = "0014_create_job_match_profiles"
branch_labels = None
depends_on = None

AUDIT_SQL = """
DO $audit$
DECLARE mismatches bigint;
BEGIN
    SELECT count(*) INTO mismatches
    FROM applications a
    LEFT JOIN jobs j ON j.id = a.job_id
    LEFT JOIN candidates c ON c.id = a.candidate_id
    WHERE a.organization_id IS DISTINCT FROM j.organization_id
       OR a.organization_id IS DISTINCT FROM c.organization_id;
    IF mismatches > 0 THEN
        RAISE EXCEPTION 'Application tenant audit failed (% rows). Review ownership before retrying.', mismatches
            USING ERRCODE = '23514';
    END IF;
END
$audit$;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Prevent writes between the audit and validated constraint installation.
    op.execute("LOCK TABLE jobs, candidates, applications IN SHARE ROW EXCLUSIVE MODE")
    op.execute(AUDIT_SQL)
    op.create_unique_constraint(
        "uq_jobs_organization_id_id", "jobs", ["organization_id", "id"]
    )
    op.create_foreign_key(
        "fk_applications_organization_id_job_id_jobs",
        "applications",
        "jobs",
        ["organization_id", "job_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_applications_organization_id_candidate_id_candidates",
        "applications",
        "candidates",
        ["organization_id", "candidate_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_applications_organization_id_candidate_id_candidates",
        "applications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_applications_organization_id_job_id_jobs",
        "applications",
        type_="foreignkey",
    )
    op.drop_constraint("uq_jobs_organization_id_id", "jobs", type_="unique")
