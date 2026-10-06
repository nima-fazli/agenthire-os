from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.candidates import (
    get_candidate_service,
)
from app.core.errors import NotFoundError
from app.main import app
from app.models.candidate import Candidate
from app.models.user import User
from app.services.candidate import CandidateService

client = TestClient(
    app
)


def make_user() -> User:
    return User(
        id=uuid4(),
        email="recruiter@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )


def override_authenticated_user(
    user: User,
) -> None:
    app.dependency_overrides[
        get_current_user
    ] = lambda: user


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_create_candidate_api() -> None:
    user = make_user()
    organization_id = uuid4()
    candidate_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=CandidateService
    )

    service.create.return_value = Candidate(
        id=candidate_id,
        organization_id=organization_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone=None,
        location="Amsterdam",
        headline="AI Engineer",
        summary=None,
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_candidate_service
    ] = lambda: service

    try:
        response = client.post(
            f"/organizations/{organization_id}/candidates",
            json={
                "full_name": " Ada Lovelace ",
                "email": " ADA@EXAMPLE.COM ",
                "location": " Amsterdam ",
                "headline": " AI Engineer ",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201

    body = response.json()

    assert body["id"] == str(
        candidate_id
    )
    assert body["email"] == "ada@example.com"

    call = service.create.await_args

    data = call.args[0]

    assert data.full_name == "Ada Lovelace"
    assert data.email == "ada@example.com"

    assert call.kwargs == {
        "organization_id": organization_id,
        "user_id": user.id,
    }


def test_list_candidates_api() -> None:
    user = make_user()
    organization_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=CandidateService
    )

    service.list_for_user.return_value = [
        Candidate(
            id=uuid4(),
            organization_id=organization_id,
            full_name="Ada Lovelace",
            created_at=now,
            updated_at=now,
        ),
        Candidate(
            id=uuid4(),
            organization_id=organization_id,
            full_name="Alan Turing",
            created_at=now,
            updated_at=now,
        ),
    ]

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_candidate_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/candidates"
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_candidate_api() -> None:
    user = make_user()
    organization_id = uuid4()
    candidate_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=CandidateService
    )

    service.get_for_user.return_value = Candidate(
        id=candidate_id,
        organization_id=organization_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_candidate_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/candidates/{candidate_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 200

    assert response.json()["id"] == str(
        candidate_id
    )


def test_get_candidate_api_returns_not_found() -> None:
    user = make_user()
    organization_id = uuid4()
    candidate_id = uuid4()

    service = AsyncMock(
        spec=CandidateService
    )

    service.get_for_user.side_effect = (
        NotFoundError(
            code="CANDIDATE_NOT_FOUND",
            message="Candidate was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "candidate_id": str(
                    candidate_id
                ),
            },
        )
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_candidate_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/candidates/{candidate_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 404

    assert (
        response.json()["error"]["code"]
        == "CANDIDATE_NOT_FOUND"
    )


def test_candidate_api_hides_organization_from_non_member() -> None:
    user = make_user()
    organization_id = uuid4()

    service = AsyncMock(
        spec=CandidateService
    )

    service.list_for_user.side_effect = (
        NotFoundError(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
            },
        )
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_candidate_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/candidates"
        )
    finally:
        clear_overrides()

    assert response.status_code == 404

    assert (
        response.json()["error"]["code"]
        == "ORGANIZATION_NOT_FOUND"
    )


def test_candidate_api_requires_authentication() -> None:
    organization_id = uuid4()

    response = client.get(
        f"/organizations/{organization_id}/candidates"
    )

    assert response.status_code == 401

    assert (
        response.json()["error"]["code"]
        == "INVALID_ACCESS_TOKEN"
    )
