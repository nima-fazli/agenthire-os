import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.document_storage import DocumentStorageError
from app.core.errors import AppError, NotFoundError
from app.core.pdf_extraction import ExtractedPdf, ExtractionFailure
from app.models.candidate_document import CandidateDocument
from app.models.document_extraction import DocumentExtraction
from app.repositories.document_extraction import ExtractionTask
from app.schemas.document_extraction import ExtractionRequest
from app.services.candidate_document import CandidateDocumentService
from app.services.document_extraction import (
    DocumentExtractionService,
    ExtractionProcessor,
)


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    documents = AsyncMock(spec=CandidateDocumentService)
    service = DocumentExtractionService(session, documents, max_attempts=3)
    service._repository = AsyncMock()
    service._document_repository = AsyncMock()
    document_id = uuid4()
    extraction = DocumentExtraction(
        document_id=document_id,
        status="queued",
        attempts=0,
        failure_code=None,
        page_count=None,
        text=None,
    )
    service._repository.get_for_candidate.return_value = None
    service._repository.create.return_value = extraction
    service._document_repository.get_for_candidate.return_value = CandidateDocument(
        id=document_id, status="ready"
    )
    return SimpleNamespace(
        service=service,
        session=session,
        documents=documents,
        extraction=extraction,
        scope={"organization_id": uuid4(), "candidate_id": uuid4(), "user_id": uuid4()},
    )


def request(context, retry: bool = False):
    return context.service.request_for_user(
        context.extraction.document_id, ExtractionRequest(retry=retry), **context.scope
    )


@pytest.mark.parametrize("operation", ["request", "get", "text"])
def test_authorization_precedes_any_job_lookup(context, operation: str) -> None:
    context.documents.get_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND", message="Hidden."
    )
    call = (
        request(context)
        if operation == "request"
        else getattr(context.service, f"{operation}_for_user")(
            context.extraction.document_id, **context.scope
        )
    )
    with pytest.raises(AppError) as error:
        asyncio.run(call)
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    assert not context.service._repository.mock_calls
    assert not context.service._document_repository.mock_calls


def test_queue_creates_one_job_under_document_lock(context) -> None:
    assert asyncio.run(request(context)) is context.extraction
    assert (
        context.service._document_repository.get_for_candidate.await_args.kwargs[
            "for_update"
        ]
        is True
    )
    context.service._repository.create.assert_awaited_once_with(
        context.extraction.document_id
    )
    context.session.commit.assert_awaited_once()


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed"])
def test_repeated_request_returns_existing_job_without_requeue(
    context, status: str
) -> None:
    context.extraction.status = status
    context.service._repository.get_for_candidate.return_value = context.extraction
    assert asyncio.run(request(context)) is context.extraction
    context.service._repository.create.assert_not_awaited()
    context.service._repository.requeue.assert_not_awaited()


def test_explicit_retry_preserves_attempt_budget(context) -> None:
    context.extraction.status = "failed"
    context.extraction.attempts = 1
    context.service._repository.get_for_candidate.return_value = context.extraction
    context.service._repository.requeue.return_value = context.extraction
    asyncio.run(request(context, retry=True))
    context.service._repository.requeue.assert_awaited_once_with(context.extraction)


def test_retry_limit_rolls_back(context) -> None:
    context.extraction.status = "failed"
    context.extraction.attempts = 3
    context.service._repository.get_for_candidate.return_value = context.extraction
    with pytest.raises(AppError) as error:
        asyncio.run(request(context, retry=True))
    assert error.value.code == "EXTRACTION_RETRY_LIMIT"
    context.session.rollback.assert_awaited_once()


def test_deleted_document_cannot_be_queued(context) -> None:
    context.service._document_repository.get_for_candidate.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(request(context))
    assert error.value.code == "DOCUMENT_NOT_FOUND"
    context.service._repository.create.assert_not_awaited()


@pytest.mark.parametrize("duplicate", [True, False])
def test_integrity_failure_is_rechecked(context, duplicate: bool) -> None:
    failure = IntegrityError("insert", {}, RuntimeError("db failure"))
    context.service._repository.create.side_effect = failure
    context.service._repository.get_for_candidate.side_effect = [
        None,
        context.extraction if duplicate else None,
    ]
    if duplicate:
        assert asyncio.run(request(context)) is context.extraction
    else:
        with pytest.raises(IntegrityError):
            asyncio.run(request(context))
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    "status, code",
    [
        ("queued", "EXTRACTION_NOT_READY"),
        ("running", "EXTRACTION_NOT_READY"),
        ("failed", "EXTRACTION_FAILED"),
    ],
)
def test_incomplete_job_never_returns_text(context, status: str, code: str) -> None:
    context.extraction.status = status
    context.service._repository.get_for_candidate.return_value = context.extraction
    with pytest.raises(AppError) as error:
        asyncio.run(
            context.service.text_for_user(
                context.extraction.document_id, **context.scope
            )
        )
    assert error.value.code == code


def processor_context():
    sessions = [AsyncMock(spec=AsyncSession), AsyncMock(spec=AsyncSession)]
    managers = [MagicMock(), MagicMock()]
    for manager, session in zip(managers, sessions, strict=True):
        manager.__aenter__ = AsyncMock(return_value=session)
        manager.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(side_effect=managers)
    repositories = [AsyncMock(), AsyncMock()]
    task = ExtractionTask(uuid4(), uuid4().hex + ".pdf", 50, "a" * 64, uuid4())
    repositories[0].claim_next.return_value = task
    repositories[1].finish_if_owned.return_value = True
    storage, extractor = AsyncMock(), AsyncMock()
    handle = io.BytesIO(b"source")
    storage.open.return_value = handle
    extractor.extract.return_value = ExtractedPdf("text", 1)
    processor = ExtractionProcessor(
        factory, storage, extractor, Settings(_env_file=None)
    )
    return SimpleNamespace(
        processor=processor,
        sessions=sessions,
        repositories=repositories,
        handle=handle,
        storage=storage,
        extractor=extractor,
    )


def test_processor_releases_database_before_parsing_and_closes_file() -> None:
    context = processor_context()

    async def parse(*_, **__):
        context.sessions[0].commit.assert_awaited_once()
        return ExtractedPdf("text", 1)

    context.extractor.extract.side_effect = parse
    with patch(
        "app.services.document_extraction.DocumentExtractionRepository",
        side_effect=context.repositories,
    ):
        assert asyncio.run(context.processor.run_one()) is True
    assert context.handle.closed
    context.sessions[1].commit.assert_awaited_once()


@pytest.mark.parametrize(
    "failure, code",
    [
        (ExtractionFailure("PDF_NO_TEXT"), "PDF_NO_TEXT"),
        (RuntimeError("synthetic-private-details"), "EXTRACTION_INTERNAL_ERROR"),
    ],
)
def test_processor_persists_safe_failure_codes(failure: Exception, code: str) -> None:
    context = processor_context()
    context.extractor.extract.side_effect = failure
    with patch(
        "app.services.document_extraction.DocumentExtractionRepository",
        side_effect=context.repositories,
    ):
        asyncio.run(context.processor.run_one())
    assert (
        context.repositories[1].finish_if_owned.await_args.kwargs["failure_code"]
        == code
    )
    assert context.handle.closed


def test_storage_failure_is_reported_without_private_paths() -> None:
    context = processor_context()
    context.storage.open.side_effect = DocumentStorageError("synthetic-private-path")
    with patch(
        "app.services.document_extraction.DocumentExtractionRepository",
        side_effect=context.repositories,
    ):
        asyncio.run(context.processor.run_one())
    assert (
        context.repositories[1].finish_if_owned.await_args.kwargs["failure_code"]
        == "DOCUMENT_STORAGE_UNAVAILABLE"
    )


def test_cancelled_parser_closes_file_and_leaves_lease_for_recovery() -> None:
    context = processor_context()
    context.extractor.extract.side_effect = asyncio.CancelledError()
    with (
        patch(
            "app.services.document_extraction.DocumentExtractionRepository",
            side_effect=context.repositories,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(context.processor.run_one())
    assert context.handle.closed
    context.repositories[1].finish_if_owned.assert_not_awaited()


def test_idle_processor_never_opens_storage() -> None:
    context = processor_context()
    context.repositories[0].claim_next.return_value = None
    with patch(
        "app.services.document_extraction.DocumentExtractionRepository",
        side_effect=context.repositories,
    ):
        assert asyncio.run(context.processor.run_one()) is False
    context.storage.open.assert_not_awaited()
