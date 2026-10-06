from sqlalchemy import CheckConstraint

from app.models.job import Job


def test_job_table_name() -> None:
    assert Job.__tablename__ == "jobs"


def test_job_has_expected_columns() -> None:
    assert set(
        Job.__table__.columns.keys()
    ) == {
        "id",
        "organization_id",
        "title",
        "description",
        "status",
        "created_at",
        "updated_at",
    }


def test_job_id_is_primary_key() -> None:
    primary_key_columns = {
        column.name
        for column in Job.__table__.primary_key.columns
    }

    assert primary_key_columns == {
        "id",
    }


def test_job_organization_foreign_key() -> None:
    foreign_keys = list(
        Job.__table__.foreign_keys
    )

    assert len(foreign_keys) == 1

    assert (
        foreign_keys[0].target_fullname
        == "organizations.id"
    )


def test_job_has_organization_index() -> None:
    index_names = {
        index.name
        for index in Job.__table__.indexes
    }

    assert (
        "ix_jobs_organization_id"
        in index_names
    )


def test_job_status_has_check_constraint() -> None:
    check_constraints = {
        constraint.name
        for constraint in Job.__table__.constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }

    assert "ck_jobs_status" in check_constraints
