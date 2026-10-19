import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.api.dependencies import get_current_user
from app.core.errors import UnauthorizedError
from app.core.tokens import InvalidAccessTokenError, SessionClaims
from app.services.sessions import SessionService


def fixture():
    claims = SessionClaims(uuid4(), uuid4(), datetime.now(UTC) + timedelta(minutes=30))
    service = AsyncMock(spec=SessionService)
    service.session = object()
    service.validate.return_value = SimpleNamespace(id=claims.user_id, is_active=True)
    request = Request({"type": "http", "method": "GET", "path": "/users/me", "headers": []})
    return request, service, claims


def test_get_current_user_returns_only_a_valid_tracked_session():
    request, service, claims = fixture()
    response = Response()
    with patch("app.api.dependencies.decode_session_token", return_value=claims) as decoder:
        result = asyncio.run(get_current_user(request, response,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token"), service))
    assert result is service.validate.return_value
    decoder.assert_called_once_with("test-token")
    service.validate.assert_awaited_once_with(claims)
    assert request.state.session_id == claims.session_id
    assert response.headers["cache-control"] == "private, no-store"


def test_missing_credentials_never_query_session_data():
    request, service, _ = fixture()
    with pytest.raises(UnauthorizedError) as error:
        asyncio.run(get_current_user(request, Response(), None, service))
    assert error.value.code == "INVALID_ACCESS_TOKEN"
    service.validate.assert_not_awaited()


def test_invalid_or_legacy_token_never_queries_session_data():
    request, service, _ = fixture()
    with patch("app.api.dependencies.decode_session_token", side_effect=InvalidAccessTokenError()), pytest.raises(UnauthorizedError):
        asyncio.run(get_current_user(request, Response(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid"), service))
    service.validate.assert_not_awaited()


def test_revoked_expired_or_missing_session_is_rejected():
    request, service, claims = fixture()
    service.validate.side_effect = UnauthorizedError(code="INVALID_ACCESS_TOKEN", message="Invalid")
    with patch("app.api.dependencies.decode_session_token", return_value=claims), pytest.raises(UnauthorizedError):
        asyncio.run(get_current_user(request, Response(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"), service))


def test_every_tenant_request_passes_through_the_current_role_gate():
    request, service, claims = fixture()
    org = uuid4()
    request.scope.update(path=f"/organizations/{org}/jobs", method="POST",
                         path_params={"organization_id": str(org)})
    authorization = AsyncMock()
    with patch("app.api.dependencies.decode_session_token", return_value=claims), patch(
        "app.api.dependencies.AccessService", return_value=authorization):
        asyncio.run(get_current_user(request, Response(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"), service))
    authorization.authorize.assert_awaited_once_with(org, claims.user_id, "POST", request.url.path)
