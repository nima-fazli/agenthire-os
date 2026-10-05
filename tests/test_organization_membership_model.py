from sqlalchemy import UniqueConstraint

from app.models.organization_membership import (
    OrganizationMembership,
)


def test_organization_membership_table_name() -> None:
    assert (
        OrganizationMembership.__tablename__
        == "organization_memberships"
    )


def test_organization_membership_has_expected_columns() -> None:
    column_names = {
        column.name
        for column in OrganizationMembership.__table__.columns
    }

    assert column_names == {
        "id",
        "organization_id",
        "user_id",
        "created_at",
        "updated_at",
    }


def test_organization_membership_id_is_primary_key() -> None:
    assert (
        OrganizationMembership.__table__.c.id.primary_key
        is True
    )


def test_organization_membership_foreign_keys() -> None:
    organization_foreign_keys = (
        OrganizationMembership.__table__.c.organization_id.foreign_keys
    )
    user_foreign_keys = (
        OrganizationMembership.__table__.c.user_id.foreign_keys
    )

    assert {
        foreign_key.target_fullname
        for foreign_key in organization_foreign_keys
    } == {
        "organizations.id",
    }

    assert {
        foreign_key.target_fullname
        for foreign_key in user_foreign_keys
    } == {
        "users.id",
    }


def test_organization_membership_is_unique_per_user_and_organization() -> None:
    unique_constraints = [
        constraint
        for constraint in OrganizationMembership.__table__.constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    ]

    unique_column_sets = {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in unique_constraints
    }

    assert (
        "organization_id",
        "user_id",
    ) in unique_column_sets


def test_organization_membership_required_columns_are_not_nullable() -> None:
    assert (
        OrganizationMembership.__table__.c.organization_id.nullable
        is False
    )
    assert (
        OrganizationMembership.__table__.c.user_id.nullable
        is False
    )
