from sqlalchemy import UniqueConstraint

from app.models.user import User


def test_user_table_name() -> None:
    assert User.__tablename__ == "users"


def test_user_has_expected_columns() -> None:
    column_names = {
        column.name
        for column in User.__table__.columns
    }

    assert column_names == {
        "id",
        "email",
        "password_hash",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_user_id_is_primary_key() -> None:
    assert User.__table__.c.id.primary_key is True


def test_user_email_has_unique_constraint() -> None:
    unique_constraints = [
        constraint
        for constraint in User.__table__.constraints
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

    assert ("email",) in unique_column_sets


def test_user_required_columns_are_not_nullable() -> None:
    assert User.__table__.c.email.nullable is False
    assert User.__table__.c.password_hash.nullable is False
    assert User.__table__.c.is_active.nullable is False
