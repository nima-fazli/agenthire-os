import importlib.util
import io
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models import Application, Candidate, Job, Organization


def test_application_table_name() -> None:
    assert Application.__tablename__ == "applications"


def test_application_has_expected_columns() -> None:
    assert set(Application.__table__.columns.keys()) == {
        "id",
        "organization_id",
        "job_id",
        "candidate_id",
        "status",
        "created_at",
        "updated_at",
    }


def test_application_id_is_primary_key() -> None:
    primary_key_columns = {
        column.name for column in Application.__table__.primary_key.columns
    }

    assert primary_key_columns == {
        "id",
    }


def test_application_foreign_keys() -> None:
    foreign_key_targets = {
        foreign_key.target_fullname
        for foreign_key in Application.__table__.foreign_keys
    }

    assert foreign_key_targets == {
        "organizations.id",
        "jobs.id",
        "jobs.organization_id",
        "candidates.id",
        "candidates.organization_id",
    }


def test_application_tenant_fields_are_required() -> None:
    assert Application.__table__.c.organization_id.nullable is False
    assert Application.__table__.c.job_id.nullable is False
    assert Application.__table__.c.candidate_id.nullable is False


def test_application_status_defaults_to_applied() -> None:
    status_column = Application.__table__.c.status

    assert status_column.nullable is False
    assert status_column.default is not None
    assert status_column.default.arg == "applied"

    assert status_column.server_default is not None
    assert status_column.server_default.arg == "applied"


def test_application_status_has_database_check_constraint() -> None:
    check_constraints = [
        constraint
        for constraint in Application.__table__.constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    ]

    constraint = next(
        constraint
        for constraint in check_constraints
        if constraint.name == "ck_applications_status"
    )

    expression = str(constraint.sqltext)

    for status in (
        "applied",
        "screening",
        "interview",
        "offer",
        "hired",
        "rejected",
    ):
        assert status in expression


def test_application_candidate_job_pair_is_unique() -> None:
    unique_constraints = [
        constraint
        for constraint in Application.__table__.constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    ]

    constraint = next(
        constraint
        for constraint in unique_constraints
        if constraint.name == "uq_applications_job_id_candidate_id"
    )

    assert {column.name for column in constraint.columns} == {
        "job_id",
        "candidate_id",
    }


def test_application_has_expected_indexes() -> None:
    index_names = {index.name for index in Application.__table__.indexes}

    assert index_names == {
        "ix_applications_organization_id",
        "ix_applications_job_id",
        "ix_applications_candidate_id",
    }


def migration():
    path = (
        Path(__file__).parents[1] / "migrations/versions/0015_application_tenant_fks.py"
    )
    spec = importlib.util.spec_from_file_location("application_tenant_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(action):
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration(), action)()
    return output.getvalue()


def test_migration_audits_under_lock_before_validated_constraints():
    module = migration()
    assert module.down_revision == "0014_create_job_match_profiles"
    assert len(module.revision) <= 32
    sql = render("upgrade")
    assert (
        sql.index("LOCK TABLE") < sql.index("DO $audit$") < sql.index("ADD CONSTRAINT")
    )
    assert "IS DISTINCT FROM j.organization_id" in sql
    assert "IS DISTINCT FROM c.organization_id" in sql
    assert "23514" in sql and "RAISE EXCEPTION" in sql
    assert "FOREIGN KEY(organization_id, job_id)" in sql
    assert "FOREIGN KEY(organization_id, candidate_id)" in sql
    assert "NOT VALID" not in sql
    assert "DELETE FROM" not in sql and "UPDATE applications" not in sql


def test_downgrade_keeps_data_and_historical_constraints():
    sql = render("downgrade")
    assert sql.index("DROP CONSTRAINT fk_applications") < sql.index(
        "uq_jobs_organization_id_id"
    )
    assert "DROP TABLE" not in sql and "DELETE" not in sql
    assert "fk_applications_job_id_jobs" not in sql
    assert "uq_candidates_organization_id_id" not in sql


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    orgs, jobs, candidates = [[uuid4(), uuid4()] for _ in range(3)]
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            Job.__table__,
            Candidate.__table__,
            Application.__table__,
        ],
    )
    with engine.begin() as connection:
        for position in range(2):
            connection.execute(
                insert(Organization),
                {
                    "id": orgs[position],
                    "name": "Tenant",
                    "slug": f"tenant-{position}",
                },
            )
            connection.execute(
                insert(Job),
                {
                    "id": jobs[position],
                    "organization_id": orgs[position],
                    "title": "Engineer",
                    "description": "Build systems",
                },
            )
            connection.execute(
                insert(Candidate),
                {
                    "id": candidates[position],
                    "organization_id": orgs[position],
                    "full_name": "Synthetic candidate",
                },
            )
    yield engine, orgs, jobs, candidates
    engine.dispose()


@pytest.mark.parametrize(
    "job,candidate", [(1, 0), (0, 1), (1, 1)], ids=["job", "candidate", "both"]
)
def test_database_rejects_cross_tenant_insert(database, job, candidate):
    engine, orgs, jobs, candidates = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(Application),
            {
                "organization_id": orgs[0],
                "job_id": jobs[job],
                "candidate_id": candidates[candidate],
            },
        )


@pytest.mark.parametrize("field", ["organization_id", "job_id", "candidate_id"])
def test_database_rejects_cross_tenant_application_update(database, field):
    engine, orgs, jobs, candidates = database
    app = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(Application),
            {
                "id": app,
                "organization_id": orgs[0],
                "job_id": jobs[0],
                "candidate_id": candidates[0],
            },
        )
    other = {
        "organization_id": orgs[1],
        "job_id": jobs[1],
        "candidate_id": candidates[1],
    }[field]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            update(Application).where(Application.id == app).values({field: other})
        )
    with engine.connect() as connection:
        assert connection.execute(select(Application.status)).scalar_one() == "applied"


@pytest.mark.parametrize("parent", [Job, Candidate], ids=["job", "candidate"])
def test_referenced_parent_cannot_move_to_another_tenant(database, parent):
    engine, orgs, jobs, candidates = database
    with engine.begin() as connection:
        connection.execute(
            insert(Application),
            {
                "organization_id": orgs[0],
                "job_id": jobs[0],
                "candidate_id": candidates[0],
            },
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            update(parent)
            .values(organization_id=orgs[1])
            .where(parent.id == (jobs[0] if parent is Job else candidates[0]))
        )
