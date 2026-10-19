from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import get_access_service, get_current_user
from app.schemas.access import (
    AccessRead,
    InvitationAccept,
    InvitationAccepted,
    InvitationCreate,
    InvitationCreated,
    MemberChanged,
    MemberRemoval,
    PasswordConfirmation,
    RoleChange,
)


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(tags=["access"], dependencies=[Depends(private_response)])


@router.get("/organizations/{organization_id}/access", response_model=AccessRead)
async def access_info(organization_id: UUID, offset: int = Query(default=0, ge=0, le=10_000),
                      user=Depends(get_current_user), service=Depends(get_access_service)):
    return await service.info(organization_id, user.id, offset)


@router.post("/organizations/{organization_id}/access/invitations", status_code=201, response_model=InvitationCreated)
async def invite(organization_id: UUID, data: InvitationCreate,
                 user=Depends(get_current_user), service=Depends(get_access_service)):
    return await service.invite(organization_id, user, data)


@router.delete("/organizations/{organization_id}/access/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(organization_id: UUID, invitation_id: UUID, data: PasswordConfirmation,
                            user=Depends(get_current_user), service=Depends(get_access_service)):
    await service.revoke_invitation(organization_id, user, invitation_id, data)


@router.put("/organizations/{organization_id}/access/members/{member_id}", response_model=MemberChanged)
async def change_role(organization_id: UUID, member_id: UUID, data: RoleChange,
                      user=Depends(get_current_user), service=Depends(get_access_service)):
    return await service.change_member(organization_id, user, member_id, data)


@router.delete("/organizations/{organization_id}/access/members/{member_id}", response_model=MemberChanged)
async def remove_member(organization_id: UUID, member_id: UUID, data: MemberRemoval,
                        user=Depends(get_current_user), service=Depends(get_access_service)):
    return await service.change_member(organization_id, user, member_id, data, remove=True)


@router.post("/access/invitations/accept", response_model=InvitationAccepted)
async def accept_invitation(data: InvitationAccept, user=Depends(get_current_user), service=Depends(get_access_service)):
    return await service.accept(user, data)
