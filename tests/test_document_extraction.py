import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pdf_extraction import ExtractedPdf
from app.db.base import Base
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentExtraction,
    Organization,
    User,
)
from app.repositories.document_extraction import (
    DocumentExtractionRepository,
    ExtractionTask,
)
from app.schemas.document_extraction import ExtractionRequest


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Organization.__table__,
            Candidate.__table__,
            CandidateDocument.__table__,
            DocumentExtraction.__table__,
        ],
    )
    user, org, candidate, document = [uuid4() for _ in range(4)]
    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {"id": user, "email": "owner@example.com", "password_hash": "hash"},
        )
        connection.execute(
            insert(Organization), {"id": org, "name": "Test", "slug": "test"}
        )
        connection.execute(
            insert(Candidate),
            {"id": candidate, "organization_id": org, "full_name": "Ada"},
        )
        connection.execute(
            insert(CandidateDocument),
            {
                "id": document,
                "organization_id": org,
                "candidate_id": candidate,
                "uploaded_by_user_id": user,
                "filename": "resume.pdf",
                "content_type": "application/pdf",
                "size_bytes": 50,
                "sha256": "a" * 64,
                "storage_key": uuid4().hex + ".pdf",
                "status": "ready",
            },
        )
    yield engine, document
    engine.dispose()


def test_one_job_per_document_and_cascade_deletion(database) -> None:
    engine, document = database
    with engine.begin() as connection:
        connection.execute(insert(DocumentExtraction), {"document_id": document})
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(insert(DocumentExtraction), {"document_id": document})
    with engine.begin() as connection:
        connection.execute(
            CandidateDocument.__table__.delete().where(CandidateDocument.id == document)
        )
        assert connection.execute(select(DocumentExtraction)).all() == []


@pytest.mark.parametrize(
    "values",
    [
        {"status": "public"},
        {"attempts": -1},
        {"page_count": 0},
        {"status": "running"},
        {"status": "queued", "lease_token": uuid4()},
        {"status": "failed"},
        {
            "status": "succeeded",
            "page_count": 1,
            "text": "",
            "completed_at": datetime.now(UTC),
        },
        {"document_id": uuid4()},
    ],
)
def test_invalid_extraction_states_are_blocked_by_database(
    database, values: dict
) -> None:
    engine, document = database
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            insert(DocumentExtraction), {"document_id": document} | values
        )


@pytest.mark.parametrize(
    "payload", [{"status": "succeeded"}, {"retry": "true"}, {"retry": 1}]
)
def test_request_cannot_set_worker_owned_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ExtractionRequest(**payload)


def session():
    value = MagicMock(spec=AsyncSession)
    value.execute = AsyncMock(return_value=MagicMock())
    value.flush = AsyncMock()
    value.refresh = AsyncMock()
    value.commit = AsyncMock()
    return value


def test_public_repository_lookup_is_parent_scoped_and_locks_only_job() -> None:
    value = session()
    scope = {
        "organization_id": uuid4(),
        "candidate_id": uuid4(),
        "document_id": uuid4(),
    }
    asyncio.run(
        DocumentExtractionRepository(value).get_for_candidate(**scope, for_update=True)
    )
    statement = value.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert (
        "candidate_documents.organization_id =" in sql
        and "candidate_documents.candidate_id =" in sql
    )
    assert "FOR UPDATE OF document_extractions" in sql
    assert all(item in statement.compile().params.values() for item in scope.values())
    value.commit.assert_not_awaited()


def test_claim_uses_skip_locked_and_renews_expired_lease() -> None:
    value = session()
    document = CandidateDocument(
        id=uuid4(), storage_key=uuid4().hex + ".pdf", size_bytes=50, sha256="a" * 64
    )
    extraction = DocumentExtraction(
        document_id=document.id, status="running", attempts=1, lease_token=uuid4()
    )
    result = MagicMock()
    now = datetime.now(UTC)
    result.one_or_none.return_value = extraction, document, now
    value.execute.side_effect = [MagicMock(), result]
    task = asyncio.run(
        DocumentExtractionRepository(value).claim_next(max_attempts=3, lease_seconds=60)
    )
    statement = value.execute.await_args.args[0]
    assert "FOR UPDATE OF document_extractions SKIP LOCKED" in str(
        statement.compile(dialect=postgresql.dialect())
    )
    assert extraction.attempts == 2 and task.lease_token == extraction.lease_token
    assert extraction.lease_expires_at > now
    value.commit.assert_not_awaited()


def test_empty_queue_does_not_create_a_job() -> None:
    value = session()
    value.execute.return_value.one_or_none.return_value = None
    assert (
        asyncio.run(
            DocumentExtractionRepository(value).claim_next(
                max_attempts=3, lease_seconds=60
            )
        )
        is None
    )
    value.add.assert_not_called()


def test_result_requires_live_lease_matching_token_and_ready_source() -> None:
    value = session()
    value.execute.return_value.rowcount = 0
    task = ExtractionTask(uuid4(), "key", 50, "a" * 64, uuid4())
    accepted = asyncio.run(
        DocumentExtractionRepository(value).finish_if_owned(
            task, result=ExtractedPdf("text", 1)
        )
    )
    assert accepted is False
    statement = value.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "document_extractions.lease_token =" in sql
    assert "document_extractions.lease_expires_at > clock_timestamp()" in sql
    assert "EXISTS" in sql and "candidate_documents.sha256 =" in sql
    assert task.lease_token in statement.compile().params.values()
    value.commit.assert_not_awaited()


def test_repository_create_and_retry_never_commit() -> None:
    value = session()
    repository = DocumentExtractionRepository(value)
    extraction = asyncio.run(repository.create(uuid4()))
    extraction.status = "failed"
    extraction.attempts = 1
    extraction.failure_code = "PDF_TIMEOUT"
    asyncio.run(repository.requeue(extraction))
    assert extraction.status == "queued" and extraction.attempts == 1
    assert extraction.failure_code is None
    value.commit.assert_not_awaited()
