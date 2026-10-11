import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_storage import (
    DocumentStorage,
    DocumentStorageError,
    StoredDocument,
)
from app.core.errors import AppError
from app.models.candidate_document import CandidateDocument
from app.repositories.candidate import CandidateRepository
from app.repositories.candidate_document import CandidateDocumentRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.schemas.candidate_document import DocumentUpload
from app.services.candidate_document import CandidateDocumentService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    storage = AsyncMock(spec=DocumentStorage)
    service = CandidateDocumentService(session, storage, max_bytes=1024)
    service._repository = AsyncMock(spec=CandidateDocumentRepository)
    service._candidates = AsyncMock(spec=CandidateRepository)
    service._memberships = AsyncMock(spec=OrganizationMembershipRepository)
    scope = {"organization_id": uuid4(), "candidate_id": uuid4(), "user_id": uuid4()}
    document = CandidateDocument(
        id=uuid4(),
        **{k: v for k, v in scope.items() if k != "user_id"},
        uploaded_by_user_id=scope["user_id"],
        filename="resume.pdf",
        content_type="application/pdf",
        size_bytes=50,
        sha256="a" * 64,
        storage_key=uuid4().hex + ".pdf",
        status="ready",
    )
    service._repository.get_by_digest.return_value = None
    service._repository.get_for_candidate.return_value = document
    service._repository.create.return_value = document
    stored = StoredDocument(uuid4().hex + ".pdf", 50, document.sha256)
    storage.save_pdf.return_value = stored
    return SimpleNamespace(
        service=service,
        session=session,
        storage=storage,
        scope=scope,
        document=document,
        stored=stored,
    )


async def body():
    yield b"%PDF-1.7\n%%EOF"


def invoke(context, operation: str = "upload", **changes):
    service, scope = context.service, context.scope
    if operation == "upload":
        args = {"content_type": "application/pdf", "content_length": None} | changes
        return service.upload(
            DocumentUpload(filename="resume.pdf"), body(), **scope, **args
        )
    if operation == "list":
        return service.list_for_user(**scope, limit=50, offset=0)
    return getattr(service, f"{operation}_for_user")(context.document.id, **scope)


@pytest.mark.parametrize("operation", ["upload", "list", "get", "download", "delete"])
def test_non_member_never_looks_up_candidate_or_document(
    context, operation: str
) -> None:
    context.service._memberships.get_by_user_and_organization.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, operation))
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    context.service._candidates.get_for_organization.assert_not_awaited()
    assert not context.service._repository.mock_calls
    assert not context.storage.mock_calls


@pytest.mark.parametrize("operation", ["upload", "list", "get", "download", "delete"])
def test_missing_candidate_never_accesses_documents(context, operation: str) -> None:
    context.service._candidates.get_for_organization.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, operation))
    assert error.value.code == "CANDIDATE_NOT_FOUND"
    assert not context.service._repository.mock_calls
    assert not context.storage.mock_calls


def test_upload_uses_server_owned_metadata_and_commits(context) -> None:
    result = asyncio.run(invoke(context))
    assert result is context.document
    values = context.service._repository.create.await_args.kwargs
    assert values["organization_id"] == context.scope["organization_id"]
    assert values["candidate_id"] == context.scope["candidate_id"]
    assert values["uploaded_by_user_id"] == context.scope["user_id"]
    assert values["sha256"] == context.document.sha256
    context.session.commit.assert_awaited_once()
    context.storage.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"content_type": "text/html"}, "UNSUPPORTED_DOCUMENT_TYPE"),
        ({"content_length": "1025"}, "DOCUMENT_TOO_LARGE"),
        ({"content_length": "9" * 5000}, "DOCUMENT_TOO_LARGE"),
        ({"content_length": "-1"}, "INVALID_CONTENT_LENGTH"),
        ({"content_length": "not-a-number"}, "INVALID_CONTENT_LENGTH"),
    ],
)
def test_invalid_headers_are_rejected_before_storage(
    context, changes: dict, code: str
) -> None:
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, **changes))
    assert error.value.code == code
    context.storage.save_pdf.assert_not_awaited()


@pytest.mark.parametrize(
    "status, code",
    [("ready", "DOCUMENT_ALREADY_EXISTS"), ("deleting", "DOCUMENT_DELETION_PENDING")],
)
def test_duplicate_discards_only_new_object(context, status: str, code: str) -> None:
    context.document.status = status
    context.service._repository.get_by_digest.return_value = context.document
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context))
    assert error.value.code == code
    context.service._repository.create.assert_not_awaited()
    context.session.rollback.assert_awaited_once()
    context.storage.delete.assert_awaited_once_with(context.stored.storage_key)
    assert context.stored.storage_key != context.document.storage_key


@pytest.mark.parametrize("duplicate", [True, False])
def test_integrity_failure_is_rechecked_without_mislabeling_other_failures(
    context, duplicate: bool
) -> None:
    failure = IntegrityError("insert", {}, RuntimeError("database error"))
    context.service._repository.create.side_effect = failure
    context.service._repository.get_by_digest.side_effect = [
        None,
        context.document if duplicate else None,
    ]
    with pytest.raises(AppError if duplicate else IntegrityError) as error:
        asyncio.run(invoke(context))
    if duplicate:
        assert error.value.code == "DOCUMENT_ALREADY_EXISTS"
    else:
        assert error.value is failure
    context.session.rollback.assert_awaited_once()
    context.storage.delete.assert_awaited_once()


def test_failed_commit_rolls_back_and_discards_uploaded_file(context) -> None:
    context.session.commit.side_effect = RuntimeError("commit failed")
    context.service._repository.get_for_candidate.return_value = None
    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(invoke(context))
    context.session.rollback.assert_awaited_once()
    context.storage.delete.assert_awaited_once()


def test_ambiguous_commit_keeps_a_file_referenced_by_committed_metadata(
    context,
) -> None:
    context.session.commit.side_effect = RuntimeError("connection lost after commit")
    with pytest.raises(RuntimeError):
        asyncio.run(invoke(context))
    context.storage.delete.assert_not_awaited()


def test_cancelled_metadata_insert_discards_file(context) -> None:
    context.service._repository.create.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke(context))
    context.session.rollback.assert_awaited_once()
    context.storage.delete.assert_awaited_once()


def test_upload_timeout_returns_408(context) -> None:
    async def slow_storage(*_, **__):
        await asyncio.Event().wait()

    context.storage.save_pdf.side_effect = slow_storage
    context.service._upload_timeout_seconds = 0.01
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context))
    assert error.value.status_code == 408
    context.service._repository.create.assert_not_awaited()


def test_content_length_with_many_leading_zeroes_does_not_crash(context) -> None:
    assert (
        asyncio.run(invoke(context, content_length="0" * 5000 + "50"))
        is context.document
    )


def test_upload_storage_failure_is_safe_and_does_not_create_metadata(context) -> None:
    context.storage.save_pdf.side_effect = DocumentStorageError(
        "synthetic-private-storage-path"
    )
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context))
    assert error.value.status_code == 503
    assert "synthetic-private" not in str(error.value)
    context.service._repository.create.assert_not_awaited()


def test_download_opens_under_lock_and_closes_on_commit_failure(context) -> None:
    handle = io.BytesIO(b"pdf")
    context.storage.open.return_value = handle
    context.session.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        asyncio.run(invoke(context, "download"))
    assert handle.closed
    assert (
        context.service._repository.get_for_candidate.await_args.kwargs["for_update"]
        is True
    )
    context.session.rollback.assert_awaited_once()


def test_download_missing_file_is_safe(context) -> None:
    context.storage.open.side_effect = DocumentStorageError("missing file")
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, "download"))
    assert error.value.code == "DOCUMENT_STORAGE_UNAVAILABLE"


def test_cancelled_download_closes_the_open_file(context) -> None:
    handle = io.BytesIO(b"pdf")
    context.storage.open.return_value = handle
    context.session.commit.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke(context, "download"))
    assert handle.closed
    context.session.rollback.assert_awaited_once()


def test_missing_document_cannot_be_read_but_delete_is_repeatable(context) -> None:
    context.service._repository.get_for_candidate.return_value = None
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, "get"))
    assert error.value.code == "DOCUMENT_NOT_FOUND"
    asyncio.run(invoke(context, "delete"))
    context.storage.delete.assert_not_awaited()


def test_deletion_tombstone_is_committed_before_object_and_row_are_deleted(
    context,
) -> None:
    events = []
    context.service._repository.mark_deleting.side_effect = lambda _: events.append(
        "mark"
    )
    context.session.commit.side_effect = lambda: events.append("commit")
    context.storage.delete.side_effect = lambda _: events.append("file")
    context.service._repository.delete_for_candidate.side_effect = lambda **_: (
        events.append("row")
    )
    asyncio.run(invoke(context, "delete"))
    assert events == ["mark", "commit", "file", "row", "commit"]


def test_storage_delete_failure_preserves_hidden_row_for_retry(context) -> None:
    context.storage.delete.side_effect = DocumentStorageError("disk unavailable")
    with pytest.raises(AppError) as error:
        asyncio.run(invoke(context, "delete"))
    assert error.value.status_code == 503
    context.session.commit.assert_awaited_once()
    context.service._repository.delete_for_candidate.assert_not_awaited()
    context.document.status = "deleting"
    context.storage.delete.side_effect = None
    asyncio.run(invoke(context, "delete"))
    context.service._repository.delete_for_candidate.assert_awaited_once()
