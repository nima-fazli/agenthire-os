"""Create a tracked session for a synthetic test user; the caller owns the transaction."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.tokens import create_access_token
from app.models.user import UserSession


def fixture_session(user_id, settings):
    now = datetime.now(UTC).replace(microsecond=0)
    record = UserSession(id=uuid4(), user_id=user_id, created_at=now,
                         expires_at=now + timedelta(minutes=settings.access_token_expire_minutes))
    token = create_access_token(subject=user_id, session_id=record.id, now=now, settings=settings)
    return record, token
