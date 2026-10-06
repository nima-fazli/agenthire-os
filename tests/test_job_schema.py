from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.job import JobCreate, JobRead


def test_job_create_normalizes_text() -> None:
    job = JobCreate(
        title="  Senior Python Engineer  ",
        description="  Build AI systems.  ",
    )

    assert job.title == "Senior Python Engineer"
    assert job.description == "Build AI systems."


def test_job_create_defaults_to_draft() -> None:
    job = JobCreate(
        title="Senior Python Engineer",
        description="Build AI systems.",
    )

    assert job.status == "draft"


def test_job_create_rejects_invalid_status() -> None:
    with pytest.raises(
        ValidationError
    ):
        JobCreate(
            title="Senior Python Engineer",
            description="Build AI systems.",
            status="deleted",
        )


def test_job_create_rejects_blank_title() -> None:
    with pytest.raises(
        ValidationError
    ):
        JobCreate(
            title="   ",
            description="Build AI systems.",
        )


def test_job_read_supports_attribute_objects() -> None:
    job_id = uuid4()
    organization_id = uuid4()
    now = datetime.now(UTC)

    source = SimpleNamespace(
        id=job_id,
        organization_id=organization_id,
        title="Senior Python Engineer",
        description="Build AI systems.",
        status="open",
        created_at=now,
        updated_at=now,
    )

    job = JobRead.model_validate(
        source
    )

    assert job.id == job_id
    assert job.organization_id == organization_id
    assert job.status == "open"
