from sqlalchemy import UniqueConstraint

from app.models.application import Application


def test_application_table_name() -> None:
    assert Application.__tablename__ == "applications"


def test_application_has_expected_columns() -> None:
    assert set(
        Application.__table__.columns.keys()
    ) == {
        "id",
        "organization_id",
        "job_id",
        "candidate_id",
        "created_at",
        "updated_at",
    }


def test_application_id_is_primary_key() -> None:
    primary_key_columns = {
        column.name
        for column in Application.__table__.primary_key.columns
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
        "candidates.id",
    }


def test_application_tenant_fields_are_required() -> None:
    assert (
        Application.__table__.c.organization_id.nullable
        is False
    )
    assert (
        Application.__table__.c.job_id.nullable
        is False
    )
    assert (
        Application.__table__.c.candidate_id.nullable
        is False
    )


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
        if constraint.name
        == "uq_applications_job_id_candidate_id"
    )

    assert {
        column.name
        for column in constraint.columns
    } == {
        "job_id",
        "candidate_id",
    }


def test_application_has_expected_indexes() -> None:
    index_names = {
        index.name
        for index in Application.__table__.indexes
    }

    assert index_names == {
        "ix_applications_organization_id",
        "ix_applications_job_id",
        "ix_applications_candidate_id",
    }
