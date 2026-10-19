"""Tenant roles and serialized owner actions; invitations never grant ownership."""

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.organization_membership import (
    AccessEvent,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.models.user import User
from app.services.sessions import SessionService, utcnow

ROLES = frozenset({"owner", "recruiter", "viewer"})
READ_POSTS = frozenset({"semantic-search", "semantic-candidate-retrieval", "grounded-explanation"})


def denied():
    return AppError(code="PERMISSION_DENIED", message="This action is not permitted.", status_code=403)


def organization_missing():
    return NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Organization was not found.")


class AccessService:
    def __init__(self, session):
        self.session = session
        self.sessions = SessionService(session)

    async def membership(self, organization_id, user_id):
        return (await self.session.execute(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == user_id)
            .execution_options(populate_existing=True))).scalar_one_or_none()

    async def authorize(self, organization_id, user_id, method, path):
        member = await self.membership(organization_id, user_id)
        if member is None or member.role not in ROLES:
            raise organization_missing()
        reading = method in {"GET", "HEAD"} or method == "POST" and path.rsplit("/", 1)[-1] in READ_POSTS
        if not reading and member.role == "viewer":
            raise denied()
        if "/access/" in path and member.role != "owner":
            raise denied()
        return member

    async def info(self, organization_id, user_id, offset=0):
        member = await self.membership(organization_id, user_id)
        if member is None:
            raise organization_missing()
        result = {"organization_id": organization_id, "role": member.role, "can_write": member.role in {"owner", "recruiter"},
                  "can_manage": member.role == "owner", "members": [], "invitations": [], "events": [],
                  "offset": offset, "has_more": False}
        if member.role != "owner":
            return result
        rows = (await self.session.execute(select(
            OrganizationMembership.id, OrganizationMembership.user_id, User.email, User.is_active, OrganizationMembership.role)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.created_at, OrganizationMembership.id).limit(21).offset(offset))).mappings().all()
        result.update(members=[dict(row) for row in rows[:20]], has_more=len(rows) > 20)
        invitations = (await self.session.execute(select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id, OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None), OrganizationInvitation.expires_at > utcnow())
            .order_by(OrganizationInvitation.created_at.desc(), OrganizationInvitation.id.desc()).limit(20))).scalars().all()
        result["invitations"] = [{"id": item.id, "email": item.email, "role": item.role, "expires_at": item.expires_at}
                                 for item in invitations]
        events = (await self.session.execute(select(AccessEvent).where(AccessEvent.organization_id == organization_id)
                  .order_by(AccessEvent.created_at.desc(), AccessEvent.id.desc()).limit(20))).scalars().all()
        result["events"] = [{"id": item.id, "actor_user_id": item.actor_user_id, "action": item.action,
                             "subject_id": item.subject_id, "previous_role": item.previous_role,
                             "new_role": item.new_role, "created_at": item.created_at} for item in events]
        return result

    async def _reauthenticate_owner(self, organization_id, user, password):
        membership = await self.membership(organization_id, user.id)
        if membership is None:
            raise organization_missing()
        if membership.role != "owner":
            raise denied()
        return await self.sessions.reauthenticate(user, password.get_secret_value())

    async def _owner_lock(self, organization_id, user_id, verified_hash):
        try:
            organization = (await self.session.execute(select(Organization).where(Organization.id == organization_id)
                            .with_for_update(nowait=True))).scalar_one_or_none()
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise AppError(code="ACCESS_BUSY", message="Another access change is in progress.", status_code=503) from error
            raise
        if organization is None:
            raise organization_missing()
        member = await self.membership(organization_id, user_id)
        if member is None or member.role != "owner":
            raise denied()
        await self.sessions.lock_user(user_id, verified_hash)

    def _event(self, organization_id, user_id, action, subject_id, previous=None, new=None):
        self.session.add(AccessEvent(organization_id=organization_id, actor_user_id=user_id, action=action,
                                    subject_id=subject_id, previous_role=previous, new_role=new))

    async def invite(self, organization_id, user, data):
        verified_hash = await self._reauthenticate_owner(organization_id, user, data.current_password)
        try:
            await self._owner_lock(organization_id, user.id, verified_hash)
            email = str(data.email)
            existing = (await self.session.execute(select(OrganizationMembership.id).join(User).where(
                OrganizationMembership.organization_id == organization_id, User.email == email))).scalar_one_or_none()
            if existing:
                raise ConflictError(code="MEMBER_ALREADY_EXISTS", message="User is already a member.")
            pending = select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id, OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None), OrganizationInvitation.expires_at > utcnow())
            rows = (await self.session.execute(pending.limit(20))).scalars().all()
            if any(item.email == email for item in rows):
                raise ConflictError(code="INVITATION_ALREADY_EXISTS", message="A pending invitation already exists.")
            if len(rows) >= 20:
                raise ConflictError(code="INVITATION_LIMIT", message="Too many pending invitations.")
            token = secrets.token_urlsafe(32)
            invitation = OrganizationInvitation(id=uuid4(), organization_id=organization_id, email=email,
                role=data.role, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=utcnow() + timedelta(hours=48))
            self.session.add(invitation)
            self._event(organization_id, user.id, "invitation_created", invitation.id, new=data.role)
            await self.session.commit()
            return {"id": invitation.id, "organization_id": organization_id, "email": email, "role": data.role,
                    "expires_at": invitation.expires_at, "token": token}
        except BaseException:
            await self.session.rollback()
            raise

    async def revoke_invitation(self, organization_id, user, invitation_id, data):
        verified_hash = await self._reauthenticate_owner(organization_id, user, data.current_password)
        try:
            await self._owner_lock(organization_id, user.id, verified_hash)
            invitation = (await self.session.execute(select(OrganizationInvitation).where(
                OrganizationInvitation.id == invitation_id, OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.revoked_at.is_(None), OrganizationInvitation.accepted_at.is_(None)))).scalar_one_or_none()
            if invitation is None:
                raise NotFoundError(code="INVITATION_INVALID", message="Invitation is not available.")
            invitation.revoked_at = utcnow()
            self._event(organization_id, user.id, "invitation_revoked", invitation.id)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise

    async def change_member(self, organization_id, user, member_id, data, *, remove=False):
        verified_hash = await self._reauthenticate_owner(organization_id, user, data.current_password)
        try:
            await self._owner_lock(organization_id, user.id, verified_hash)
            record = (await self.session.execute(select(OrganizationMembership).where(
                OrganizationMembership.id == member_id, OrganizationMembership.organization_id == organization_id)
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if record is None:
                raise NotFoundError(code="MEMBER_NOT_FOUND", message="Member was not found.")
            if record.role != data.expected_role:
                raise ConflictError(code="ACCESS_CHANGED", message="Membership changed. Read it again.")
            target = None if remove else data.role
            if record.role == "owner" and target != "owner":
                owners = (await self.session.execute(select(func.count()).select_from(OrganizationMembership).join(User)
                    .where(OrganizationMembership.organization_id == organization_id,
                           OrganizationMembership.role == "owner", User.is_active.is_(True),
                           OrganizationMembership.user_id != record.user_id))).scalar_one()
                if owners < 1:
                    raise ConflictError(code="LAST_OWNER", message="Keep at least one active owner.")
            old = record.role
            if remove:
                await self.session.delete(record)
            else:
                record.role = target
            self._event(organization_id, user.id, "member_removed" if remove else "role_changed", record.user_id, old, target)
            await self.session.commit()
            return {"removed_self": remove and record.user_id == user.id}
        except BaseException:
            await self.session.rollback()
            raise

    async def accept(self, user, data):
        token = data.token.get_secret_value()
        unavailable = NotFoundError(code="INVITATION_INVALID", message="Invitation is not available for this account.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise unavailable
        digest = hashlib.sha256(token.encode()).hexdigest()
        try:
            organization_id = (await self.session.execute(select(OrganizationInvitation.organization_id).where(
                OrganizationInvitation.token_hash == digest))).scalar_one_or_none()
            if organization_id is None:
                raise unavailable
            # Every membership writer takes the same organization mutex first.
            try:
                await self.session.execute(select(Organization.id).where(Organization.id == organization_id)
                                           .with_for_update(nowait=True))
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) == "55P03":
                    raise AppError(code="ACCESS_BUSY", message="Another access change is in progress.", status_code=503) from error
                raise
            invitation = (await self.session.execute(select(OrganizationInvitation).where(
                OrganizationInvitation.token_hash == digest, OrganizationInvitation.email == user.email,
                OrganizationInvitation.expires_at > utcnow(), OrganizationInvitation.revoked_at.is_(None),
                OrganizationInvitation.accepted_at.is_(None))
                .execution_options(populate_existing=True))).scalar_one_or_none()
            if invitation is None:
                raise unavailable
            if await self.membership(organization_id, user.id):
                raise ConflictError(code="MEMBER_ALREADY_EXISTS", message="User is already a member.")
            self.session.add(OrganizationMembership(organization_id=organization_id, user_id=user.id, role=invitation.role))
            invitation.accepted_at = utcnow()
            self._event(organization_id, user.id, "invitation_accepted", user.id, new=invitation.role)
            await self.session.commit()
            return {"organization_id": organization_id, "role": invitation.role}
        except BaseException:
            await self.session.rollback()
            raise
