import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.text_chunking import text_digest
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunkSet
from app.models.document_extraction import DocumentExtraction
from app.services.candidate_document import CandidateDocumentService
from app.services.document_chunk import DocumentChunkService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    documents = AsyncMock(spec=CandidateDocumentService)
    settings = Settings(_env_file=None)
    service = DocumentChunkService(session, documents, settings)
    service._document_repository = AsyncMock()
    service._extractions = AsyncMock()
    service._repository = AsyncMock()
    document_id = uuid4()
    document = CandidateDocument(id=document_id, sha256="a" * 64, status="ready")
    extraction = DocumentExtraction(
        document_id=document_id,
        status="succeeded",
        text="Python SQL " * 250,
        page_count=1,
    )
    service._document_repository.get_for_candidate.return_value = document
    service._extractions.get_for_candidate.return_value = extraction
    service._repository.get_policy.return_value = None

    async def create(chunk_set, _chunks):
        chunk_set.id = uuid4()
        chunk_set.created_at = datetime.now(UTC)
        return chunk_set

    service._repository.create.side_effect = create
    return SimpleNamespace(
        service=service,
        session=session,
        documents=documents,
        document=document,
        extraction=extraction,
        chunk_set_id=uuid4(),
        scope={"organization_id": uuid4(), "candidate_id": uuid4(), "user_id": uuid4()},
    )


def build(context):
    return context.service.build_for_user(context.document.id, **context.scope)


def call(context, operation):
    if operation == "build":
        return build(context)
    if operation == "get":
        return context.service.get_for_user(
            context.document.id, context.chunk_set_id, **context.scope
        )
    if operation == "list":
        return context.service.list_for_user(
            context.document.id, **context.scope, limit=2, offset=0
        )
    return context.service.chunks_for_user(
        context.document.id, context.chunk_set_id, **context.scope, limit=2, offset=0
    )


@pytest.mark.parametrize("operation", ["build", "get", "list", "items"])
def test_authorization_precedes_every_chunk_lookup(context, operation: str) -> None:
    context.documents.get_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND", message="Hidden."
    )
    with pytest.raises(AppError) as error:
        asyncio.run(call(context, operation))
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    assert not context.service._repository.mock_calls
    assert not context.service._extractions.mock_calls
    assert not context.service._document_repository.mock_calls


def test_generation_locks_source_and_commits_exact_provenance(context) -> None:
    chunk_set, created = asyncio.run(build(context))
    assert created is True
    for repository in (
        context.service._document_repository,
        context.service._extractions,
    ):
        assert repository.get_for_candidate.await_args.kwargs["for_update"] is True
    assert chunk_set.source_document_sha256 == context.document.sha256
    assert chunk_set.source_text_sha256 == text_digest(context.extraction.text)
    assert chunk_set.source_char_count == len(context.extraction.text)
    chunks = context.service._repository.create.await_args.args[1]
    assert len(chunks) == chunk_set.chunk_count
    assert chunks[-1].end_offset == chunk_set.source_char_count
    context.session.commit.assert_awaited_once()


def test_cached_request_keeps_existing_id_and_does_not_recompute(context) -> None:
    existing = DocumentChunkSet(id=context.chunk_set_id)
    context.service._repository.get_policy.return_value = existing
    with patch("app.services.document_chunk.chunk_text") as chunker:
        assert asyncio.run(build(context)) == (existing, False)
    chunker.assert_not_called()
    context.service._repository.create.assert_not_awaited()


@pytest.mark.parametrize(
    "status, code",
    [
        ("queued", "EXTRACTION_NOT_READY"),
        ("running", "EXTRACTION_NOT_READY"),
        ("failed", "EXTRACTION_FAILED"),
    ],
)
def test_incomplete_or_failed_source_is_never_chunked(
    context, status: str, code: str
) -> None:
    context.extraction.status = status
    with pytest.raises(AppError) as error:
        asyncio.run(build(context))
    assert error.value.code == code
    context.service._repository.create.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    "missing, code",
    [("document", "DOCUMENT_NOT_FOUND"), ("extraction", "EXTRACTION_NOT_FOUND")],
)
def test_missing_source_cannot_create_orphan_chunks(
    context, missing: str, code: str
) -> None:
    repository = (
        context.service._document_repository
        if missing == "document"
        else context.service._extractions
    )
    repository.get_for_candidate.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(build(context))
    assert error.value.code == code
    context.service._repository.create.assert_not_awaited()


@pytest.mark.parametrize("empty", [True, False], ids=["empty-source", "count-limit"])
def test_limits_roll_back_without_partial_generation(context, empty: bool) -> None:
    if empty:
        context.extraction.text = " "
    else:
        context.service._settings = Settings(_env_file=None, chunk_max_count=1)
    with pytest.raises(AppError) as error:
        asyncio.run(build(context))
    assert error.value.code == (
        "CHUNK_SOURCE_EMPTY" if empty else "CHUNK_LIMIT_EXCEEDED"
    )
    context.service._repository.create.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


def test_policy_change_creates_new_set_and_keeps_source_hash(context) -> None:
    first, _ = asyncio.run(build(context))
    context.service._settings = Settings(_env_file=None, chunk_max_chars=1500)
    second, _ = asyncio.run(build(context))
    assert first.id != second.id
    assert first.chunk_max_chars == 1200 and second.chunk_max_chars == 1500
    assert first.source_text_sha256 == second.source_text_sha256
    assert first.chunk_count > second.chunk_count


@pytest.mark.parametrize("duplicate", [True, False])
def test_integrity_failure_is_rechecked_after_rollback(
    context, duplicate: bool
) -> None:
    failure = IntegrityError("insert", {}, RuntimeError("database error"))
    existing = DocumentChunkSet(id=context.chunk_set_id)
    context.service._repository.create.side_effect = failure
    context.service._repository.get_policy.side_effect = [
        None,
        existing if duplicate else None,
    ]
    if duplicate:
        assert asyncio.run(build(context)) == (existing, False)
    else:
        with pytest.raises(IntegrityError):
            asyncio.run(build(context))
    context.session.rollback.assert_awaited_once()
    assert context.documents.get_for_user.await_count == 2


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("unavailable"), asyncio.CancelledError()],
    ids=["database-error", "cancellation"],
)
def test_transaction_errors_are_rolled_back(context, failure: BaseException) -> None:
    context.session.commit.side_effect = failure
    with pytest.raises(type(failure)):
        asyncio.run(build(context))
    context.session.rollback.assert_awaited_once()


def test_unknown_set_is_hidden_after_document_authorization(context) -> None:
    context.service._repository.get.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(call(context, "get"))
    assert error.value.code == "CHUNK_SET_NOT_FOUND"


def test_chunk_page_keeps_metadata_when_offset_is_beyond_last_item(context) -> None:
    existing = DocumentChunkSet(id=context.chunk_set_id, chunk_count=3)
    context.service._repository.get.return_value = existing
    context.service._repository.list_chunks.return_value = []
    chunk_set, items = asyncio.run(
        context.service.chunks_for_user(
            context.document.id,
            context.chunk_set_id,
            **context.scope,
            limit=2,
            offset=50,
        )
    )
    assert chunk_set.chunk_count == 3 and items == []
    assert context.service._repository.list_chunks.await_args.kwargs == {
        "organization_id": context.scope["organization_id"],
        "candidate_id": context.scope["candidate_id"],
        "document_id": context.document.id,
        "chunk_set_id": context.chunk_set_id,
        "limit": 2,
        "offset": 50,
    }
