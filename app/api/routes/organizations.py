from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_organization_service
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationRead,
)
from app.services.organization import OrganizationService

router = APIRouter(
    prefix="/organizations",
    tags=["organizations"],
)


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    data: OrganizationCreate,
    service: OrganizationService = Depends(
        get_organization_service,
    ),
) -> OrganizationRead:
    organization = await service.create(data)

    return OrganizationRead.model_validate(
        organization,
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
)
async def get_organization(
    organization_id: UUID,
    service: OrganizationService = Depends(
        get_organization_service,
    ),
) -> OrganizationRead:
    organization = await service.get_by_id(
        organization_id
    )

    return OrganizationRead.model_validate(
        organization,
    )
