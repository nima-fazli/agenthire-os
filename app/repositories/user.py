from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
        )

        self._session.add(user)

        await self._session.flush()
        await self._session.refresh(user)

        return user

    async def get_by_id(
        self,
        user_id: UUID,
    ) -> User | None:
        return await self._session.get(
            User,
            user_id,
        )

    async def get_by_email(
        self,
        email: str,
    ) -> User | None:
        statement = select(User).where(
            User.email == email
        )

        result = await self._session.execute(
            statement
        )

        return result.scalar_one_or_none()
