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
from app.schemas.job_matching import JobMatchProfileWrite
from app.services.job_matching import JobMatchingService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    service = JobMatchingService(session, Settings(_env_file=None))
    service._jobs = AsyncMock()
    service._candidates = AsyncMock()
    service._repository = AsyncMock()
    scope = {"organization_id": uuid4(), "user_id": uuid4(), "job_id": uuid4()}
    candidate_id, now = uuid4(), datetime.now(UTC)
    item = {
        "position": 0,
        "key": "python",
        "label": "Python",
        "q": "Python",
        "importance": "required",
    }
    profile = {
        "job_id": scope["job_id"],
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "criteria": [item],
    }
    hit = {
        "document_id": uuid4(),
        "candidate_id": candidate_id,
        "candidate_name": "Ada",
        "filename": "resume.pdf",
        "chunk_set_id": uuid4(),
        "chunk_position": 0,
        "start_offset": 0,
        "end_offset": 6,
        "text": "Python",
        "chunk_sha256": "a" * 64,
        "source_document_sha256": "b" * 64,
        "source_text_sha256": "c" * 64,
        "score": 0.5,
    }
    report = {
        "job_id": scope["job_id"],
        "candidate_id": candidate_id,
        "candidate_name": "Ada",
        "profile_revision": 1,
        "profile_updated_at": now,
        "observed_at": now,
        "ready_documents": 1,
        "indexed_documents": 1,
        "criteria": [item | {"evidence": hit}],
    }
    service._repository.get_profile.return_value = profile
    service._repository.save_profile.return_value = profile
    service._repository.lock_job.return_value = scope["job_id"]
    service._repository.evidence.return_value = report
    data = JobMatchProfileWrite(
        criteria=[{key: value for key, value in item.items() if key != "position"}]
    )
    return SimpleNamespace(
        session=session,
        service=service,
        scope=scope,
        candidate_id=candidate_id,
        data=data,
        report=report,
    )


def call(context, operation):
    if operation == "put":
        return context.service.put_profile(context.data, **context.scope)
    if operation == "get":
        return context.service.get_profile(**context.scope)
    return context.service.evidence(**context.scope, candidate_id=context.candidate_id)


@pytest.mark.parametrize("operation", ["put", "get", "evidence"])
@pytest.mark.parametrize("code", ["ORGANIZATION_NOT_FOUND", "JOB_NOT_FOUND"])
def test_job_authorization_precedes_profile_or_evidence_work(context, operation, code):
    context.service._jobs.get_for_user.side_effect = NotFoundError(
        code=code, message="Hidden"
    )
    with pytest.raises(NotFoundError) as error:
        asyncio.run(call(context, operation))
    assert error.value.code == code and context.service._repository.mock_calls == []
    context.service._candidates.get_for_user.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


def test_candidate_scope_is_checked_before_evidence_queries(context):
    context.service._candidates.get_for_user.side_effect = NotFoundError(
        code="CANDIDATE_NOT_FOUND", message="Hidden"
    )
    with pytest.raises(NotFoundError):
        asyncio.run(call(context, "evidence"))
    context.service._repository.evidence.assert_not_awaited()


def test_put_locks_parent_saves_validated_criteria_and_commits(context):
    value = asyncio.run(call(context, "put"))
    assert value.revision == 1 and value.criteria[0].key == "python"
    assert [call[0] for call in context.service._repository.mock_calls] == [
        "lock_job",
        "get_profile",
        "save_profile",
    ]
    assert context.service._repository.save_profile.await_args.kwargs == {
        **context.scope,
        "criteria": [item.model_dump() for item in context.data.criteria],
    }
    context.session.commit.assert_awaited_once()


@pytest.mark.parametrize("operation", ["get", "evidence"])
def test_missing_profile_is_explicit_after_authorization(context, operation):
    getattr(
        context.service._repository, "get_profile" if operation == "get" else "evidence"
    ).return_value = None
    with pytest.raises(NotFoundError) as error:
        asyncio.run(call(context, operation))
    assert error.value.code == "JOB_MATCH_PROFILE_NOT_FOUND"
    context.session.commit.assert_not_awaited()


def test_report_preserves_source_and_summary_without_writing_domain_state(context):
    value = asyncio.run(call(context, "evidence"))
    assert (
        value.criteria[0].evidence.text == "Python"
        and value.summary.required_with_evidence == 1
    )
    assert (
        value.summary.source_status == "indexed"
        and value.observed_at == context.report["observed_at"]
    )
    assert context.service._repository.evidence.await_args.kwargs == {
        **context.scope,
        "candidate_id": context.candidate_id,
        "timeout_ms": 1500,
    }
    context.session.commit.assert_not_awaited()
    context.service._jobs.update_for_user.assert_not_awaited()
    context.service._candidates.update_for_user.assert_not_awaited()


def test_empty_evidence_is_not_a_claim_that_the_candidate_lacks_a_skill(context):
    context.report["criteria"][0]["evidence"] = None
    context.report["indexed_documents"] = 0
    value = asyncio.run(call(context, "evidence"))
    assert (
        value.criteria[0].evidence is None
        and value.summary.source_status == "not_indexed"
    )
    assert (
        value.summary.required_total == 1 and value.summary.required_with_evidence == 0
    )


@pytest.mark.parametrize("sqlstate", ["57014", "08006"])
def test_only_database_cancellation_is_a_safe_timeout(context, sqlstate):
    original = RuntimeError("synthetic-private-database-details")
    original.sqlstate = sqlstate
    failure = DBAPIError("SELECT", {}, original, False)
    context.service._repository.evidence.side_effect = failure
    with pytest.raises(AppError if sqlstate == "57014" else DBAPIError) as error:
        asyncio.run(call(context, "evidence"))
    if sqlstate == "57014":
        assert (
            error.value.code == "MATCH_EVIDENCE_TIMEOUT"
            and error.value.status_code == 503
        )
        assert "synthetic-private" not in str(error.value)
    else:
        assert error.value is failure
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("operation", ["put", "get", "evidence"])
def test_cancellation_rolls_back_all_operations(context, operation):
    name = {"put": "save_profile", "get": "get_profile", "evidence": "evidence"}[
        operation
    ]
    getattr(context.service._repository, name).side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call(context, operation))
    context.session.rollback.assert_awaited_once()


def test_commit_failure_does_not_leave_a_partial_profile(context):
    context.session.commit.side_effect = RuntimeError("Unavailable")
    with pytest.raises(RuntimeError):
        asyncio.run(call(context, "put"))
    context.session.rollback.assert_awaited_once()


def test_lost_job_lock_prevents_profile_writes(context):
    context.service._repository.lock_job.return_value = None
    with pytest.raises(NotFoundError):
        asyncio.run(call(context, "put"))
    context.service._repository.save_profile.assert_not_awaited()
