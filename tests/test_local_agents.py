"""SQLite domain/API contracts; native PostgreSQL locking is a separate smoke gate."""

import asyncio
import hashlib
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.dependencies import get_current_user
from app.api.routes import agent_workspace as routes
from app.core.agent_runtime import ReplayModel, agent_turn
from app.core.agent_tools import (
    AgentFailure,
    execute_tool,
    register_evidence,
    search_sources,
    validate_review,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.pdf_extraction import ExtractionFailure, PdfExtractor
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.agent_workspace import (
    AgentOutbox,
    AgentRun,
    ApplicantIdentity,
    ApplicantSubmission,
)
from app.models.job_matching import JobMatchProfile
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.schemas.agent_workspace import (
    AnswerInput,
    ApplicantQuestionInput,
    ApprovalInput,
    DraftInput,
    RunInput,
    VerifyInput,
)
from app.schemas.application import ApplicationStatus, ApplicationStatusTransition
from app.services.agent_workspace import AgentWorkspaceService, now
from app.services.application import ApplicationService
from app.tools.demo_seed import CRITERIA, RESUMES, seed, stable
from app.workers.agents import AgentWorker, mail_once


async def database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agents.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        t
        for t in Base.metadata.sorted_tables
        if t.name not in {"document_embeddings", "document_embedding_jobs"}
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        agents_enabled=True,
        document_storage_path=tmp_path / "documents",
    )
    await seed(factory, settings, True)
    ids = {name: stable("user/" + name) for name in ["owner", "alex", "maya", "sam"]}
    ids.update(
        org=stable("organization"), job=stable("job"), other=uuid4(), viewer=uuid4()
    )
    async with factory() as session:
        session.add_all(
            [
                User(
                    id=ids["other"],
                    email="other@example.com",
                    password_hash="unused",
                    is_active=True,
                ),
                User(
                    id=ids["viewer"],
                    email="viewer@example.com",
                    password_hash="unused",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            OrganizationMembership(
                organization_id=ids["org"], user_id=ids["viewer"], role="viewer"
            )
        )
        await session.commit()
    return engine, factory, settings, ids


async def drain(factory, settings):
    worker = AgentWorker(factory, settings)
    for _ in range(12):
        if not await worker.once():
            return
    raise AssertionError("Worker did not drain bounded replay fixtures")


async def alex_run(session, ids):
    sub = (
        await session.execute(
            select(ApplicantSubmission).where(
                ApplicantSubmission.user_id == ids["alex"]
            )
        )
    ).scalar_one()
    run = (
        (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.submission_id == sub.id)
                .order_by(AgentRun.created_at, AgentRun.id)
            )
        )
        .scalars()
        .first()
    )
    return sub, run


def test_complete_review_approval_reply_and_applicant_agent(tmp_path):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        try:
            await drain(factory, settings)
            async with factory() as session:
                svc = AgentWorkspaceService(session, settings)
                sub, run = await alex_run(session, ids)
                assert (
                    run.status == "waiting_approval"
                    and run.steps == 5
                    and run.report["question_keys"] == ["docker"]
                )
                applicant, owner = (
                    await session.get(User, ids["alex"]),
                    await session.get(User, ids["owner"]),
                )
                assert (await svc.portal_list(applicant))[0]["question"] is None
                data = ApprovalInput(
                    decision="approve", source_fingerprint=run.source_fingerprint
                )
                await svc.approve(ids["org"], run.id, owner, data)
                assert (await svc.approve(ids["org"], run.id, owner, data))[
                    "already_approved"
                ]
                assert (
                    await session.execute(
                        select(func.count())
                        .select_from(AgentOutbox)
                        .where(AgentOutbox.dedupe_key == f"clarification:{run.id}")
                    )
                ).scalar_one() == 1
                approved = (await svc.portal_list(applicant))[0]
                assert approved["status"] == "Additional information requested"
                reply = await svc.answer(
                    applicant,
                    sub.id,
                    AnswerInput(
                        question_revision=1,
                        text="Built Docker images for Python services and maintained deployment containers.",
                    ),
                )
                assert (
                    await svc.answer(
                        applicant,
                        sub.id,
                        AnswerInput(
                            question_revision=1,
                            text="A duplicate retry must not overwrite my accepted response.",
                        ),
                    )
                )["already_answered"]
                asked = await svc.ask(
                    applicant,
                    sub.id,
                    ApplicantQuestionInput(goal="What is my application status?"),
                )
            await drain(factory, settings)
            async with factory() as session:
                report = await session.get(AgentRun, reply["run_id"])
                assert all(
                    f["assessment"] == "supported" for f in report.report["findings"]
                )
                answer = await AgentWorkspaceService(session, settings).own_agent_run(
                    await session.get(User, ids["alex"]), asked["id"]
                )
                assert (
                    answer["status"] == "completed"
                    and "Your application status:" in answer["answer"]
                )
                assert set(answer).isdisjoint(
                    {"events", "report", "checkpoint", "source_fingerprint"}
                )
            sent = []
            while await mail_once(
                factory, settings, sender=lambda message, _: sent.append(message)
            ):
                pass
            assert len(sent) == 4  # three receipts, one approved clarification
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_scope_viewer_and_stale_approval(tmp_path):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        try:
            await drain(factory, settings)
            async with factory() as session:
                svc = AgentWorkspaceService(session, settings)
                sub, run = await alex_run(session, ids)
                outsider, viewer, owner = [
                    await session.get(User, ids[x])
                    for x in ["other", "viewer", "owner"]
                ]
                with pytest.raises(AppError):
                    await svc.get_run(ids["org"], run.id, outsider)
                with pytest.raises(AppError):
                    await svc.own_submission(sub.id, outsider)
                with pytest.raises(AppError):
                    await svc.create_run(ids["org"], sub.id, viewer, RunInput())
                assert (await svc.get_run(ids["org"], run.id, viewer)).id == run.id
                profile = await session.get(JobMatchProfile, ids["job"])
                profile.revision += 1
                await session.commit()
                with pytest.raises(AppError, match="changed"):
                    await svc.approve(
                        ids["org"],
                        run.id,
                        owner,
                        ApprovalInput(
                            decision="approve",
                            source_fingerprint=run.source_fingerprint,
                        ),
                    )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_verification_throttle_attempts_and_separate_applicant_identity(tmp_path):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        try:
            async with factory() as session:
                svc = AgentWorkspaceService(session, settings)
                user = await session.get(User, ids["other"])
                with pytest.raises(AppError):
                    await svc.draft(
                        user,
                        DraftInput(job_id=ids["job"], full_name="Unverified Person"),
                    )
                await svc.request_verification(user)
                with pytest.raises(AppError):
                    await svc.request_verification(user)
                mail = (
                    await session.execute(
                        select(AgentOutbox).where(AgentOutbox.recipient == user.email)
                    )
                ).scalar_one()
                code = re.search(r"code is ([0-9]{6})", mail.body).group(1)
                wrong = "999999" if code != "999999" else "888888"
                for _ in range(5):
                    with pytest.raises(AppError):
                        await svc.verify(user, VerifyInput(code=wrong))
                with pytest.raises(AppError):
                    await svc.verify(user, VerifyInput(code=code))
                identity = await session.get(ApplicantIdentity, user.id)
                identity.requested_at = now() - timedelta(minutes=2)
                await session.commit()
                await svc.request_verification(user)
                latest = (
                    (
                        await session.execute(
                            select(AgentOutbox)
                            .where(AgentOutbox.recipient == user.email)
                            .order_by(
                                AgentOutbox.created_at.desc(), AgentOutbox.id.desc()
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                challenge = await session.get(ApplicantIdentity, user.id)
                code = next(
                    re.search(r"code is ([0-9]{6})", m.body).group(1)
                    for m in latest
                    if svc._code_hash(
                        user, re.search(r"code is ([0-9]{6})", m.body).group(1)
                    )
                    == challenge.challenge_hash
                )
                assert (await svc.verify(user, VerifyInput(code=code)))["verified"]
                draft = await svc.draft(
                    user,
                    DraftInput(
                        job_id=ids["job"],
                        full_name="Individual Applicant",
                        resume_text=RESUMES[0][2],
                    ),
                )
                receipt = await svc.submit(user, draft["id"], "replay")
                assert (
                    receipt["state"] == "submitted"
                    and (await svc.submit(user, draft["id"], "replay"))[
                        "already_submitted"
                    ]
                )
                assert (
                    await session.execute(
                        select(OrganizationMembership).where(
                            OrganizationMembership.user_id == user.id
                        )
                    )
                ).first() is None
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_cancel_and_reclaim_fence_late_results(tmp_path):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        try:
            worker = AgentWorker(factory, settings)
            rid, old = await worker.claim()
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                run.lease_expires_at = now() - timedelta(seconds=1)
                await session.commit()
            claimed = await worker.claim()
            assert claimed[0] == rid and claimed[1] != old
            await worker.process(rid, old)
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                assert run.steps == 0
                owner = await session.get(User, ids["owner"])
                await AgentWorkspaceService(session, settings).cancel(
                    ids["org"], rid, owner
                )
            await worker.process(*claimed)
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                assert (
                    run.status == "cancelled" and run.steps == 0 and run.report is None
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_status_notices_are_atomic_and_same_state_retries_do_not_duplicate(
    tmp_path, monkeypatch
):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
        try:
            async with factory() as session:
                sub, run = await alex_run(session, ids)
                svc = ApplicationService(session)
                for status in [
                    ApplicationStatus.SCREENING,
                    ApplicationStatus.SCREENING,
                    ApplicationStatus.REJECTED,
                ]:
                    await svc.transition_status_for_user(
                        sub.application_id,
                        ApplicationStatusTransition(status=status),
                        organization_id=ids["org"],
                        user_id=ids["owner"],
                    )
                mails = (
                    (
                        await session.execute(
                            select(AgentOutbox).where(
                                AgentOutbox.dedupe_key.like(
                                    f"status:{sub.application_id}:%"
                                )
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(mails) == 2
                assert (
                    await AgentWorkspaceService(session, settings).portal_list(
                        await session.get(User, ids["alex"])
                    )
                )[0]["status"] == "Not selected"
                with pytest.raises(AgentFailure, match="APPLICATION_CLOSED"):
                    await AgentWorkspaceService(session, settings).snapshot(run)
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.fixture
def api_fixture(tmp_path, monkeypatch):
    engine, factory, settings, ids = asyncio.run(database(tmp_path))
    actor = [
        User(
            id=ids["alex"],
            email="alex@agenthire.example.com",
            password_hash="unused",
            is_active=True,
        )
    ]

    async def db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = lambda: actor[0]
    app.dependency_overrides[get_db_session] = db
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    client = TestClient(app)
    try:
        yield client, actor, factory, settings, ids
    finally:
        client.close()
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db_session, None)
        asyncio.run(engine.dispose())


def test_actual_http_publication_privacy_and_roles(api_fixture):
    client, actor, _, _, ids = api_fixture
    response = client.get("/public/jobs")
    assert (
        response.status_code == 200 and "no-store" in response.headers["cache-control"]
    )
    assert "Private saved" not in response.text and "criteria" not in response.text
    assert len(client.get("/portal/api/applications").json()) == 1
    assert client.get(f"/organizations/{ids['org']}/agent-runs").status_code == 404
    actor[0] = User(
        id=ids["viewer"],
        email="viewer@example.com",
        password_hash="unused",
        is_active=True,
    )
    assert client.get(f"/organizations/{ids['org']}/agent-runs").status_code == 200
    assert (
        client.put(
            f"/organizations/{ids['org']}/career-publications/{ids['job']}",
            json={
                "published": True,
                "public_description": "A different public description.",
            },
        ).status_code
        == 403
    )


def test_actual_http_pdf_draft_finalization_and_immutable_retry(api_fixture):
    client, actor, factory, settings, ids = api_fixture

    async def verified():
        async with factory() as session:
            session.add(
                ApplicantIdentity(
                    user_id=ids["other"],
                    email="other@example.com",
                    verified_at=now(),
                    attempts=0,
                )
            )
            await session.commit()

    asyncio.run(verified())
    actor[0] = User(
        id=ids["other"],
        email="other@example.com",
        password_hash="unused",
        is_active=True,
    )
    draft = client.post(
        "/portal/api/drafts",
        json={"job_id": str(ids["job"]), "full_name": "Synthetic PDF Applicant"},
    )
    assert draft.status_code == 201
    path = f"/portal/api/applications/{draft.json()['id']}"
    assert (
        client.put(
            path + "/resume?filename=../bad.pdf",
            content=b"x",
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 422
    )
    pdf = Path("docs/demo-resumes/alex-morgan.pdf").read_bytes()
    assert (
        client.put(
            path + "/resume?filename=resume.pdf",
            content=pdf,
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 200
    )
    result = client.post(path + "/submit", json={"mode": "replay"})
    assert result.status_code == 202
    assert client.post(path + "/submit", json={"mode": "replay"}).json()[
        "already_submitted"
    ]
    assert (
        client.put(
            path + "/resume?filename=resume.pdf",
            content=pdf,
            headers={"Content-Type": "application/pdf"},
        ).status_code
        == 409
    )
    assert len(list(settings.document_storage_path.glob("*.pdf"))) == 1


@pytest.mark.parametrize(
    "name,expected",
    [
        ("alex-morgan", ["supported", "supported", "unclear"]),
        ("maya-chen", ["supported", "unclear", "supported"]),
        ("sam-rivera", ["unclear"] * 3),
    ],
)
def test_supplied_pdfs_extract_with_actual_worker_and_review_expected_evidence(
    name, expected
):
    try:
        PdfExtractor.ensure_tools()
    except ExtractionFailure:
        pytest.skip("Actual PDF extraction requires Linux Poppler worker tools")

    async def check():
        path = Path("docs/demo-resumes") / (name + ".pdf")
        with path.open("rb") as handle:
            result = await PdfExtractor(Settings(_env_file=None)).extract(
                handle, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
            )
        snapshot = {
            "job_title": "Backend Engineer",
            "criteria": CRITERIA,
            "sources": [{"id": "synthetic-pdf:" + name, "text": result.text}],
        }
        state = {}
        for _ in range(8):
            state = await agent_turn(
                "recruiter", snapshot, state, "Review this application", ReplayModel()
            )
            if state.get("report"):
                break
        assert (
            result.page_count == 1
            and [f["assessment"] for f in state["report"]["findings"]] == expected
        )

    asyncio.run(check())


@pytest.mark.parametrize(
    "body", ["No production PostgreSQL experience.", "با PostgreSQL تجربه کاری ندارم."]
)
def test_narrow_quotes_cannot_remove_negation(body):
    snapshot = {
        "job_title": "Backend",
        "criteria": [CRITERIA[1]],
        "sources": [{"id": "r1", "text": body}],
    }
    start = body.index("PostgreSQL")
    w = []
    hit = {
        "source_id": "r1",
        "start": start,
        "end": start + len("PostgreSQL"),
        "quote": "PostgreSQL",
    }
    register_evidence(hit, w)
    with pytest.raises(AgentFailure, match="NEGATED_EVIDENCE"):
        validate_review(
            {
                "findings": {
                    "postgresql": {"assessment": "supported", "evidence_ids": ["e1"]}
                }
            },
            snapshot,
            w,
        )


def test_unknown_handles_and_foreign_tools_fail_closed():
    snapshot = {"criteria": [CRITERIA[0]], "sources": []}
    with pytest.raises(AgentFailure, match="EVIDENCE_ID_UNKNOWN"):
        validate_review(
            {
                "findings": {
                    "python": {"assessment": "supported", "evidence_ids": ["e999"]}
                }
            },
            snapshot,
            [],
        )
    with pytest.raises(AgentFailure, match="TOOL_NOT_ALLOWED"):
        execute_tool("applicant", "search_resume", {"query": "Python"}, {}, {})
    assert not search_sources([{"id": "r1", "text": "Used JavaScript"}], "Java")
    assert search_sources([{"id": "r1", "text": "Built C and C++ services"}], "C++")


def test_final_report_cannot_bypass_token_budget(tmp_path):
    class CostlyFinal(ReplayModel):
        async def choose(self, kind, snapshot, state):
            call, _ = await super().choose(kind, snapshot, state)
            return call, [2000, 1] if call["name"] == "submit_review" else [1, 1]

    async def check():
        engine, factory, settings, _ids = await database(tmp_path)
        settings = settings.model_copy(update={"agent_max_tokens": 2000})
        try:
            worker = AgentWorker(factory, settings, live_model=CostlyFinal())
            rid, token = await worker.claim()
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                run.mode, run.model = "live", settings.agent_model
                await session.commit()
            await worker.process(rid, token)
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                assert (
                    run.status == "failed"
                    and run.failure_code == "TOKEN_BUDGET_EXCEEDED"
                    and run.report is None
                )
                assert run.input_tokens + run.output_tokens > settings.agent_max_tokens
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_cancellation_during_model_inference_wins_over_late_result(tmp_path):
    async def check():
        engine, factory, settings, ids = await database(tmp_path)
        try:
            worker = AgentWorker(factory, settings)
            rid, token = await worker.claim()

            class CancellingModel(ReplayModel):
                async def choose(self, kind, snapshot, state):
                    async with factory() as session:
                        await AgentWorkspaceService(session, settings).cancel(
                            ids["org"], rid, await session.get(User, ids["owner"])
                        )
                    return await super().choose(kind, snapshot, state)

            async with factory() as session:
                run = await session.get(AgentRun, rid)
                run.mode, run.model = "live", settings.agent_model
                await session.commit()
            worker.live_model = CancellingModel()
            await worker.process(rid, token)
            async with factory() as session:
                run = await session.get(AgentRun, rid)
                assert (
                    run.status == "cancelled" and run.steps == 0 and run.report is None
                )
        finally:
            await engine.dispose()

    asyncio.run(check())
