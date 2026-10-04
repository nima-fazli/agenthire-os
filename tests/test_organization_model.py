from sqlalchemy import UniqueConstraint

from app.models.organization import Organization


def test_organization_uses_expected_table_name() -> None:
    assert Organization.__tablename__ == "organizations"


def test_organization_has_expected_columns() -> None:
    column_names = set(Organization.__table__.columns.keys())

    assert column_names == {
        "id",
        "name",
        "slug",
        "created_at",
        "updated_at",
    }


def test_organization_slug_is_unique() -> None:
    unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in Organization.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("slug",) in unique_constraints


def test_organization_id_is_primary_key() -> None:
    primary_key_columns = {
        column.name
        for column in Organization.__table__.primary_key.columns
    }

    assert primary_key_columns == {"id"}
