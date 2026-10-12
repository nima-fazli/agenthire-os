import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_chunking import chunk_text
from app.models.document_chunk import DocumentChunkSet
from app.repositories.document_chunk import DocumentChunkRepository


def context():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock())
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    scope = {
        "organization_id": uuid4(),
        "candidate_id": uuid4(),
        "document_id": uuid4(),
    }
    return session, DocumentChunkRepository(session), scope


def assert_scoped(statement, scope):
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "candidate_documents.organization_id =" in sql
    assert "candidate_documents.candidate_id =" in sql
    assert (
        "candidate_documents.status =" in sql and "document_extractions.status =" in sql
    )
    assert all(value in statement.compile().params.values() for value in scope.values())


def test_metadata_and_policy_lookups_are_tenant_scoped() -> None:
    session, repository, scope = context()
    asyncio.run(repository.get(**scope, chunk_set_id=uuid4()))
    assert_scoped(session.execute.await_args.args[0], scope)
    asyncio.run(
        repository.get_policy(
            **scope,
            source_text_sha256="a" * 64,
            chunker_version="char-window-v1",
            max_chars=1200,
            overlap_chars=150,
        )
    )
    statement = session.execute.await_args.args[0]
    assert_scoped(statement, scope)
    assert "document_chunk_sets.source_text_sha256 =" in str(statement)
    session.commit.assert_not_awaited()


def test_count_and_history_pages_use_the_same_scope_and_stable_order() -> None:
    session, repository, scope = context()
    asyncio.run(repository.list_sets(**scope, limit=2, offset=3))
    for call in session.execute.await_args_list:
        assert_scoped(call.args[0], scope)
    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "document_chunk_sets.created_at DESC, document_chunk_sets.id DESC" in sql
    assert "LIMIT" in sql and "OFFSET" in sql


def test_chunk_page_is_ordered_and_bound_to_its_document() -> None:
    session, repository, scope = context()
    chunk_set_id = uuid4()
    asyncio.run(
        repository.list_chunks(**scope, chunk_set_id=chunk_set_id, limit=2, offset=3)
    )
    statement = session.execute.await_args.args[0]
    assert_scoped(statement, scope)
    assert chunk_set_id in statement.compile().params.values()
    assert "ORDER BY document_chunks.position" in str(statement)
    session.commit.assert_not_awaited()


def test_repository_inserts_in_bounded_batches_and_never_commits() -> None:
    session, repository, _scope = context()
    chunks = chunk_text("x" * 501, max_chars=1, overlap_chars=0, max_count=501)
    chunk_set = DocumentChunkSet(id=uuid4(), chunk_count=len(chunks))
    assert asyncio.run(repository.create(chunk_set, chunks)) is chunk_set
    assert [len(call.args[1]) for call in session.execute.await_args_list] == [
        250,
        250,
        1,
    ]
    assert all(
        row["chunk_set_id"] == chunk_set.id
        for call in session.execute.await_args_list
        for row in call.args[1]
    )
    session.commit.assert_not_awaited()
