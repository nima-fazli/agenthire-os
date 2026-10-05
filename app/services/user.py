import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate


class UserService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session
        self._repository = UserRepository(
            session
        )

    async def create(
        self,
        data: UserCreate,
    ) -> User:
        existing = await self._repository.get_by_email(
            data.email
        )

        if existing is not None:
            raise self._duplicate_email_error(
                data.email
            )

        password_hash = await asyncio.to_thread(
            hash_password,
            data.password.get_secret_value(),
        )

        try:
            user = await self._repository.create(
                email=data.email,
                password_hash=password_hash,
            )

            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()

            existing = await self._repository.get_by_email(
                data.email
            )

            if existing is not None:
                raise self._duplicate_email_error(
                    data.email
                ) from error

            raise
        except Exception:
            await self._session.rollback()
            raise

        return user

    @staticmethod
    def _duplicate_email_error(
        email: str,
    ) -> ConflictError:
        return ConflictError(
            code="USER_EMAIL_ALREADY_EXISTS",
            message="User email already exists.",
            details={
                "email": email,
            },
        )
