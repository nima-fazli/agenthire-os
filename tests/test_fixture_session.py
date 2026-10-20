import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.tokens import decode_session_token
from app.db.base import Base
from app.models.user import User, UserSession
from app.services.sessions import SessionService
from scripts.fixture_session import fixture_session


class Database:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


def test_fixture_bearer_requires_the_real_unexpired_unrevoked_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    try:
        with Session(engine) as session:
            user = User(id=uuid4(), email="fixture@example.com", password_hash="synthetic")
            session.add(user)
            record, token = fixture_session(user.id, get_settings())
            session.add(record)
            session.commit()
            claims = decode_session_token(token)
            assert claims.session_id == record.id
            assert claims.expires_at == record.expires_at.replace(tzinfo=UTC)
            service = SessionService(Database(session))
            assert asyncio.run(service.validate(claims)).id == user.id
            asyncio.run(service.logout(user.id, record.id))
            with pytest.raises(UnauthorizedError):
                asyncio.run(service.validate(claims))
            record.revoked_at = None
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            record.created_at = record.expires_at - timedelta(minutes=1)
            session.commit()
            with pytest.raises(UnauthorizedError):
                asyncio.run(service.validate(claims))
    finally:
        engine.dispose()
