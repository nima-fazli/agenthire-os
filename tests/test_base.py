from sqlalchemy import MetaData

from app.db.base import NAMING_CONVENTION, Base


def test_base_uses_expected_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_base_exposes_sqlalchemy_metadata() -> None:
    assert isinstance(Base.metadata, MetaData)
