from app.db.base import NAMING_CONVENTION, Base


def test_base_uses_expected_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_base_metadata_starts_without_tables() -> None:
    assert len(Base.metadata.tables) == 0
