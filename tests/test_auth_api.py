import asyncio
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_organization_service,
    get_session_service,
    get_user_service,
)
from app.core.errors import AppError, ConflictError, NotFoundError, UnauthorizedError
from app.core.security import hash_password
from app.core.tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_session_token,
)
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.organization import Organization
from app.models.organization_membership import (
    AccessEvent,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.models.user import LoginThrottle, User, UserSession
from app.schemas.access import (
    InvitationAccept,
    InvitationCreate,
    MemberRemoval,
    PasswordChange,
    RoleChange,
)
from app.schemas.auth import LoginRequest
from app.services.access import AccessService
from app.services.organization import OrganizationService
from app.services.sessions import MAX_SESSIONS, SessionService, password_work
from app.services.user import UserService

PASSWORD = "synthetic-password-123"


class AsyncDatabase:
    """Execute real ORM SQL without an extra async SQLite dependency."""
    def __init__(self, engine):
        self.sync = Session(engine, expire_on_commit=False)

    async def execute(self, statement):
        if "set_config(" in str(statement):
            return self.sync.execute(select(1))
        return self.sync.execute(statement)

    def add(self, value):
        self.sync.add(value)

    async def delete(self, value):
        self.sync.delete(value)

    async def flush(self):
        self.sync.flush()

    async def refresh(self, value):
        self.sync.refresh(value)

    async def commit(self):
        self.sync.commit()

    async def rollback(self):
        self.sync.rollback()

    async def get(self, model, identity):
        return self.sync.get(model, identity)


@pytest.fixture
def identity():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [User.__table__, UserSession.__table__, LoginThrottle.__table__, Organization.__table__,
              OrganizationMembership.__table__, OrganizationInvitation.__table__, AccessEvent.__table__]
    Base.metadata.create_all(engine, tables=tables)
    db = AsyncDatabase(engine)
    encoded = hash_password(PASSWORD)
    users = {role: User(id=uuid4(), email=f"{role}@example.com", password_hash=encoded, is_active=True)
             for role in ("owner", "recruiter", "viewer", "outsider")}
    organization = Organization(id=uuid4(), name="Synthetic", slug="synthetic")
    db.sync.add_all([*users.values(), organization])
    db.sync.flush()
    memberships = {role: OrganizationMembership(id=uuid4(), organization_id=organization.id, user_id=users[role].id, role=role)
                   for role in ("owner", "recruiter", "viewer")}
    db.sync.add_all(memberships.values())
    db.sync.commit()
    yield SimpleNamespace(db=db, users=users, members=memberships, org=organization,
                          sessions=SessionService(db), access=AccessService(db))
    db.sync.close()
    engine.dispose()


def login(identity, role="owner"):
    return asyncio.run(identity.sessions.login(LoginRequest(email=identity.users[role].email, password=PASSWORD)))


@pytest.mark.parametrize("role", ["owner", "recruiter", "viewer"])
@pytest.mark.parametrize("method,suffix,reading", [
    ("GET", "/jobs", True), ("POST", "/jobs", False),
    ("POST", "/semantic-search", True), ("POST", "/jobs/any/candidates/any/grounded-explanation", True),
])
def test_role_matrix_is_enforced_before_workflow_execution(identity, role, method, suffix, reading):
    call = identity.access.authorize(identity.org.id, identity.users[role].id, method, "/organizations/fixture" + suffix)
    if role == "viewer" and not reading:
        with pytest.raises(AppError) as error:
            asyncio.run(call)
        assert error.value.status_code == 403
    else:
        assert asyncio.run(call).role == role


def test_outsider_cannot_discover_membership_and_recruiter_cannot_manage_access(identity):
    with pytest.raises(NotFoundError):
        asyncio.run(identity.access.authorize(identity.org.id, identity.users["outsider"].id, "GET", "/jobs"))
    with pytest.raises(AppError) as error:
        asyncio.run(identity.access.authorize(identity.org.id, identity.users["recruiter"].id, "GET", "/access/members"))
    assert error.value.status_code == 403
    view = asyncio.run(identity.access.info(identity.org.id, identity.users["viewer"].id))
    assert not view["can_write"] and not view["can_manage"] and view["members"] == view["events"] == []


def test_last_active_owner_is_preserved_and_stale_roles_do_not_overwrite(identity):
    data = RoleChange(role="viewer", expected_role="owner", current_password=PASSWORD)
    with pytest.raises(ConflictError) as error:
        asyncio.run(identity.access.change_member(identity.org.id, identity.users["owner"], identity.members["owner"].id, data))
    assert error.value.code == "LAST_OWNER"
    with pytest.raises(ConflictError) as error:
        asyncio.run(identity.access.change_member(identity.org.id, identity.users["owner"], identity.members["recruiter"].id, data))
    assert error.value.code == "ACCESS_CHANGED"
    assert identity.db.sync.scalars(select(AccessEvent)).all() == []


def test_owner_promotion_and_removal_are_recorded_in_the_same_transaction(identity):
    owner = identity.users["owner"]
    promote = RoleChange(role="owner", expected_role="recruiter", current_password=PASSWORD)
    asyncio.run(identity.access.change_member(identity.org.id, owner, identity.members["recruiter"].id, promote))
    removal = MemberRemoval(expected_role="viewer", current_password=PASSWORD)
    asyncio.run(identity.access.change_member(identity.org.id, owner, identity.members["viewer"].id, removal, remove=True))
    events = identity.db.sync.scalars(select(AccessEvent)).all()
    assert {item.action for item in events} == {"role_changed", "member_removed"}
    assert all(item.actor_user_id == owner.id and item.organization_id == identity.org.id for item in events)
    assert asyncio.run(identity.access.membership(identity.org.id, identity.users["viewer"].id)) is None


def test_invitation_is_email_bound_hashed_single_use_and_cannot_promote_ownership(identity):
    data = InvitationCreate(email=" OUTSIDER@EXAMPLE.COM ", role="viewer", current_password=PASSWORD)
    invited = asyncio.run(identity.access.invite(identity.org.id, identity.users["owner"], data))
    record = identity.db.sync.get(OrganizationInvitation, invited["id"])
    assert len(invited["token"]) == 43 and invited["token"] != record.token_hash
    accept = InvitationAccept(token=invited["token"])
    with pytest.raises(NotFoundError):
        asyncio.run(identity.access.accept(identity.users["viewer"], accept))
    result = asyncio.run(identity.access.accept(identity.users["outsider"], accept))
    assert result == {"organization_id": identity.org.id, "role": "viewer"}
    with pytest.raises(NotFoundError):
        asyncio.run(identity.access.accept(identity.users["outsider"], accept))
    assert "token_hash" not in str(asyncio.run(identity.access.info(identity.org.id, identity.users["owner"].id)))
    with pytest.raises(ValidationError):
        InvitationCreate(email="new@example.com", role="owner", current_password=PASSWORD)


def test_revoked_and_expired_invitations_are_unusable(identity):
    data = InvitationCreate(email=identity.users["outsider"].email, role="recruiter", current_password=PASSWORD)
    first = asyncio.run(identity.access.invite(identity.org.id, identity.users["owner"], data))
    asyncio.run(identity.access.revoke_invitation(identity.org.id, identity.users["owner"], first["id"], data))
    with pytest.raises(NotFoundError):
        asyncio.run(identity.access.accept(identity.users["outsider"], InvitationAccept(token=first["token"])))
    second = asyncio.run(identity.access.invite(identity.org.id, identity.users["owner"], data))
    identity.db.sync.execute(update(OrganizationInvitation).where(OrganizationInvitation.id == second["id"])
                             .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    identity.db.sync.commit()
    with pytest.raises(NotFoundError):
        asyncio.run(identity.access.accept(identity.users["outsider"], InvitationAccept(token=second["token"])))


def test_session_logout_invalidates_only_its_own_bearer(identity):
    first, second = login(identity), login(identity)
    a, b = decode_session_token(first["access_token"]), decode_session_token(second["access_token"])
    assert asyncio.run(identity.sessions.validate(a)).id == identity.users["owner"].id
    asyncio.run(identity.sessions.logout(a.user_id, a.session_id))
    with pytest.raises(UnauthorizedError):
        asyncio.run(identity.sessions.validate(a))
    assert asyncio.run(identity.sessions.validate(b)).id == a.user_id
    sessions = asyncio.run(identity.sessions.list(b.user_id, b.session_id))
    assert len(sessions) == 1 and sessions[0]["current"]


def test_session_expiry_database_identity_and_active_user_are_all_required(identity):
    result = login(identity)
    claims = decode_session_token(result["access_token"])
    foreign = create_access_token(subject=identity.users["viewer"].id, session_id=claims.session_id)
    with pytest.raises(UnauthorizedError):
        asyncio.run(identity.sessions.validate(decode_session_token(foreign)))
    identity.users["owner"].is_active = False
    identity.db.sync.commit()
    with pytest.raises(UnauthorizedError):
        asyncio.run(identity.sessions.validate(claims))


def test_oldest_sessions_are_revoked_under_the_user_lock(identity):
    first = login(identity)
    for _ in range(MAX_SESSIONS):
        login(identity)
    claims = decode_session_token(first["access_token"])
    with pytest.raises(UnauthorizedError):
        asyncio.run(identity.sessions.validate(claims))
    assert len(asyncio.run(identity.sessions.list(claims.user_id, claims.session_id))) == MAX_SESSIONS


def test_password_change_checks_current_password_and_revokes_every_session(identity):
    first, second = login(identity), login(identity)
    new = "replacement-password-456"
    with pytest.raises(AppError) as error:
        asyncio.run(identity.sessions.change_password(identity.users["owner"], PasswordChange(current_password="incorrect", new_password=new)))
    assert error.value.code == "INVALID_CURRENT_PASSWORD" and error.value.status_code == 403
    asyncio.run(identity.sessions.change_password(identity.users["owner"], PasswordChange(current_password=PASSWORD, new_password=new)))
    for item in (first, second):
        with pytest.raises(UnauthorizedError):
            asyncio.run(identity.sessions.validate(decode_session_token(item["access_token"])))
    with pytest.raises(UnauthorizedError):
        login(identity)
    assert asyncio.run(identity.sessions.login(LoginRequest(email=identity.users["owner"].email, password=new)))["session_id"]


def test_database_login_throttle_applies_to_unknown_accounts_without_enumeration(identity):
    data = LoginRequest(email="unknown@example.com", password="incorrect")
    for _ in range(5):
        with pytest.raises(UnauthorizedError) as error:
            asyncio.run(identity.sessions.login(data))
        assert error.value.code == "INVALID_CREDENTIALS"
    with pytest.raises(AppError) as error:
        asyncio.run(identity.sessions.login(data))
    assert error.value.code == "AUTH_THROTTLED" and error.value.status_code == 429


def test_legacy_and_wrong_purpose_tokens_cannot_authenticate():
    token = create_access_token(subject=uuid4())
    with pytest.raises(InvalidAccessTokenError):
        decode_session_token(token)
    assert "synthetic" not in str(PasswordChange(current_password=PASSWORD, new_password="replacement-password-456"))


def test_cancelled_password_waiter_keeps_its_worker_slot(monkeypatch):
    import app.services.sessions as module
    entered, release = Event(), Event()
    monkeypatch.setattr(module, "PASSWORD_SLOTS", BoundedSemaphore(1))
    def hashing():
        entered.set()
        assert release.wait(3)
    async def run():
        task = asyncio.create_task(password_work(hashing))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(AppError) as error:
                await password_work(lambda: None)
            assert error.value.code == "AUTH_BUSY"
        finally:
            release.set()
    asyncio.run(run())


def test_permission_locks_use_postgresql_nowait_and_busy_errors_are_safe():
    session = SimpleNamespace(execute=AsyncMock(side_effect=DBAPIError("PRIVATE_SQL", {}, SimpleNamespace(sqlstate="55P03"))))
    with pytest.raises(AppError) as error:
        asyncio.run(SessionService(session).lock_user(uuid4(), "hash"))
    assert error.value.code == "AUTH_BUSY" and "PRIVATE" not in str(error.value)
    query = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE NOWAIT" in str(query)


def test_real_authentication_gate_denies_viewer_writes_before_domain_services(identity):
    from app.api.routes.jobs import get_job_service
    saved = app.dependency_overrides.copy()
    async def database():
        yield identity.db
    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_user_service] = lambda: UserService(identity.db)
    app.dependency_overrides[get_organization_service] = lambda: OrganizationService(identity.db)
    domain = MagicMock()
    domain.create = AsyncMock()
    app.dependency_overrides[get_job_service] = lambda: domain
    client = TestClient(app)
    try:
        response = client.post("/auth/login", json={"email": identity.users["viewer"].email, "password": PASSWORD})
        assert response.status_code == 200
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        denied = client.post(f"/organizations/{identity.org.id}/jobs", headers=headers,
                             json={"title": "Fixture", "description": "Fixture"})
        assert denied.status_code == 403
        domain.create.assert_not_awaited()
        allowed = client.get(f"/organizations/{identity.org.id}/access", headers=headers)
        assert allowed.status_code == 200 and allowed.json()["role"] == "viewer"
        assert client.post("/auth/logout", headers=headers).status_code == 204
        assert client.get("/users/me", headers=headers).status_code == 401
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


@pytest.fixture
def authentication():
    service = AsyncMock(spec=SessionService)
    saved = app.dependency_overrides.copy()
    app.dependency_overrides[get_session_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def test_login_returns_a_server_tracked_token_and_expiry(authentication):
    client, service = authentication
    session_id = uuid4()
    expiry = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=30)
    service.login.return_value = {"access_token": "test-access-token", "token_type": "bearer",
                                  "session_id": session_id, "expires_at": expiry}
    response = client.post("/auth/login", json={"email": "  NIMA@EXAMPLE.COM  ", "password": "a-very-secure-password"})
    assert response.status_code == 200
    assert response.json()["access_token"] == "test-access-token"
    assert response.json()["session_id"] == str(session_id)
    assert datetime.fromisoformat(response.json()["expires_at"]) == expiry
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    data = service.login.await_args.args[0]
    assert data.email == "nima@example.com"
    assert data.password.get_secret_value() == "a-very-secure-password"


def test_login_rejects_invalid_credentials(authentication):
    client, service = authentication
    service.login.side_effect = UnauthorizedError(code="INVALID_CREDENTIALS", message="Invalid email or password.")
    response = client.post("/auth/login", json={"email": "nima@example.com", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "access_token" not in response.json()


def test_login_rejects_empty_password_without_authentication(authentication):
    client, service = authentication
    response = client.post("/auth/login", json={"email": "nima@example.com", "password": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]["errors"][0]["location"] == ["body", "password"]
    service.login.assert_not_awaited()


@pytest.mark.parametrize("claim,value", [
    ("purpose", "refresh"), ("aud", ["agenthire-os", "other"]), ("iss", "other"),
    ("sid", "not-a-uuid"), ("exp", "9999999999"), ("iat", True),
])
def test_strict_session_claims_reject_alternative_purpose_audience_and_types(claim, value):
    import jwt

    from app.core.config import get_settings
    settings = get_settings()
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now, "exp": now + 60,
               "purpose": "access", "iss": "agenthire-os", "aud": "agenthire-os"}
    payload[claim] = value
    encoded = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    with pytest.raises(InvalidAccessTokenError):
        decode_session_token(encoded)


def test_expired_own_throttle_does_not_depend_on_the_global_cleanup_limit(identity):
    import hashlib
    key = hashlib.sha256(identity.users["owner"].email.encode()).hexdigest()
    identity.db.sync.add_all([
        LoginThrottle(key=str(index).zfill(64), attempts=5, expires_at=datetime.now(UTC) - timedelta(minutes=1))
        for index in range(120)
    ] + [LoginThrottle(key=key, attempts=5, expires_at=datetime.now(UTC) - timedelta(minutes=1))])
    identity.db.sync.commit()
    assert login(identity)["session_id"]
    assert identity.db.sync.get(LoginThrottle, key) is None
