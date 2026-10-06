from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.jobs import get_job_service
from app.core.errors import NotFoundError
from app.main import app
from app.models.job import Job
from app.models.user import User
from app.services.job import JobService

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


def test_create_job_api() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=JobService
    )

    service.create.return_value = Job(
        id=job_id,
        organization_id=organization_id,
        title="Backend Engineer",
        description="Build backend systems.",
        status="draft",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.post(
            f"/organizations/{organization_id}/jobs",
            json={
                "title": " Backend Engineer ",
                "description": (
                    " Build backend systems. "
                ),
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_update_job_api() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=JobService
    )

    service.update_for_user.return_value = Job(
        id=job_id,
        organization_id=organization_id,
        title="Staff Backend Engineer",
        description="Backend work.",
        status="open",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.patch(
            f"/organizations/{organization_id}/jobs/{job_id}",
            json={
                "title": " Staff Backend Engineer ",
                "status": "open",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200

    body = response.json()

    assert body["title"] == "Staff Backend Engineer"
    assert body["status"] == "open"

    call = service.update_for_user.await_args

    assert call.args[0] == job_id

    data = call.args[1]

    assert data.title == "Staff Backend Engineer"
    assert data.status == "open"

    assert call.kwargs == {
        "organization_id": organization_id,
        "user_id": user.id,
    }


def test_update_job_api_returns_not_found() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()

    service = AsyncMock(
        spec=JobService
    )

    service.update_for_user.side_effect = NotFoundError(
        code="JOB_NOT_FOUND",
        message="Job was not found.",
        details={
            "organization_id": str(
                organization_id
            ),
            "job_id": str(
                job_id
            ),
        },
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.patch(
            f"/organizations/{organization_id}/jobs/{job_id}",
            json={
                "status": "closed",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert (
        response.json()["error"]["code"]
        == "JOB_NOT_FOUND"
    )


def test_update_job_api_requires_authentication() -> None:
    response = client.patch(
        f"/organizations/{uuid4()}/jobs/{uuid4()}",
        json={
            "status": "closed",
        },
    )

    assert response.status_code == 401
    assert (
        response.json()["error"]["code"]
        == "INVALID_ACCESS_TOKEN"
    )


def test_list_jobs_api() -> None:
    user = make_user()
    organization_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=JobService
    )

    service.list_for_user.return_value = [
        Job(
            id=uuid4(),
            organization_id=organization_id,
            title="Backend Engineer",
            description="Backend work.",
            status="draft",
            created_at=now,
            updated_at=now,
        ),
        Job(
            id=uuid4(),
            organization_id=organization_id,
            title="AI Engineer",
            description="AI work.",
            status="open",
            created_at=now,
            updated_at=now,
        ),
    ]

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/jobs"
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_job_api() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=JobService
    )

    service.get_for_user.return_value = Job(
        id=job_id,
        organization_id=organization_id,
        title="Backend Engineer",
        description="Backend work.",
        status="open",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/jobs/{job_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["id"] == str(
        job_id
    )


def test_get_job_api_returns_not_found() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()

    service = AsyncMock(
        spec=JobService
    )

    service.get_for_user.side_effect = NotFoundError(
        code="JOB_NOT_FOUND",
        message="Job was not found.",
        details={
            "organization_id": str(
                organization_id
            ),
            "job_id": str(
                job_id
            ),
        },
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/jobs/{job_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert (
        response.json()["error"]["code"]
        == "JOB_NOT_FOUND"
    )


def test_job_api_hides_organization_from_non_member() -> None:
    user = make_user()
    organization_id = uuid4()

    service = AsyncMock(
        spec=JobService
    )

    service.list_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND",
        message="Organization was not found.",
        details={
            "organization_id": str(
                organization_id
            ),
        },
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_job_service
    ] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/jobs"
        )
    finally:
        clear_overrides()

    assert response.status_code == 404

    assert response.json()["error"]["code"] == (
        "ORGANIZATION_NOT_FOUND"
    )


def test_job_api_requires_authentication() -> None:
    organization_id = uuid4()

    response = client.get(
        f"/organizations/{organization_id}/jobs"
    )

    assert response.status_code == 401

    assert response.json()["error"]["code"] == (
        "INVALID_ACCESS_TOKEN"
    )
