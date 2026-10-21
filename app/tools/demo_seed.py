"""Add an isolated fictional company. Never reset existing accounts or records."""

import argparse
import asyncio
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.session import async_session_factory
from app.models.agent_workspace import (
    ApplicantIdentity,
    ApplicantSubmission,
    CareerPublication,
)
from app.models.job import Job
from app.models.job_matching import JobMatchCriterion, JobMatchProfile
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.schemas.agent_workspace import DraftInput
from app.services.agent_workspace import AgentWorkspaceService, now

PASSWORD = "AgentHire-Demo-2026!"
RESUMES = [
    (
        "alex",
        "Alex Morgan",
        "Backend engineer\nBuilt Python and FastAPI services for an inventory platform.\nImplemented PostgreSQL migrations, indexes and transaction handling.\nWrote pytest integration tests.\nSeeking experience with container operations.",
    ),
    (
        "maya",
        "Maya Chen",
        "Backend developer\nBuilt Python APIs and automated tests with pytest.\nNo production experience with PostgreSQL.\nCreated Docker images and CI builds for internal tools.",
    ),
    (
        "sam",
        "Sam Rivera",
        "Product designer\nCreated interface prototypes and usability studies.\nDesigned accessible onboarding flows and typography systems.\nWorked with product managers and engineering teams.",
    ),
]
CRITERIA = [
    {
        "key": label.lower(),
        "label": label,
        "query_text": label,
        "importance": "required" if i < 2 else "preferred",
    }
    for i, label in enumerate(["Python", "PostgreSQL", "Docker"])
]


def stable(name):
    return uuid5(NAMESPACE_URL, "https://agenthire.example.com/local-demo/v1/" + name)


async def seed(factory, settings, with_applications=False):
    if settings.environment != "local" or not settings.agents_enabled:
        raise RuntimeError("Demo seed requires local environment and enabled agents.")
    async with factory() as session:
        users = {}
        for name in ["owner", "alex", "maya", "sam"]:
            email, uid = f"{name}@agenthire.example.com", stable("user/" + name)
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is not None and (
                user.id != uid or not verify_password(PASSWORD, user.password_hash)
            ):
                raise RuntimeError(
                    "A demo email belongs to another account. Nothing was overwritten."
                )
            if user is None:
                user = User(
                    id=uid,
                    email=email,
                    password_hash=hash_password(PASSWORD),
                    is_active=True,
                )
                session.add(user)
            users[name] = user
        await session.flush()
        oid, jid = stable("organization"), stable("job")
        if await session.get(Organization, oid) is None:
            if (
                await session.execute(
                    select(Organization.id).where(Organization.slug == "agenthire-demo")
                )
            ).first():
                raise RuntimeError(
                    "The demo company slug is occupied. Nothing was overwritten."
                )
            session.add(
                Organization(id=oid, name="AgentHire Demo Lab", slug="agenthire-demo")
            )
            await session.flush()
            session.add(
                OrganizationMembership(
                    organization_id=oid, user_id=users["owner"].id, role="owner"
                )
            )
        if await session.get(Job, jid) is None:
            session.add(
                Job(
                    id=jid,
                    organization_id=oid,
                    title="Backend Engineer — Local Agent Demo",
                    description="Private saved review criteria are separate from the public description.",
                    status="open",
                )
            )
            await session.flush()
            session.add(
                CareerPublication(
                    job_id=jid,
                    organization_id=oid,
                    published=True,
                    public_description="Build Python backend services with PostgreSQL. Tell us about projects, testing and deployment experience. This is a fictional portfolio opportunity.",
                )
            )
            session.add(
                JobMatchProfile(
                    job_id=jid, revision=1, updated_by_user_id=users["owner"].id
                )
            )
            await session.flush()
            for position, c in enumerate(CRITERIA):
                session.add(JobMatchCriterion(job_id=jid, position=position, **c))
        for name in ["alex", "maya", "sam"]:
            if await session.get(ApplicantIdentity, users[name].id) is None:
                session.add(
                    ApplicantIdentity(
                        user_id=users[name].id,
                        email=users[name].email,
                        verified_at=now(),
                        attempts=0,
                    )
                )
        await session.commit()
        if with_applications:
            svc = AgentWorkspaceService(session, settings)
            for name, full_name, resume in RESUMES:
                if (
                    await session.execute(
                        select(ApplicantSubmission.id).where(
                            ApplicantSubmission.user_id == users[name].id,
                            ApplicantSubmission.job_id == jid,
                        )
                    )
                ).first() is None:
                    draft = await svc.draft(
                        users[name],
                        DraftInput(job_id=jid, full_name=full_name, resume_text=resume),
                    )
                    await svc.submit(users[name], draft["id"], "replay")
    return {"seeded": True, "organization": str(oid), "job": str(jid)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--with-applications", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            "Plan: add an isolated fictional company and demo accounts. Add --execute to proceed."
        )
    else:
        print(
            asyncio.run(
                seed(async_session_factory, get_settings(), args.with_applications)
            )
        )
        print(
            "Demo owner: owner@agenthire.example.com; applicants: alex/maya/sam@agenthire.example.com"
        )
        print("Local synthetic password: " + PASSWORD)
