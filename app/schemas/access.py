from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

Role = Literal["owner", "recruiter", "viewer"]
InviteRole = Literal["recruiter", "viewer"]


class PasswordConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=128)


class PasswordChange(PasswordConfirmation):
    new_password: SecretStr = Field(min_length=15, max_length=128)


class RoleChange(PasswordConfirmation):
    role: Role
    expected_role: Role


class MemberRemoval(PasswordConfirmation):
    expected_role: Role


class InvitationCreate(PasswordConfirmation):
    email: EmailStr = Field(min_length=3, max_length=320)
    role: InviteRole

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=43, max_length=43)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    session_id: UUID
    expires_at: AwareDatetime


class SessionRead(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    current: bool


class MemberRead(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    is_active: bool
    role: Role


class InvitationRead(BaseModel):
    id: UUID
    email: str
    role: InviteRole
    expires_at: datetime


class InvitationCreated(InvitationRead):
    organization_id: UUID
    token: str


class AccessEventRead(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: Literal["invitation_created", "invitation_revoked", "invitation_accepted", "role_changed", "member_removed"]
    subject_id: UUID
    previous_role: Role | None
    new_role: Role | None
    created_at: datetime


class AccessRead(BaseModel):
    organization_id: UUID
    role: Role
    can_write: bool
    can_manage: bool
    members: list[MemberRead] = Field(max_length=20)
    invitations: list[InvitationRead] = Field(max_length=20)
    events: list[AccessEventRead] = Field(max_length=20)
    offset: int = Field(ge=0, le=10_000)
    has_more: bool


class InvitationAccepted(BaseModel):
    organization_id: UUID
    role: InviteRole


class MemberChanged(BaseModel):
    removed_self: bool
