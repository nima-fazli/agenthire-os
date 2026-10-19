"""Server-owned bearer sessions; credentials and bearer secrets are never persisted."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from uuid import uuid4

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password_with_dummy
from app.core.tokens import create_access_token
from app.models.user import LoginThrottle, User, UserSession

PASSWORD_SLOTS = BoundedSemaphore(2)
MAX_SESSIONS = 10


def utcnow():
    return datetime.now(UTC)


def invalid_token():
    return UnauthorizedError(code="INVALID_ACCESS_TOKEN", message="Access token is invalid or missing.")


async def password_work(function, *arguments):
    # The worker owns release: cancelling an HTTP waiter never releases a running hash slot.
    if not PASSWORD_SLOTS.acquire(blocking=False):
        raise AppError(code="AUTH_BUSY", message="Authentication is busy.", status_code=503)

    def work():
        try:
            return function(*arguments)
        finally:
            PASSWORD_SLOTS.release()
    try:
        future = asyncio.get_running_loop().run_in_executor(None, work)
    except BaseException:
        PASSWORD_SLOTS.release()
        raise
    future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    return await asyncio.shield(future)


class SessionService:
    def __init__(self, session):
        self.session = session

    async def credentials(self, email, password, *, sensitive=False):
        """Five failed attempts per normalized email per 15-minute database window."""
        now = utcnow()
        key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        try:
            await self.session.execute(text("SELECT set_config('lock_timeout', '2000', true)"))
            await self.session.execute(delete(LoginThrottle).where(LoginThrottle.key == key, LoginThrottle.expires_at <= now)
                                       .execution_options(synchronize_session="fetch"))
            await self.session.execute(delete(LoginThrottle).where(LoginThrottle.key.in_(
                select(LoginThrottle.key).where(LoginThrottle.expires_at <= now).limit(100))))
            await self.session.execute(insert(LoginThrottle).values(
                key=key, attempts=0, expires_at=now + timedelta(minutes=15)).on_conflict_do_nothing())
            result = await self.session.execute(select(LoginThrottle).where(LoginThrottle.key == key)
                                                .with_for_update(nowait=True).execution_options(populate_existing=True))
            throttle = result.scalar_one()
            if throttle.attempts >= 5:
                raise AppError(code="AUTH_THROTTLED", message="Too many attempts. Try again later.", status_code=429)
            user = (await self.session.execute(select(User).where(User.email == email)
                    .execution_options(populate_existing=True))).scalar_one_or_none()
            valid = await password_work(verify_password_with_dummy, password, user.password_hash if user else None)
            if user is None or not valid or not user.is_active:
                throttle.attempts += 1
                await self.session.commit()
                if sensitive:
                    raise AppError(code="INVALID_CURRENT_PASSWORD", message="Current password is incorrect.", status_code=403)
                raise UnauthorizedError(code="INVALID_CREDENTIALS", message="Invalid email or password.")
            verified_hash = user.password_hash
            await self.session.delete(throttle)
            await self.session.commit()
            return user, verified_hash
        except DBAPIError as error:
            await self.session.rollback()
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise AppError(code="AUTH_BUSY", message="Authentication is busy.", status_code=503) from error
            raise
        except BaseException:
            await self.session.rollback()
            raise

    async def lock_user(self, user_id, expected_hash):
        try:
            result = await self.session.execute(select(User).where(User.id == user_id)
                                                .with_for_update(nowait=True).execution_options(populate_existing=True))
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise AppError(code="AUTH_BUSY", message="Authentication is busy.", status_code=503) from error
            raise
        user = result.scalar_one_or_none()
        if user is None or not user.is_active or user.password_hash != expected_hash:
            raise AppError(code="REAUTHENTICATION_REQUIRED", message="Authenticate again.", status_code=403)
        return user

    async def login(self, data):
        user, verified_hash = await self.credentials(data.email, data.password.get_secret_value())
        try:
            user = await self.lock_user(user.id, verified_hash)
            now = utcnow().replace(microsecond=0)
            active = (await self.session.execute(select(UserSession).where(
                UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
                .order_by(UserSession.created_at.desc(), UserSession.id.desc()))).scalars().all()
            for old in active[MAX_SESSIONS - 1:]:
                old.revoked_at = utcnow()
            await self.session.execute(delete(UserSession).where(
                UserSession.user_id == user.id, UserSession.expires_at < now - timedelta(days=30))
                .execution_options(synchronize_session="fetch"))
            expires = now + timedelta(minutes=get_settings().access_token_expire_minutes)
            record = UserSession(id=uuid4(), user_id=user.id, created_at=utcnow(), expires_at=expires)
            self.session.add(record)
            await self.session.flush()
            token = create_access_token(subject=user.id, session_id=record.id, now=now)
            await self.session.commit()
            return {"access_token": token, "token_type": "bearer", "session_id": record.id, "expires_at": expires}
        except BaseException:
            await self.session.rollback()
            raise

    async def validate(self, claims):
        result = await self.session.execute(select(User).join(UserSession, UserSession.user_id == User.id).where(
            User.id == claims.user_id, User.is_active.is_(True), UserSession.id == claims.session_id,
            UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow(),
            UserSession.expires_at == claims.expires_at))
        user = result.scalar_one_or_none()
        if user is None:
            raise invalid_token()
        return user

    async def list(self, user_id, current_id):
        records = (await self.session.execute(select(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
            .order_by(UserSession.created_at.desc(), UserSession.id.desc()).limit(MAX_SESSIONS))).scalars().all()
        return [{"id": item.id, "created_at": item.created_at, "expires_at": item.expires_at,
                 "current": item.id == current_id} for item in records]

    async def reauthenticate(self, user, password):
        verified, password_hash = await self.credentials(user.email, password, sensitive=True)
        if verified.id != user.id:
            raise invalid_token()
        return password_hash

    async def logout(self, user_id, session_id):
        try:
            await self.session.execute(update(UserSession).where(
                UserSession.user_id == user_id, UserSession.id == session_id,
                UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise

    async def revoke(self, user, current_id, password, target_id=None):
        verified_hash = await self.reauthenticate(user, password)
        try:
            await self.lock_user(user.id, verified_hash)
            statement = update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            statement = statement.where(UserSession.id == target_id) if target_id else statement.where(UserSession.id != current_id)
            await self.session.execute(statement.values(revoked_at=utcnow()))
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise

    async def change_password(self, user, data):
        old, new = data.current_password.get_secret_value(), data.new_password.get_secret_value()
        if old == new:
            raise ConflictError(code="PASSWORD_UNCHANGED", message="Choose a different password.")
        verified_hash = await self.reauthenticate(user, old)
        encoded = await password_work(hash_password, new)
        try:
            current = await self.lock_user(user.id, verified_hash)
            current.password_hash = encoded
            await self.session.execute(update(UserSession).where(
                UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
