from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.organization import OrganizationCreate, OrganizationRead


def test_organization_create_normalizes_input() -> None:
    organization = OrganizationCreate(
        name="  Acme Corporation  ",
        slug="  ACME-CORPORATION  ",
    )

    assert organization.name == "Acme Corporation"
    assert organization.slug == "acme-corporation"


def test_organization_create_rejects_invalid_slug() -> None:
    with pytest.raises(ValidationError):
        OrganizationCreate(
            name="Acme Corporation",
            slug="acme corporation",
        )


def test_organization_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        OrganizationCreate(
            name="   ",
            slug="acme",
        )


def test_organization_read_supports_attribute_objects() -> None:
    organization_id = uuid4()
    now = datetime.now(UTC)

    organization = SimpleNamespace(
        id=organization_id,
        name="Acme Corporation",
        slug="acme",
        created_at=now,
        updated_at=now,
    )

    response = OrganizationRead.model_validate(organization)

    assert response.id == organization_id
    assert response.name == "Acme Corporation"
    assert response.slug == "acme"
    assert response.created_at == now
    assert response.updated_at == now
