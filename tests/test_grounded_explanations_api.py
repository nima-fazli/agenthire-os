from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.grounded_explanations import get_explanation_service
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.grounded_explanations import render
from app.main import app
from app.schemas.grounded_explanations import GroundedExplanation
from app.services.grounded_explanations import GroundedExplanationService
from scripts.grounded_explanations_evaluation import example_snapshot, load_reference


@pytest.fixture
def context():
    org, user, job, candidate = (uuid4() for _ in range(4))
    snapshot = example_snapshot(load_reference()["cases"][-1])
    service = AsyncMock(spec=GroundedExplanationService)
    service.explain.return_value = GroundedExplanation(job_id=job, candidate_id=candidate, candidate_name="Synthetic",
        profile_revision=1, profile_updated_at=snapshot.profile_updated_at, observed_at=snapshot.observed_at,
        validated_at=datetime.now(UTC), language="fa", generator_used=False, elapsed_ms=1,
        summary=snapshot.summary, **render(snapshot, {}, "fa"))
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user)
    app.dependency_overrides[get_explanation_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, service=service,
                path=f"/organizations/{org}/jobs/{job}/candidates/{candidate}/grounded-explanation",
                scope={"organization_id": org, "user_id": user, "job_id": job, "candidate_id": candidate})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_post_is_authenticated_private_and_passes_scope(context):
    response = context.client.post(context.path, json={})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert response.json()["explanation_version"] == "extractive-brief-v1"
    assert context.service.explain.await_args.kwargs == context.scope


def test_authentication_is_required_before_service(context):
    app.dependency_overrides.pop(get_current_user)
    assert context.client.post(context.path, json={}).status_code == 401
    context.service.explain.assert_not_awaited()


@pytest.mark.parametrize("payload", [{"prompt": "override"}, {"language": "de"}, {"model": "external"}])
def test_invalid_requests_never_reach_generation(context, payload):
    assert context.client.post(context.path, json=payload).status_code == 422
    context.service.explain.assert_not_awaited()


@pytest.mark.parametrize("error,status", [
    (AppError(code="EXPLANATIONS_DISABLED", message="Disabled.", status_code=503), 503),
    (ConflictError(code="EXPLANATION_SNAPSHOT_CHANGED", message="Retry."), 409),
    (NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Hidden."), 404),
])
def test_failures_keep_existing_safe_error_contract(context, error, status):
    context.service.explain.side_effect = error
    response = context.client.post(context.path, json={})
    assert response.status_code == status and response.json()["error"]["code"] == error.code
