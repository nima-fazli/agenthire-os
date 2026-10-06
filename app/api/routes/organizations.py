from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_current_user,
    get_organization_service,
)
from app.models.user import User
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
    current_user: User = Depends(
        get_current_user,
    ),
    service: OrganizationService = Depends(
        get_organization_service,
    ),
) -> OrganizationRead:
    organization = await service.create(
        data,
        owner_user_id=current_user.id,
    )

    return OrganizationRead.model_validate(
        organization
    )


@router.get(
    "",
    response_model=list[OrganizationRead],
)
async def list_organizations(
    current_user: User = Depends(
        get_current_user,
    ),
    service: OrganizationService = Depends(
        get_organization_service,
    ),
) -> list[OrganizationRead]:
    organizations = await service.list_for_user(
        user_id=current_user.id,
    )

    return [
        OrganizationRead.model_validate(
            organization
        )
        for organization in organizations
    ]


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
)
async def get_organization(
    organization_id: UUID,
    current_user: User = Depends(
        get_current_user,
    ),
    service: OrganizationService = Depends(
        get_organization_service,
    ),
) -> OrganizationRead:
    organization = await service.get_for_user(
        organization_id,
        user_id=current_user.id,
    )

    return OrganizationRead.model_validate(
        organization
    )
