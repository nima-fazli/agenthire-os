import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_reconciliation import (
    MIN_AGE_SECONDS,
    ReconciliationError,
    ReconciliationStorage,
)
from app.core.document_storage import DocumentStorage, StoredDocument
from app.repositories.document_reconciliation import DocumentReconciliationRepository
from app.schemas.candidate_document import DocumentUpload
from app.services.candidate_document import CandidateDocumentService
from app.services.document_reconciliation import DocumentReconciliationService

KEY = "a" * 32 + ".pdf"
TEMP = ".upload-123abc_x"


@pytest.fixture
def context(tmp_path):
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    session.rollback = AsyncMock()
    store = ReconciliationStorage(tmp_path)
    service = DocumentReconciliationService(session, store)
    service._repository = AsyncMock(spec=DocumentReconciliationRepository)
    service._repository.referenced_keys.return_value = set()
    for key in (KEY, TEMP):
        path = tmp_path / key
        path.write_bytes(b"synthetic")
        os.utime(path, (time.time() - 8 * MIN_AGE_SECONDS,) * 2)
    return SimpleNamespace(session=session, store=store, service=service, root=tmp_path)


def run(context, **options):
    return asyncio.run(context.service.run(**options))


def test_dry_run_and_scoped_apply_are_repeatable(context):
    assert {item.action for item in run(context)} == {"would_delete"}
    assert (context.root / KEY).exists() and (context.root / TEMP).exists()
    assert run(context, keys=(KEY,), apply=True)[0].action == "deleted"
    assert (context.root / TEMP).exists()
    assert run(context, keys=(KEY,), apply=True)[0].action == "missing"
    context.session.rollback.assert_awaited()


def test_every_reference_is_retained_and_missing_reference_is_reported(context):
    context.service._repository.referenced_keys.return_value = {KEY}
    assert run(context, keys=(KEY,), apply=True)[0].action == "keep_referenced"
    (context.root / KEY).unlink()
    assert run(context, keys=(KEY,), apply=True)[0].action == "referenced_missing"


def test_young_and_unsafe_objects_are_kept(context):
    os.utime(context.root / KEY, None)
    (context.root / TEMP).unlink()
    (context.root / TEMP).mkdir()
    result = {
        item.key: item.action for item in run(context, keys=(KEY, TEMP), apply=True)
    }
    assert result == {KEY: "keep_young", TEMP: "keep_unsafe"}


def test_fresh_reference_check_precedes_delete(context):
    context.service._repository.referenced_keys.side_effect = [set(), {KEY}]
    assert run(context, keys=(KEY,), apply=True)[0].action == "keep_referenced"
    assert (context.root / KEY).exists()


@pytest.mark.parametrize("stage", ["guard", "initial", "recheck"])
def test_database_failure_never_deletes_unchecked_objects(context, stage):
    error = OperationalError("private SQL", {}, RuntimeError("private secret"))
    repo = context.service._repository
    if stage == "guard":
        repo.guard.side_effect = error
    else:
        repo.referenced_keys.side_effect = (
            [error] if stage == "initial" else [set(), error]
        )
    with pytest.raises(ReconciliationError) as caught:
        run(context, keys=(KEY,), apply=True)
    assert "private" not in str(caught.value)
    assert (context.root / KEY).exists()
    context.session.rollback.assert_awaited_once()


def test_cancellation_releases_guard_and_preserves_file(context):
    context.service._repository.referenced_keys.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run(context, keys=(KEY,), apply=True)
    assert (context.root / KEY).exists()
    context.session.rollback.assert_awaited_once()


def test_journal_keeps_completed_deletion_when_later_check_fails(context):
    error = OperationalError("query", {}, RuntimeError("unavailable"))
    context.service._repository.referenced_keys.side_effect = [set(), set(), error]
    journal = []
    with pytest.raises(ReconciliationError):
        run(context, keys=(KEY, TEMP), apply=True, emit=journal.append)
    assert [(item.key, item.action) for item in journal] == [(KEY, "deleted")]
    assert not (context.root / KEY).exists() and (context.root / TEMP).exists()


def test_changed_object_is_kept_and_delete_failure_is_reported(context, monkeypatch):
    monkeypatch.setattr(context.store, "remove_if_unchanged", lambda *_: False)
    assert run(context, keys=(KEY,), apply=True)[0].action == "changed"

    def failure(*_):
        raise ReconciliationError("private path")

    monkeypatch.setattr(context.store, "remove_if_unchanged", failure)
    assert run(context, keys=(KEY,), apply=True)[0].action == "delete_failed"
    assert (context.root / KEY).exists()


@pytest.mark.parametrize(
    "options",
    [
        {"apply": True},
        {"keys": (KEY, KEY)},
        {"keys": ("../outside",)},
        {"min_age_seconds": MIN_AGE_SECONDS - 1},
        {"min_age_seconds": True},
        {"min_age_seconds": 366 * MIN_AGE_SECONDS},
    ],
    ids=["scope", "duplicate", "path", "too_young", "boolean", "too_old"],
)
def test_invalid_options_never_access_database(context, options):
    with pytest.raises(ReconciliationError):
        run(context, **options)
    context.service._repository.guard.assert_not_awaited()


def test_busy_session_is_refused(context):
    context.session.in_transaction.return_value = True
    with pytest.raises(ReconciliationError, match="fresh"):
        run(context)
    context.service._repository.guard.assert_not_awaited()


def test_repository_guard_and_reference_query_cover_all_statuses_and_tenants():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [KEY]
    session.execute.return_value = result
    repo = DocumentReconciliationRepository(session)

    async def execute():
        await repo.guard()
        return await repo.referenced_keys((KEY,))

    assert asyncio.run(execute()) == {KEY}
    sql = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "READ COMMITTED" in sql[0]
    assert "lock_timeout" in sql[1] and "statement_timeout" in sql[2]
    assert "SHARE ROW EXCLUSIVE" in sql[3]
    assert "storage_key IN" in sql[4]
    assert "organization_id" not in sql[4] and "status" not in sql[4]
    session.commit.assert_not_called()


def test_upload_guard_is_acquired_before_storage_and_held_until_commit():
    session = AsyncMock(spec=AsyncSession)
    storage = AsyncMock(spec=DocumentStorage)
    service = CandidateDocumentService(session, storage, max_bytes=1024)
    service._require_candidate = AsyncMock()
    service._repository = AsyncMock()
    service._repository.get_by_digest.return_value = None
    service._repository.create.return_value = SimpleNamespace(id=uuid4())
    events = []
    session.execute.side_effect = lambda statement: events.append(str(statement))
    stored = StoredDocument(KEY, 20, "a" * 64)

    async def save(*args, **kwargs):
        events.append("file")
        return stored

    storage.save_pdf.side_effect = save
    session.commit.side_effect = lambda: events.append("commit")

    async def chunks():
        yield b"synthetic"

    asyncio.run(
        service.upload(
            DocumentUpload(filename="resume.pdf"),
            chunks(),
            organization_id=uuid4(),
            candidate_id=uuid4(),
            user_id=uuid4(),
            content_type="application/pdf",
            content_length=None,
        )
    )
    assert events == [
        "LOCK TABLE candidate_documents IN ROW EXCLUSIVE MODE",
        "file",
        "commit",
    ]


def test_failed_upload_guard_never_starts_filesystem_write():
    session = AsyncMock(spec=AsyncSession)
    storage = AsyncMock(spec=DocumentStorage)
    service = CandidateDocumentService(session, storage, max_bytes=1024)
    service._require_candidate = AsyncMock()
    session.execute.side_effect = OperationalError("lock", {}, RuntimeError("offline"))

    async def chunks():
        yield b"synthetic"

    with pytest.raises(OperationalError):
        asyncio.run(
            service.upload(
                DocumentUpload(filename="resume.pdf"),
                chunks(),
                organization_id=uuid4(),
                candidate_id=uuid4(),
                user_id=uuid4(),
                content_type="application/pdf",
                content_length=None,
            )
        )
    storage.save_pdf.assert_not_awaited()
