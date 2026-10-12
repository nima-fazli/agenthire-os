from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.document_search import get_document_search_service
from app.core.errors import AppError, NotFoundError
from app.main import app
from app.models.user import User
from app.schemas.document_search import DocumentSearchHit, DocumentSearchPage
from app.services.document_search import DocumentSearchService


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="search@example.com", password_hash="hash", is_active=True
    )
    service = AsyncMock(spec=DocumentSearchService)
    hit = DocumentSearchHit(
        document_id=uuid4(),
        candidate_id=uuid4(),
        candidate_name="Ada",
        filename="resume.pdf",
        chunk_set_id=uuid4(),
        chunk_position=0,
        start_offset=0,
        end_offset=10,
        text="Python SQL",
        chunk_sha256="a" * 64,
        source_document_sha256="b" * 64,
        source_text_sha256="c" * 64,
        score=0.5,
    )
    service.search_for_user.return_value = DocumentSearchPage(
        items=[hit], total=1, limit=10, offset=0
    )
    org = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_search_service] = lambda: service
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            service=service,
            user=user,
            org=org,
            path=f"/organizations/{org}/document-search",
            hit=hit,
        )
    app.dependency_overrides.clear()


def test_private_search_returns_source_and_authenticated_scope(context) -> None:
    response = context.client.get(context.path, params={"q": "Python SQL"})
    assert (
        response.status_code == 200
        and response.headers["cache-control"] == "private, no-store"
    )
    assert response.json()["search_version"] == "simple-fold-v1"
    assert response.json()["items"][0]["chunk_set_id"] == str(context.hit.chunk_set_id)
    assert "storage_key" not in response.text and "lease_token" not in response.text
    assert context.service.search_for_user.await_args.kwargs == {
        "organization_id": context.org,
        "user_id": context.user.id,
    }


def test_filters_and_pagination_are_forwarded_as_validated_data(context) -> None:
    candidate, document = uuid4(), uuid4()
    response = context.client.get(
        context.path,
        params={
            "q": "مهندس نرم افزار",
            "candidate_id": str(candidate),
            "document_id": str(document),
            "limit": 2,
            "offset": 3,
        },
    )
    assert response.status_code == 200
    data = context.service.search_for_user.await_args.args[0]
    assert (
        data.q == "مهندس نرم افزار"
        and data.candidate_id == candidate
        and data.document_id == document
    )
    assert data.limit == 2 and data.offset == 3


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": " "},
        {"q": "& |"},
        {"q": "x" * 257},
        {"q": "word " * 17},
        {"q": "python", "limit": 0},
        {"q": "python", "limit": 51},
        {"q": "python", "offset": -1},
        {"q": "python", "offset": 1001},
        {"q": "python", "user_id": str(uuid4())},
        {"q": "py\x00thon"},
    ],
    ids=[
        "missing",
        "blank",
        "operators",
        "long",
        "terms",
        "zero-limit",
        "large-limit",
        "negative-offset",
        "large-offset",
        "user-override",
        "nul",
    ],
)
def test_invalid_query_never_reaches_search(context, params: dict) -> None:
    assert context.client.get(context.path, params=params).status_code == 422
    context.service.search_for_user.assert_not_awaited()


def test_missing_bearer_token_is_rejected(context) -> None:
    app.dependency_overrides.pop(get_current_user)
    assert context.client.get(context.path, params={"q": "python"}).status_code == 401
    context.service.search_for_user.assert_not_awaited()


def test_non_member_organization_is_hidden(context) -> None:
    context.service.search_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND", message="Hidden."
    )
    response = context.client.get(context.path, params={"q": "python"})
    assert (
        response.status_code == 404
        and response.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    )


def test_search_deadline_returns_safe_503(context) -> None:
    context.service.search_for_user.side_effect = AppError(
        code="DOCUMENT_SEARCH_TIMEOUT", message="Search timed out.", status_code=503
    )
    response = context.client.get(context.path, params={"q": "python"})
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "DOCUMENT_SEARCH_TIMEOUT"
    )


def test_operator_like_input_remains_literal_query_text(context) -> None:
    value = "python OR postgres"
    assert context.client.get(context.path, params={"q": value}).status_code == 200
    assert context.service.search_for_user.await_args.args[0].q == value
