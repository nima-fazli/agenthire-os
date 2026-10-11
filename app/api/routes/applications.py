from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStatusTransition,
)
from app.services.application import ApplicationService

router = APIRouter(prefix="/organizations/{organization_id}/applications", tags=["applications"])


def get_application_service(session: AsyncSession = Depends(get_db_session)) -> ApplicationService:
    return ApplicationService(session)


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    organization_id: UUID,
    data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationRead:
    application = await service.create(
        data, organization_id=organization_id, user_id=current_user.id
    )

    return ApplicationRead.model_validate(application)


@router.post(
    "/{application_id}/transitions", response_model=ApplicationRead, status_code=status.HTTP_200_OK
)
async def transition_application_status(
    organization_id: UUID,
    application_id: UUID,
    data: ApplicationStatusTransition,
    current_user: User = Depends(get_current_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationRead:
    application = await service.transition_status_for_user(
        application_id, data, organization_id=organization_id, user_id=current_user.id
    )

    return ApplicationRead.model_validate(application)


@router.get("", response_model=list[ApplicationRead])
async def list_applications(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ApplicationService = Depends(get_application_service),
) -> list[ApplicationRead]:
    applications = await service.list_for_user(
        organization_id=organization_id, user_id=current_user.id
    )

    return [ApplicationRead.model_validate(application) for application in applications]


@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(
    organization_id: UUID,
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationRead:
    application = await service.get_for_user(
        application_id, organization_id=organization_id, user_id=current_user.id
    )

    return ApplicationRead.model_validate(application)
