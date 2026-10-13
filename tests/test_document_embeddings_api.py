from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.document_embeddings import get_document_embedding_service
from app.core.errors import AppError, ConflictError, NotFoundError
from app.main import app
from app.models.user import User
from app.services.document_embeddings import DocumentEmbeddingService

PUBLIC_FIELDS = {
    "id",
    "chunk_set_id",
    "model_tag",
    "model_digest",
    "encoding_version",
    "source_text_sha256",
    "chunk_count",
    "dimensions",
    "status",
    "attempts",
    "failure_code",
    "completed_at",
    "created_at",
    "updated_at",
}


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="owner@example.com", password_hash="synthetic", is_active=True
    )
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        chunk_set_id=uuid4(),
        model_tag="qwen3-embedding:0.6b",
        model_digest="a" * 64,
        encoding_version="qwen3-raw-l2-v1",
        source_text_sha256="b" * 64,
        chunk_count=2,
        status="queued",
        attempts=0,
        failure_code=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
        lease_token=uuid4(),
        lease_expires_at=now,
        text="Synthetic private resume text",
        embeddings=[[1.0] + [0.0] * 1023],
    )
    service = AsyncMock(spec=DocumentEmbeddingService)
    service.request.return_value = (job, True)
    service.get.return_value = job
    org, candidate, document = uuid4(), uuid4(), uuid4()
    path = (
        f"/organizations/{org}/candidates/{candidate}"
        f"/documents/{document}/embedding-jobs"
    )
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_embedding_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                user=user,
                job=job,
                service=service,
                org=org,
                candidate=candidate,
                document=document,
                path=path,
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("created", [True, False], ids=["new", "existing"])
def test_request_preserves_scope_and_private_response_contract(context, created):
    context.service.request.return_value = (context.job, created)
    response = context.client.post(context.path, json={"retry": True})
    assert response.status_code == (202 if created else 200)
    assert response.headers["cache-control"] == "private, no-store"
    assert set(response.json()) == PUBLIC_FIELDS
    assert response.json()["id"] == str(context.job.id)
    assert response.json()["dimensions"] == 1024
    call = context.service.request.await_args
    assert call.args[0] == context.document
    assert call.args[1].retry is True
    assert call.kwargs == {
        "organization_id": context.org,
        "candidate_id": context.candidate,
        "user_id": context.user.id,
    }


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed"])
def test_status_lookup_hides_vectors_text_and_leases(context, status):
    context.job.status = status
    if status in {"succeeded", "failed"}:
        context.job.completed_at = datetime.now(UTC)
    if status == "failed":
        context.job.failure_code = "EMBEDDING_MODEL_CHANGED"
    response = context.client.get(f"{context.path}/{context.job.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert set(response.json()) == PUBLIC_FIELDS
    assert response.json()["status"] == status
    context.service.get.assert_awaited_once_with(
        context.document,
        context.job.id,
        organization_id=context.org,
        candidate_id=context.candidate,
        user_id=context.user.id,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"model_tag": "remote-provider"},
        {"dimensions": 1024},
        {"status": "succeeded"},
        {"retry": "true"},
        {"retry": 1},
    ],
    ids=["model", "dimensions", "status", "string-retry", "integer-retry"],
)
def test_request_rejects_server_fields_and_non_boolean_retry(context, payload):
    response = context.client.post(context.path, json=payload)
    assert response.status_code == 422
    context.service.request.assert_not_awaited()


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_embedding_endpoints_require_authentication(context, method):
    app.dependency_overrides.pop(get_current_user)
    path = context.path if method == "POST" else f"{context.path}/{context.job.id}"
    response = context.client.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"
    context.service.request.assert_not_awaited()
    context.service.get.assert_not_awaited()


@pytest.mark.parametrize("method", ["POST", "GET"])
@pytest.mark.parametrize("code", ["ORGANIZATION_NOT_FOUND", "DOCUMENT_NOT_FOUND"])
def test_hidden_resources_keep_the_standard_error_contract(context, method, code):
    operation = context.service.request if method == "POST" else context.service.get
    operation.side_effect = NotFoundError(code=code, message="Resource was not found.")
    path = context.path if method == "POST" else f"{context.path}/{context.job.id}"
    response = context.client.request(method, path, json={})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": code, "message": "Resource was not found.", "details": {}}
    }


@pytest.mark.parametrize("disabled", [True, False], ids=["disabled", "chunks-pending"])
def test_unavailable_feature_and_pending_source_return_domain_errors(context, disabled):
    if disabled:
        error = AppError(
            code="SEMANTIC_DISABLED",
            message="Local semantic processing is disabled.",
            status_code=503,
        )
    else:
        error = ConflictError(
            code="DOCUMENT_CHUNKS_NOT_READY",
            message="Build source chunks before requesting embeddings.",
        )
    context.service.request.side_effect = error
    response = context.client.post(context.path, json={})
    assert response.status_code == (503 if disabled else 409)
    assert response.json()["error"]["code"] == error.code
