import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.document_search import DocumentSearchRepository
from app.schemas.document_search import DocumentSearchQuery


def statement(**kwargs):
    return DocumentSearchRepository.statement(
        organization_id=uuid4(),
        user_id=uuid4(),
        data=DocumentSearchQuery(q="Python SQL", **kwargs),
    )


def test_statement_checks_membership_tenant_and_readiness() -> None:
    org, user = uuid4(), uuid4()
    value = DocumentSearchRepository.statement(
        organization_id=org, user_id=user, data=DocumentSearchQuery(q="Python")
    )
    sql = str(value.compile(dialect=postgresql.dialect()))
    assert "EXISTS" in sql and "organization_memberships.user_id =" in sql
    assert "candidate_documents.organization_id =" in sql
    assert (
        "candidate_documents.status =" in sql and "document_extractions.status =" in sql
    )
    assert (
        org in value.compile().params.values()
        and user in value.compile().params.values()
    )


def test_only_latest_set_is_searchable_with_deterministic_ties() -> None:
    sql = str(statement().compile(dialect=postgresql.dialect()))
    assert "document_chunk_sets_1.document_id = candidate_documents.id" in sql
    assert "document_chunk_sets_1.created_at DESC, document_chunk_sets_1.id DESC" in sql
    assert "LIMIT" in sql and "@@" in sql and "ts_rank_cd" in sql
    assert (
        "search_page.score DESC, search_page.document_id, search_page.chunk_set_id, search_page.chunk_position"
        in sql
    )


def test_filters_are_bound_inside_the_authorized_match_scope() -> None:
    candidate, document = uuid4(), uuid4()
    value = statement(candidate_id=candidate, document_id=document, limit=2, offset=3)
    sql = str(value.compile(dialect=postgresql.dialect()))
    assert "candidate_documents.candidate_id =" in sql
    assert (
        candidate in value.compile().params.values()
        and document in value.compile().params.values()
    )
    assert 2 in value.compile().params.values() and 3 in value.compile().params.values()


def test_page_and_count_share_one_statement_and_preserve_empty_pages() -> None:
    sql = str(statement(offset=1000).compile(dialect=postgresql.dialect()))
    assert "search_total AS" in sql and "search_page AS" in sql
    assert "search_total LEFT OUTER JOIN search_page ON true" in sql
    assert "storage_key" not in sql and "lease_token" not in sql


def test_empty_page_keeps_total_and_repository_never_commits() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [{"total": 7, "chunk_set_id": None}]
    session.execute.side_effect = [MagicMock(), result]
    items, total = asyncio.run(
        DocumentSearchRepository(session).search(
            organization_id=uuid4(),
            user_id=uuid4(),
            data=DocumentSearchQuery(q="Python", offset=50),
            timeout_ms=1500,
        )
    )
    assert items == [] and total == 7
    timeout = session.execute.await_args_list[0].args[0]
    assert (
        "1500ms" in timeout.compile().params.values()
        and True in timeout.compile().params.values()
    )
    session.commit.assert_not_called()


def test_hit_projection_removes_internal_count_column() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {"total": 1, "chunk_set_id": uuid4(), "score": 0.5}
    ]
    session.execute.side_effect = [MagicMock(), result]
    items, total = asyncio.run(
        DocumentSearchRepository(session).search(
            organization_id=uuid4(),
            user_id=uuid4(),
            data=DocumentSearchQuery(q="Python"),
            timeout_ms=1500,
        )
    )
    assert total == 1 and "total" not in items[0]
