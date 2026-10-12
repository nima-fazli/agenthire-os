import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.document_search import DocumentSearchQuery
from app.services.document_search import DocumentSearchService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    service = DocumentSearchService(session, Settings(_env_file=None))
    service._memberships = AsyncMock()
    service._memberships.get_by_user_and_organization.return_value = object()
    service._repository = AsyncMock()
    hit = {
        "document_id": uuid4(),
        "candidate_id": uuid4(),
        "candidate_name": "Ada",
        "filename": "resume.pdf",
        "chunk_set_id": uuid4(),
        "chunk_position": 0,
        "start_offset": 0,
        "end_offset": 10,
        "text": "Python SQL",
        "chunk_sha256": "a" * 64,
        "source_document_sha256": "b" * 64,
        "source_text_sha256": "c" * 64,
        "score": 0.5,
    }
    service._repository.search.return_value = ([hit], 3)
    return SimpleNamespace(
        session=session,
        service=service,
        hit=hit,
        scope={"organization_id": uuid4(), "user_id": uuid4()},
        data=DocumentSearchQuery(q="Python SQL", limit=2, offset=1),
    )


def search(context):
    return context.service.search_for_user(context.data, **context.scope)


def test_non_members_cannot_reach_search_or_deadline_configuration(context) -> None:
    context.service._memberships.get_by_user_and_organization.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(search(context))
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    context.service._repository.search.assert_not_awaited()


def test_search_forwards_authenticated_scope_and_returns_provenance(context) -> None:
    page = asyncio.run(search(context))
    assert page.total == 3 and page.limit == 2 and page.offset == 1
    assert page.items[0].document_id == context.hit["document_id"]
    assert page.items[0].source_text_sha256 == "c" * 64
    assert context.service._repository.search.await_args.kwargs == {
        **context.scope,
        "data": context.data,
        "timeout_ms": 1500,
    }
    context.session.commit.assert_not_awaited()


def test_no_results_and_out_of_range_page_are_valid(context) -> None:
    context.service._repository.search.return_value = ([], 10)
    page = asyncio.run(search(context))
    assert page.items == [] and page.total == 10


def database_error(sqlstate: str):
    original = RuntimeError("synthetic-private-database-details")
    original.sqlstate = sqlstate
    return DBAPIError("SELECT", {}, original, False)


def test_postgres_cancellation_is_a_safe_retryable_domain_error(context) -> None:
    context.service._repository.search.side_effect = database_error("57014")
    with pytest.raises(AppError) as error:
        asyncio.run(search(context))
    assert (
        error.value.code == "DOCUMENT_SEARCH_TIMEOUT" and error.value.status_code == 503
    )
    assert "synthetic-private-database-details" not in str(error.value)
    context.session.rollback.assert_awaited_once()


def test_other_database_errors_are_not_mislabeled_as_timeouts(context) -> None:
    failure = database_error("08006")
    context.service._repository.search.side_effect = failure
    with pytest.raises(DBAPIError) as error:
        asyncio.run(search(context))
    assert error.value is failure
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("unavailable"), asyncio.CancelledError()],
    ids=["unexpected", "cancellation"],
)
def test_failed_read_transaction_is_rolled_back(
    context, failure: BaseException
) -> None:
    context.service._repository.search.side_effect = failure
    with pytest.raises(type(failure)):
        asyncio.run(search(context))
    context.session.rollback.assert_awaited_once()
