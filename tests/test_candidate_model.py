from app.models.candidate import Candidate


def test_candidate_table_name() -> None:
    assert Candidate.__tablename__ == "candidates"


def test_candidate_has_expected_columns() -> None:
    assert set(
        Candidate.__table__.columns.keys()
    ) == {
        "id",
        "organization_id",
        "full_name",
        "email",
        "phone",
        "location",
        "headline",
        "summary",
        "created_at",
        "updated_at",
    }


def test_candidate_id_is_primary_key() -> None:
    primary_key_columns = {
        column.name
        for column in Candidate.__table__.primary_key.columns
    }

    assert primary_key_columns == {
        "id",
    }


def test_candidate_organization_foreign_key() -> None:
    foreign_keys = list(
        Candidate.__table__.foreign_keys
    )

    assert len(foreign_keys) == 1

    assert (
        foreign_keys[0].target_fullname
        == "organizations.id"
    )


def test_candidate_has_organization_index() -> None:
    index_names = {
        index.name
        for index in Candidate.__table__.indexes
    }

    assert (
        "ix_candidates_organization_id"
        in index_names
    )
