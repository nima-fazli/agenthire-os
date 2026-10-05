from collections.abc import AsyncIterator

from app.db.session import get_db_session
from app.services.organization import OrganizationService


async def get_organization_service() -> AsyncIterator[OrganizationService]:
    async for session in get_db_session():
        yield OrganizationService(session)
