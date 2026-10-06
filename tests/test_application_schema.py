from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
)


def test_application_create_accepts_candidate_and_job_ids() -> None:
    job_id = uuid4()
    candidate_id = uuid4()

    application = ApplicationCreate(
        job_id=job_id,
        candidate_id=candidate_id,
    )

    assert application.job_id == job_id
    assert (
        application.candidate_id
        == candidate_id
    )


def test_application_create_rejects_invalid_ids() -> None:
    with pytest.raises(
        ValidationError
    ):
        ApplicationCreate(
            job_id="not-a-uuid",
            candidate_id="also-not-a-uuid",
        )


def test_application_read_supports_attribute_objects() -> None:
    application_id = uuid4()
    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()
    now = datetime.now(UTC)

    source = SimpleNamespace(
        id=application_id,
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
        created_at=now,
        updated_at=now,
    )

    application = ApplicationRead.model_validate(
        source
    )

    assert application.id == application_id
    assert (
        application.organization_id
        == organization_id
    )
    assert application.job_id == job_id
    assert (
        application.candidate_id
        == candidate_id
    )
