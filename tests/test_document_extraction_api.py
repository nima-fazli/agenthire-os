from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.candidate_documents import get_document_extraction_service
from app.core.errors import ConflictError, NotFoundError
from app.main import app
from app.models.document_extraction import DocumentExtraction
from app.models.user import User
from app.services.document_extraction import DocumentExtractionService


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="owner@example.com", password_hash="hash", is_active=True
    )
    now = datetime.now(UTC)
    extraction = DocumentExtraction(
        document_id=uuid4(),
        status="queued",
        attempts=0,
        page_count=None,
        text=None,
        failure_code=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
        lease_token=uuid4(),
    )
    service = AsyncMock(spec=DocumentExtractionService)
    service.request_for_user.return_value = extraction
    service.get_for_user.return_value = extraction
    service.text_for_user.return_value = extraction
    org, candidate = uuid4(), uuid4()
    path = f"/organizations/{org}/candidates/{candidate}/documents/{extraction.document_id}/extraction"
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_extraction_service] = lambda: service
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            user=user,
            service=service,
            extraction=extraction,
            org=org,
            candidate=candidate,
            path=path,
        )
    app.dependency_overrides.clear()


def test_request_is_accepted_and_only_retry_is_client_owned(context) -> None:
    response = context.client.post(context.path, json={"retry": True})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.headers["cache-control"] == "private, no-store"
    assert "lease_token" not in response.json() and "text" not in response.json()
    call = context.service.request_for_user.await_args
    assert call.args[1].retry is True
    assert call.kwargs == {
        "organization_id": context.org,
        "candidate_id": context.candidate,
        "user_id": context.user.id,
    }


@pytest.mark.parametrize(
    "payload", [{"status": "succeeded"}, {"retry": "true"}, {"attempts": 0}]
)
def test_request_rejects_extra_and_coerced_fields(context, payload: dict) -> None:
    assert context.client.post(context.path, json=payload).status_code == 422
    context.service.request_for_user.assert_not_awaited()


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_existing_finished_job_returns_200(context, status: str) -> None:
    context.extraction.status = status
    assert context.client.post(context.path, json={}).status_code == 200


def test_metadata_does_not_include_extracted_text_or_lease(context) -> None:
    response = context.client.get(context.path)
    assert response.status_code == 200
    assert set(response.json()) == {
        "document_id",
        "status",
        "attempts",
        "page_count",
        "failure_code",
        "completed_at",
        "created_at",
        "updated_at",
    }


def test_successful_text_is_private(context) -> None:
    context.extraction.status = "succeeded"
    context.extraction.text = "Private candidate resume"
    context.extraction.page_count = 1
    response = context.client.get(context.path + "/text")
    assert response.status_code == 200
    assert response.json()["text"] == "Private candidate resume"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "method, suffix", [("POST", ""), ("GET", ""), ("GET", "/text")]
)
def test_extraction_endpoints_require_authentication(
    context, method: str, suffix: str
) -> None:
    app.dependency_overrides.pop(get_current_user)
    response = context.client.request(method, context.path + suffix, json={})
    assert response.status_code == 401
    assert not context.service.mock_calls


def test_non_member_gets_standard_hidden_resource_error(context) -> None:
    context.service.get_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND", message="Hidden."
    )
    response = context.client.get(context.path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


def test_pending_text_returns_a_domain_conflict(context) -> None:
    context.service.text_for_user.side_effect = ConflictError(
        code="EXTRACTION_NOT_READY", message="Not ready."
    )
    response = context.client.get(context.path + "/text")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXTRACTION_NOT_READY"
