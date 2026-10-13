import asyncio
import hashlib
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.semantic_embeddings import (
    DIMENSIONS,
    EmbeddingFailure,
    ModelIdentity,
    SourceChunk,
)
from app.repositories.document_embeddings import (
    DocumentEmbeddingRepository,
    EmbeddingTask,
)
from app.schemas.document_embeddings import EmbeddingRequest
from app.services import document_embeddings as module
from app.services.document_embeddings import (
    DocumentEmbeddingService,
    EmbeddingProcessor,
)
from app.workers import document_embeddings as worker
from app.workers.document_embeddings import run_worker


def job(**changes):
    now = datetime.now(UTC)
    fields = {
        "id": uuid4(), "chunk_set_id": uuid4(), "model_tag": "qwen3-embedding:0.6b",
        "model_digest": "a" * 64, "encoding_version": "qwen3-raw-l2-v1",
        "source_text_sha256": "b" * 64, "chunk_count": 1,
        "status": "queued", "attempts": 0, "failure_code": None,
        "completed_at": None, "created_at": now, "updated_at": now,
    }
    return SimpleNamespace(**(fields | changes))


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    documents, encoder = AsyncMock(), AsyncMock()
    encoder.identity.return_value = ModelIdentity("a" * 64)
    settings = Settings(_env_file=None, semantic_enabled=True)
    service = DocumentEmbeddingService(session, documents, encoder, settings)
    repo = AsyncMock(spec=DocumentEmbeddingRepository)
    repo.latest_source.return_value = SimpleNamespace(id=uuid4(), chunk_count=1)
    repo.for_space.return_value = None
    repo.create.return_value = job()
    service._repository = repo
    return SimpleNamespace(session=session, documents=documents, encoder=encoder,
        settings=settings, service=service, repo=repo, document_id=uuid4(),
        scope={"organization_id": uuid4(), "candidate_id": uuid4(), "user_id": uuid4()})


def request(context, retry=False):
    return asyncio.run(context.service.request(context.document_id, EmbeddingRequest(retry=retry), **context.scope))


def test_creation_and_repeat_pin_server_identity_and_commit_once(context):
    result, created = request(context)
    assert created and result.model_digest == "a" * 64
    context.session.commit.assert_awaited_once()
    context.repo.for_space.return_value = job(id=result.id)
    again, created = request(context)
    assert not created and again.id == result.id
    context.repo.create.assert_awaited_once()


@pytest.mark.parametrize("denied", ["membership", "disabled"])
def test_denied_request_never_contacts_the_model(context, denied):
    if denied == "membership":
        context.documents.get_for_user.side_effect = NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Missing.")
    else:
        context.settings.semantic_enabled = False
    with pytest.raises(AppError):
        request(context)
    context.encoder.identity.assert_not_awaited()
    context.repo.create.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("issue", ["unavailable", "not_ready", "too_large", "retry_limit"])
def test_failures_rollback_without_creating_jobs(context, issue):
    if issue == "unavailable":
        context.encoder.identity.side_effect = EmbeddingFailure("EMBEDDING_MODEL_CHANGED")
    elif issue == "not_ready":
        context.repo.latest_source.return_value = None
    elif issue == "too_large":
        context.repo.latest_source.return_value.chunk_count = 1001
    else:
        context.repo.for_space.return_value = job(status="failed", attempts=3)
    with pytest.raises(AppError):
        request(context, retry=True)
    context.session.rollback.assert_awaited_once()
    context.session.commit.assert_not_awaited()


def test_failed_job_retry_preserves_identity(context):
    failed = job(status="failed", attempts=1)
    context.repo.for_space.return_value = failed
    context.repo.requeue.return_value = job(id=failed.id)
    result, created = request(context, retry=True)
    assert not created and result.id == failed.id
    context.repo.requeue.assert_awaited_once_with(failed)


def test_status_lookup_uses_all_parent_identifiers(context):
    context.repo.get_scoped.return_value = None
    identifier = uuid4()
    with pytest.raises(NotFoundError):
        asyncio.run(context.service.get(context.document_id, identifier, **context.scope))
    context.repo.get_scoped.assert_awaited_once_with(identifier,
        organization_id=context.scope["organization_id"], candidate_id=context.scope["candidate_id"],
        document_id=context.document_id)


def test_repository_sql_preserves_scope_source_and_lease_fencing():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.one_or_none.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    repo = DocumentEmbeddingRepository(session)
    ids = [uuid4() for _ in range(4)]
    task = EmbeddingTask(ids[3], uuid4(), "a" * 64, 1, uuid4())

    async def run():
        await repo.latest_source(organization_id=ids[0], candidate_id=ids[1], document_id=ids[2])
        await repo.get_scoped(ids[3], organization_id=ids[0], candidate_id=ids[1], document_id=ids[2])
        await repo.claim(max_attempts=3, lease_seconds=300, job_id=ids[3])
        assert not await repo.renew(task, 300)
        assert not await repo.finish(task, (), (), "EMBEDDING_INTERNAL_ERROR")

    asyncio.run(run())
    sql = [str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
           for call in session.execute.await_args_list]
    assert all(str(identifier) in sql[1] for identifier in ids)
    assert "FOR UPDATE OF candidate_documents" in sql[0]
    assert "SKIP LOCKED" in sql[4]
    assert all(str(ids[3]) in value for value in sql[2:5])
    assert all("lease_token" in value and "clock_timestamp" in value for value in sql[-2:])
    assert "source_text_sha256" in sql[-1] and "document_extractions.status" in sql[-1]
    session.add_all.assert_not_called()
    session.commit.assert_not_called()


@pytest.fixture
def processor_context(monkeypatch):
    session = AsyncMock(spec=AsyncSession)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=False)
    sessions = MagicMock(return_value=manager)
    repo = AsyncMock(spec=DocumentEmbeddingRepository)
    task = EmbeddingTask(uuid4(), uuid4(), "a" * 64, 3, uuid4())
    repo.claim.return_value = task
    repo.chunks.return_value = tuple(SourceChunk(i, f"text-{i}", hashlib.sha256(f"text-{i}".encode()).hexdigest()) for i in range(3))
    repo.renew.return_value = True
    repo.finish.return_value = True
    monkeypatch.setattr(module, "DocumentEmbeddingRepository", lambda _: repo)
    encoder = AsyncMock()

    async def encode(texts, identity):
        return tuple([1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts)

    encoder.encode.side_effect = encode
    processor = EmbeddingProcessor(sessions, encoder, Settings(_env_file=None, embedding_batch_size=2))
    return SimpleNamespace(session=session, repo=repo, task=task, encoder=encoder, processor=processor)


def test_processor_publishes_complete_vectors_after_each_batch_renews(processor_context):
    c = processor_context
    assert asyncio.run(c.processor.run_one(job_id=c.task.id))
    assert c.encoder.encode.await_count == 2 and c.repo.renew.await_count == 2
    task, chunks, vectors, failure = c.repo.finish.await_args.args
    assert task == c.task and len(chunks) == len(vectors) == 3 and failure is None
    assert all(len(vector) == DIMENSIONS for vector in vectors)


@pytest.mark.parametrize("issue", ["lost", "empty", "malformed", "cancelled"])
def test_processor_never_publishes_unowned_or_partial_results(processor_context, issue):
    c = processor_context
    if issue == "lost":
        c.repo.renew.return_value = False
    elif issue == "empty":
        c.repo.claim.return_value = None
    elif issue == "cancelled":
        c.encoder.encode.side_effect = asyncio.CancelledError()
    else:
        c.encoder.encode.side_effect = None
        c.encoder.encode.return_value = ()
    if issue == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(c.processor.run_one())
    else:
        result = asyncio.run(c.processor.run_one())
        assert result == (issue != "empty")
    if issue == "malformed":
        assert c.repo.finish.await_args.args[-1] == "EMBEDDING_VECTOR_INVALID"
    else:
        c.repo.finish.assert_not_awaited()


def test_worker_shutdown_cancels_inflight_processing(tmp_path):
    async def run():
        stop, entered = asyncio.Event(), asyncio.Event()
        processor = AsyncMock()

        async def process():
            entered.set()
            await asyncio.Event().wait()

        processor.run_one.side_effect = process
        task = asyncio.create_task(run_worker(processor, Settings(_env_file=None), stop, tmp_path / "heartbeat"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        assert (tmp_path / "heartbeat").is_file()

    asyncio.run(run())


@pytest.mark.parametrize("age", [0, 5, 90])
def test_embedding_health_accepts_a_recent_heartbeat(tmp_path, monkeypatch, age):
    path = tmp_path / "heartbeat"
    monkeypatch.setattr(worker.time, "monotonic", lambda: 1000)
    path.write_text(str(1000 - age), encoding="ascii")
    assert worker.healthy(path)
    worker.heartbeat(path)
    assert path.read_text(encoding="ascii") == "1000"
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize(
    "value",
    [None, "800", "1001", "nan", "inf", "invalid"],
    ids=["missing", "stale", "future", "nan", "infinite", "malformed"],
)
def test_embedding_health_rejects_missing_or_invalid_heartbeat(
    tmp_path, monkeypatch, value
):
    path = tmp_path / "heartbeat"
    monkeypatch.setattr(worker.time, "monotonic", lambda: 1000)
    if value is not None:
        path.write_text(value, encoding="ascii")
    assert not worker.healthy(path)


@pytest.mark.parametrize("fresh", [True, False], ids=["healthy", "missing"])
def test_healthcheck_cli_does_not_import_application_runtime(tmp_path, fresh):
    if fresh:
        (tmp_path / "agenthire-embedding.heartbeat").write_text(
            str(time.monotonic()), encoding="ascii"
        )
    environment = os.environ.copy()
    environment.update(
        {
            "TMPDIR": str(tmp_path),
            "TEMP": str(tmp_path),
            "TMP": str(tmp_path),
            "AGENTHIRE_EXTRACTION_TIMEOUT_SECONDS": "invalid-for-runtime-settings",
        }
    )
    probe = """
import runpy
import sys

class RejectRuntimeImports:
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            "app.core", "app.db", "app.services", "app.repositories",
            "app.models", "sqlalchemy", "pydantic", "pydantic_settings",
        )
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise RuntimeError("Healthcheck imported application runtime.")
        return None

sys.meta_path.insert(0, RejectRuntimeImports())
sys.argv = ["app.workers.document_embeddings", "--healthcheck"]
runpy.run_module("app.workers.document_embeddings", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (0 if fresh else 1), result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
