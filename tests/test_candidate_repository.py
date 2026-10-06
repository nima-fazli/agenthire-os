import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.repositories.candidate import CandidateRepository


def test_create_candidate_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    organization_id = uuid4()

    repository = CandidateRepository(
        session
    )

    candidate = asyncio.run(
        repository.create(
            organization_id=organization_id,
            full_name="Ada Lovelace",
            email="ada@example.com",
            phone=None,
            location="Amsterdam",
            headline="AI Engineer",
            summary=None,
        )
    )

    assert candidate.organization_id == organization_id
    assert candidate.full_name == "Ada Lovelace"
    assert candidate.email == "ada@example.com"

    session.add.assert_called_once_with(
        candidate
    )

    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(
        candidate
    )

    session.commit.assert_not_awaited()


def test_update_candidate_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    candidate = Candidate(
        id=uuid4(),
        organization_id=uuid4(),
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone="+31 20 123 4567",
        location="Amsterdam",
        headline="AI Engineer",
        summary="Original summary.",
    )

    repository = CandidateRepository(
        session
    )

    result = asyncio.run(
        repository.update(
            candidate,
            full_name="Ada Byron",
            email="ada.byron@example.com",
            headline="Principal AI Engineer",
        )
    )

    assert result is candidate
    assert candidate.full_name == "Ada Byron"
    assert (
        candidate.email
        == "ada.byron@example.com"
    )
    assert (
        candidate.headline
        == "Principal AI Engineer"
    )

    assert (
        candidate.phone
        == "+31 20 123 4567"
    )
    assert candidate.location == "Amsterdam"
    assert candidate.summary == "Original summary."

    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(
        candidate
    )

    session.commit.assert_not_awaited()


def test_list_candidates_is_scoped_to_organization() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization_id = uuid4()

    candidates = [
        Candidate(
            id=uuid4(),
            organization_id=organization_id,
            full_name="Ada Lovelace",
        ),
        Candidate(
            id=uuid4(),
            organization_id=organization_id,
            full_name="Alan Turing",
        ),
    ]

    scalar_result = MagicMock()
    scalar_result.all.return_value = candidates

    query_result = MagicMock()
    query_result.scalars.return_value = scalar_result

    session.execute.return_value = query_result

    repository = CandidateRepository(
        session
    )

    result = asyncio.run(
        repository.list_for_organization(
            organization_id
        )
    )

    assert result == candidates

    statement = session.execute.await_args.args[
        0
    ]

    statement_text = str(
        statement
    )

    assert (
        "candidates.organization_id"
        in statement_text
    )

    assert organization_id in set(
        statement.compile().params.values()
    )


def test_get_candidate_is_scoped_to_organization() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization_id = uuid4()
    candidate_id = uuid4()

    candidate = Candidate(
        id=candidate_id,
        organization_id=organization_id,
        full_name="Ada Lovelace",
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = (
        candidate
    )

    session.execute.return_value = query_result

    repository = CandidateRepository(
        session
    )

    result = asyncio.run(
        repository.get_for_organization(
            candidate_id=candidate_id,
            organization_id=organization_id,
        )
    )

    assert result is candidate

    statement = session.execute.await_args.args[
        0
    ]

    statement_text = str(
        statement
    )

    assert "candidates.id" in statement_text
    assert (
        "candidates.organization_id"
        in statement_text
    )

    params = set(
        statement.compile().params.values()
    )

    assert candidate_id in params
    assert organization_id in params


def test_get_candidate_returns_none_when_not_found() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = (
        None
    )

    session.execute.return_value = query_result

    repository = CandidateRepository(
        session
    )

    result = asyncio.run(
        repository.get_for_organization(
            candidate_id=uuid4(),
            organization_id=uuid4(),
        )
    )

    assert result is None
