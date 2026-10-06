from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.candidate import (
    CandidateCreate,
    CandidateRead,
)


def test_candidate_create_normalizes_text() -> None:
    candidate = CandidateCreate(
        full_name="  Ada Lovelace  ",
        email="  ADA@EXAMPLE.COM  ",
        phone="  +31 20 123 4567  ",
        location="  Amsterdam  ",
        headline="  AI Engineer  ",
        summary="  Builds intelligent systems.  ",
    )

    assert candidate.full_name == "Ada Lovelace"
    assert candidate.email == "ada@example.com"
    assert candidate.phone == "+31 20 123 4567"
    assert candidate.location == "Amsterdam"
    assert candidate.headline == "AI Engineer"
    assert candidate.summary == "Builds intelligent systems."


def test_candidate_create_allows_optional_fields() -> None:
    candidate = CandidateCreate(
        full_name="Ada Lovelace",
    )

    assert candidate.email is None
    assert candidate.phone is None
    assert candidate.location is None
    assert candidate.headline is None
    assert candidate.summary is None


def test_candidate_create_rejects_blank_name() -> None:
    with pytest.raises(
        ValidationError
    ):
        CandidateCreate(
            full_name="   ",
        )


def test_candidate_create_rejects_blank_optional_text() -> None:
    with pytest.raises(
        ValidationError
    ):
        CandidateCreate(
            full_name="Ada Lovelace",
            headline="   ",
        )


def test_candidate_read_supports_attribute_objects() -> None:
    candidate_id = uuid4()
    organization_id = uuid4()
    now = datetime.now(UTC)

    source = SimpleNamespace(
        id=candidate_id,
        organization_id=organization_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone=None,
        location="Amsterdam",
        headline="AI Engineer",
        summary=None,
        created_at=now,
        updated_at=now,
    )

    candidate = CandidateRead.model_validate(
        source
    )

    assert candidate.id == candidate_id
    assert candidate.organization_id == organization_id
    assert candidate.full_name == "Ada Lovelace"
    assert candidate.email == "ada@example.com"
