from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.document_chunks import get_document_chunk_service
from app.core.errors import ConflictError, NotFoundError
from app.main import app
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.user import User
from app.services.document_chunk import DocumentChunkService


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="chunks@example.com", password_hash="hash", is_active=True
    )
    chunk_set = DocumentChunkSet(
        id=uuid4(),
        document_id=uuid4(),
        source_document_sha256="a" * 64,
        source_text_sha256="b" * 64,
        source_char_count=8,
        page_count=1,
        chunker_version="char-window-v1",
        chunk_max_chars=1200,
        chunk_overlap_chars=150,
        chunk_count=1,
        created_at=datetime.now(UTC),
    )
    chunk = DocumentChunk(
        chunk_set_id=chunk_set.id,
        position=0,
        start_offset=0,
        end_offset=8,
        text="abcdefgh",
        sha256="a" * 64,
    )
    service = AsyncMock(spec=DocumentChunkService)
    service.build_for_user.return_value = (chunk_set, True)
    service.list_for_user.return_value = ([chunk_set], 1)
    service.get_for_user.return_value = chunk_set
    service.chunks_for_user.return_value = (chunk_set, [chunk])
    org, candidate = uuid4(), uuid4()
    path = f"/organizations/{org}/candidates/{candidate}/documents/{chunk_set.document_id}/chunks"
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_chunk_service] = lambda: service
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            service=service,
            chunk_set=chunk_set,
            path=path,
            org=org,
            candidate=candidate,
            user=user,
        )
    app.dependency_overrides.clear()


def test_build_returns_created_metadata_and_forwards_authenticated_scope(
    context,
) -> None:
    response = context.client.post(context.path, json={})
    assert response.status_code == 201
    assert response.json()["id"] == str(context.chunk_set.id)
    assert response.headers["cache-control"] == "private, no-store"
    assert "text" not in response.json() and "storage_key" not in response.json()
    assert context.service.build_for_user.await_args.kwargs == {
        "organization_id": context.org,
        "candidate_id": context.candidate,
        "user_id": context.user.id,
    }


def test_cached_generation_returns_200_and_same_id(context) -> None:
    context.service.build_for_user.return_value = (context.chunk_set, False)
    response = context.client.post(context.path, json={})
    assert response.status_code == 200 and response.json()["id"] == str(
        context.chunk_set.id
    )


@pytest.mark.parametrize(
    "payload", [{"force": True}, {"text": "untrusted"}, {"chunk_max_chars": 1000}]
)
def test_client_cannot_override_source_or_server_policy(context, payload: dict) -> None:
    assert context.client.post(context.path, json=payload).status_code == 422
    context.service.build_for_user.assert_not_awaited()


def test_history_page_exposes_total_and_pagination(context) -> None:
    response = context.client.get(context.path + "?limit=2&offset=3")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 2 and response.json()["offset"] == 3
    assert response.headers["cache-control"] == "private, no-store"


def test_set_metadata_is_retrievable_without_full_text(context) -> None:
    response = context.client.get(context.path + f"/{context.chunk_set.id}")
    assert response.status_code == 200 and "text" not in response.json()
    assert response.headers["cache-control"] == "private, no-store"


def test_chunk_page_contains_exact_offsets_and_source_metadata(context) -> None:
    response = context.client.get(
        context.path + f"/{context.chunk_set.id}/items?limit=2&offset=0"
    )
    assert response.status_code == 200 and response.json()["total"] == 1
    chunk = response.json()["items"][0]
    assert chunk["start_offset"] == 0 and chunk["end_offset"] == 8
    assert chunk["text"] == "abcdefgh"
    assert response.json()["chunk_set"]["source_text_sha256"] == "b" * 64
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("items", [False, True], ids=["history", "chunks"])
@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "limit=invalid"]
)
def test_invalid_pagination_never_reaches_service(
    context, items: bool, query: str
) -> None:
    suffix = f"/{context.chunk_set.id}/items" if items else ""
    assert context.client.get(context.path + suffix + "?" + query).status_code == 422
    assert not context.service.mock_calls


@pytest.mark.parametrize(
    "method, target",
    [("POST", "root"), ("GET", "root"), ("GET", "set"), ("GET", "items")],
)
def test_all_chunk_routes_require_bearer_auth(
    context, method: str, target: str
) -> None:
    app.dependency_overrides.pop(get_current_user)
    suffix = (
        ""
        if target == "root"
        else f"/{context.chunk_set.id}" + ("/items" if target == "items" else "")
    )
    assert (
        context.client.request(method, context.path + suffix, json={}).status_code
        == 401
    )
    assert not context.service.mock_calls


def test_non_member_gets_the_standard_hidden_resource_error(context) -> None:
    context.service.list_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND", message="Hidden."
    )
    response = context.client.get(context.path)
    assert (
        response.status_code == 404
        and response.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    )


def test_chunking_limit_uses_a_domain_conflict(context) -> None:
    context.service.build_for_user.side_effect = ConflictError(
        code="CHUNK_LIMIT_EXCEEDED", message="Limit."
    )
    response = context.client.post(context.path, json={})
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "CHUNK_LIMIT_EXCEEDED"
    )
