from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate


class CandidateRepository:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        full_name: str,
        email: str | None,
        phone: str | None,
        location: str | None,
        headline: str | None,
        summary: str | None,
    ) -> Candidate:
        candidate = Candidate(
            organization_id=organization_id,
            full_name=full_name,
            email=email,
            phone=phone,
            location=location,
            headline=headline,
            summary=summary,
        )

        self._session.add(
            candidate
        )

        await self._session.flush()
        await self._session.refresh(
            candidate
        )

        return candidate

    async def update(
        self,
        candidate: Candidate,
        *,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        location: str | None = None,
        headline: str | None = None,
        summary: str | None = None,
    ) -> Candidate:
        if full_name is not None:
            candidate.full_name = full_name

        if email is not None:
            candidate.email = email

        if phone is not None:
            candidate.phone = phone

        if location is not None:
            candidate.location = location

        if headline is not None:
            candidate.headline = headline

        if summary is not None:
            candidate.summary = summary

        await self._session.flush()
        await self._session.refresh(
            candidate
        )

        return candidate

    async def list_for_organization(
        self,
        organization_id: UUID,
    ) -> list[Candidate]:
        statement = (
            select(Candidate)
            .where(
                Candidate.organization_id
                == organization_id
            )
            .order_by(
                Candidate.created_at,
                Candidate.id,
            )
        )

        result = await self._session.execute(
            statement
        )

        return list(
            result.scalars().all()
        )

    async def get_for_organization(
        self,
        *,
        candidate_id: UUID,
        organization_id: UUID,
    ) -> Candidate | None:
        statement = select(
            Candidate
        ).where(
            Candidate.id == candidate_id,
            Candidate.organization_id
            == organization_id,
        )

        result = await self._session.execute(
            statement
        )

        return result.scalar_one_or_none()
