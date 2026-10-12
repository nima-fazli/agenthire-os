import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.models.job_search_profile import JobSearchProfile
from app.schemas.job_retrieval import JobCandidateQuery, JobSearchProfileWrite
from app.services.job_retrieval import JobRetrievalService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    service = JobRetrievalService(session, Settings(_env_file=None))
    service._jobs = AsyncMock()
    service._repository = AsyncMock()
    scope = {"organization_id": uuid4(), "user_id": uuid4(), "job_id": uuid4()}
    now = datetime.now(UTC)
    profile = JobSearchProfile(
        job_id=scope["job_id"],
        query_text="Python",
        revision=1,
        updated_by_user_id=scope["user_id"],
        created_at=now,
        updated_at=now,
    )
    service._repository.save_profile.return_value = profile
    service._repository.get_profile.return_value = profile
    service._repository.lock_job.return_value = scope["job_id"]
    service._repository.retrieve.return_value = {
        "q": "Python",
        "profile_revision": 1,
        "profile_updated_at": now,
        "items": [],
        "total": 7,
    }
    return SimpleNamespace(
        service=service, session=session, scope=scope, profile=profile
    )


def call(context, operation):
    if operation == "put":
        return context.service.put_profile(
            JobSearchProfileWrite(q="Python"), **context.scope
        )
    if operation == "get":
        return context.service.get_profile(**context.scope)
    return context.service.retrieve(
        JobCandidateQuery(limit=2, offset=50), **context.scope
    )


@pytest.mark.parametrize("operation", ["put", "get", "retrieve"])
@pytest.mark.parametrize("code", ["ORGANIZATION_NOT_FOUND", "JOB_NOT_FOUND"])
def test_authorization_failure_precedes_all_profile_and_retrieval_work(
    context, operation, code
):
    context.service._jobs.get_for_user.side_effect = NotFoundError(
        code=code, message="Hidden"
    )
    with pytest.raises(NotFoundError) as error:
        asyncio.run(call(context, operation))
    assert error.value.code == code
    assert context.service._repository.mock_calls == []
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


def test_put_authorizes_locks_saves_then_commits(context):
    result = asyncio.run(call(context, "put"))
    assert result.q == "Python" and result.revision == 1
    repository = context.service._repository
    assert [entry[0] for entry in repository.mock_calls] == [
        "lock_job",
        "get_profile",
        "save_profile",
    ]
    assert repository.save_profile.await_args.kwargs == {
        "job_id": context.scope["job_id"],
        "user_id": context.scope["user_id"],
        "q": "Python",
    }
    context.session.commit.assert_awaited_once()


def test_lost_job_lock_does_not_write_profile(context):
    context.service._repository.lock_job.return_value = None
    with pytest.raises(NotFoundError) as error:
        asyncio.run(call(context, "put"))
    assert error.value.code == "JOB_NOT_FOUND"
    context.service._repository.save_profile.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("operation", ["get", "retrieve"])
def test_missing_profile_is_explicit_and_reads_never_commit(context, operation):
    context.service._repository.get_profile.return_value = None
    context.service._repository.retrieve.return_value = None
    with pytest.raises(NotFoundError) as error:
        asyncio.run(call(context, operation))
    assert error.value.code == "JOB_SEARCH_PROFILE_NOT_FOUND"
    context.session.commit.assert_not_awaited()


def test_page_preserves_snapshot_profile_count_and_forwarded_scope(context):
    page = asyncio.run(call(context, "retrieve"))
    assert page.items == [] and page.total == 7 and page.offset == 50
    assert page.profile_revision == 1 and page.job_id == context.scope["job_id"]
    assert context.service._repository.retrieve.await_args.kwargs == {
        **context.scope,
        "data": JobCandidateQuery(limit=2, offset=50),
        "timeout_ms": 1500,
    }
    context.session.commit.assert_not_awaited()


@pytest.mark.parametrize("sqlstate", ["57014", "08006"])
def test_only_postgres_cancellation_maps_to_safe_timeout(context, sqlstate):
    original = RuntimeError("synthetic-private-database-details")
    original.sqlstate = sqlstate
    failure = DBAPIError("SELECT", {}, original, False)
    context.service._repository.retrieve.side_effect = failure
    with pytest.raises(AppError if sqlstate == "57014" else DBAPIError) as error:
        asyncio.run(call(context, "retrieve"))
    if sqlstate == "57014":
        assert (
            error.value.code == "CANDIDATE_RETRIEVAL_TIMEOUT"
            and error.value.status_code == 503
        )
        assert "synthetic-private" not in str(error.value)
    else:
        assert error.value is failure
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("operation", ["put", "get", "retrieve"])
def test_cancellation_rolls_back_the_transaction(context, operation):
    name = {"put": "save_profile", "get": "get_profile", "retrieve": "retrieve"}[
        operation
    ]
    getattr(context.service._repository, name).side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call(context, operation))
    context.session.rollback.assert_awaited_once()


def test_commit_failure_rolls_back_profile_write(context):
    context.session.commit.side_effect = RuntimeError("Unavailable")
    with pytest.raises(RuntimeError):
        asyncio.run(call(context, "put"))
    context.session.rollback.assert_awaited_once()
