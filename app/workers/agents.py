"""Leased SQL agent worker with fenced checkpoints and a separate local mail loop."""

import asyncio
import logging
import smtplib
import sys
import time
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select

from app.core.agent_runtime import OllamaAgentModel, ReplayModel, agent_turn
from app.core.agent_tools import AgentFailure
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import async_session_factory
from app.models.agent_workspace import (
    AgentEvent,
    AgentOutbox,
    AgentRun,
    ApplicantSubmission,
)
from app.models.user import User
from app.services.agent_workspace import AgentWorkspaceService, now

log = logging.getLogger("agenthire.agents")
HEARTBEAT = Path("/tmp/agenthire-agents.heartbeat")


class AgentWorker:
    def __init__(self, factory, settings, live_model=None):
        self.factory, self.settings = factory, settings
        self.live_model = live_model or OllamaAgentModel(settings)

    async def claim(self):
        async with self.factory() as session:
            row = (
                await session.execute(
                    select(AgentRun)
                    .where(
                        or_(
                            and_(
                                AgentRun.status == "queued",
                                or_(
                                    AgentRun.lease_expires_at.is_(None),
                                    AgentRun.lease_expires_at <= now(),
                                ),
                            ),
                            and_(
                                AgentRun.status == "running",
                                AgentRun.lease_expires_at <= now(),
                            ),
                        )
                    )
                    .order_by(AgentRun.created_at, AgentRun.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.attempts >= 3:
                row.status, row.failure_code, row.lease_token, row.lease_expires_at = (
                    "failed",
                    "WORKER_RETRY_LIMIT",
                    None,
                    None,
                )
                await session.commit()
                return None
            row.status, row.attempts = "running", row.attempts + 1
            row.lease_token, row.lease_expires_at = (
                uuid4(),
                now() + timedelta(seconds=self.settings.agent_lease_seconds),
            )
            await session.commit()
            return row.id, row.lease_token

    async def _fail(self, rid, token, code):
        async with self.factory() as session:
            run = (
                await session.execute(
                    select(AgentRun).where(AgentRun.id == rid).with_for_update()
                )
            ).scalar_one_or_none()
            if run is None or run.status != "running" or run.lease_token != token:
                return
            if code == "PDF_EXTRACTION_PENDING" and run.created_at.replace(
                tzinfo=now().tzinfo
            ) > now() - timedelta(minutes=10):
                run.status, run.attempts, run.lease_token, run.lease_expires_at = (
                    "queued",
                    max(0, run.attempts - 1),
                    None,
                    now() + timedelta(seconds=3),
                )
            else:
                run.status, run.failure_code, run.lease_token, run.lease_expires_at = (
                    "failed",
                    code,
                    None,
                    None,
                )
                session.add(
                    AgentEvent(
                        run_id=rid,
                        sequence=run.steps + 1,
                        event_type="failed",
                        payload={"code": code},
                    )
                )
                await AgentWorkspaceService(session, self.settings).notify_company(
                    run.organization_id,
                    "Agent review needs attention",
                    "Inspect the run. Code: " + code,
                )
            await session.commit()

    async def _authorized(self, session, run):
        user, submission = (
            await session.get(User, run.requested_by_user_id),
            await session.get(ApplicantSubmission, run.submission_id),
        )
        if user is None or not user.is_active or submission is None:
            raise AgentFailure("ACTOR_PERMISSION_CHANGED")
        if run.kind == "applicant" and submission.user_id != user.id:
            raise AgentFailure("ACTOR_PERMISSION_CHANGED")
        if run.kind == "recruiter" and submission.user_id != user.id:
            try:
                await AgentWorkspaceService(session, self.settings).staff(
                    run.organization_id, user.id, True
                )
            except AppError:
                raise AgentFailure("ACTOR_PERMISSION_CHANGED") from None

    async def process(self, rid, token):
        try:
            while True:
                async with self.factory() as session:
                    run = await session.get(AgentRun, rid)
                    if (
                        run is None
                        or run.status != "running"
                        or run.lease_token != token
                    ):
                        return
                    await self._authorized(session, run)
                    snapshot, fingerprint = await AgentWorkspaceService(
                        session, self.settings
                    ).snapshot(run)
                    if run.source_fingerprint and run.source_fingerprint != fingerprint:
                        raise AgentFailure("SOURCE_CHANGED")
                    if run.steps >= self.settings.agent_max_steps:
                        raise AgentFailure("STEP_BUDGET_EXCEEDED")
                    if (
                        run.input_tokens + run.output_tokens
                        >= self.settings.agent_max_tokens
                    ):
                        raise AgentFailure("TOKEN_BUDGET_EXCEEDED")
                    if run.elapsed_ms >= self.settings.agent_max_elapsed_seconds * 1000:
                        raise AgentFailure("TIME_BUDGET_EXCEEDED")
                    if run.mode == "live" and run.model != self.settings.agent_model:
                        raise AgentFailure("MODEL_CONFIGURATION_CHANGED")
                    state, kind, mode, goal = (
                        run.checkpoint,
                        run.kind,
                        run.mode,
                        run.goal,
                    )
                started = time.monotonic()
                try:
                    async with asyncio.timeout(
                        self.settings.agent_timeout_seconds + 25
                    ):
                        updated = await agent_turn(
                            kind,
                            snapshot,
                            state,
                            goal,
                            ReplayModel() if mode == "replay" else self.live_model,
                        )
                except TimeoutError:
                    raise AgentFailure("MODEL_TIMEOUT") from None
                elapsed = int((time.monotonic() - started) * 1000)
                async with self.factory() as session:
                    run = (
                        await session.execute(
                            select(AgentRun).where(AgentRun.id == rid).with_for_update()
                        )
                    ).scalar_one_or_none()
                    if (
                        run is None
                        or run.status != "running"
                        or run.lease_token != token
                    ):
                        return
                    await self._authorized(session, run)
                    _, current = await AgentWorkspaceService(
                        session, self.settings
                    ).snapshot(run)
                    if current != fingerprint:
                        raise AgentFailure("SOURCE_CHANGED")
                    run.source_fingerprint, run.checkpoint = fingerprint, dict(updated)
                    run.steps += 1
                    run.input_tokens += updated["usage"][0]
                    run.output_tokens += updated["usage"][1]
                    run.elapsed_ms += elapsed
                    run.lease_expires_at = now() + timedelta(
                        seconds=self.settings.agent_lease_seconds
                    )
                    session.add(
                        AgentEvent(
                            run_id=rid,
                            sequence=run.steps,
                            event_type="tool_completed",
                            payload={
                                **updated["event"],
                                "mode": mode,
                                "model_digest": updated.get("model_digest"),
                                "elapsed_ms": elapsed,
                            },
                        )
                    )
                    failure = (
                        "TOKEN_BUDGET_EXCEEDED"
                        if run.input_tokens + run.output_tokens
                        > self.settings.agent_max_tokens
                        else "TIME_BUDGET_EXCEEDED"
                        if run.elapsed_ms
                        > self.settings.agent_max_elapsed_seconds * 1000
                        else None
                    )
                    if failure:
                        (
                            run.status,
                            run.failure_code,
                            run.lease_token,
                            run.lease_expires_at,
                        ) = "failed", failure, None, None
                        session.add(
                            AgentEvent(
                                run_id=rid,
                                sequence=run.steps + 1,
                                event_type="failed",
                                payload={"code": failure},
                            )
                        )
                        await AgentWorkspaceService(
                            session, self.settings
                        ).notify_company(
                            run.organization_id,
                            "Agent review needs attention",
                            "Inspect the run. Code: " + failure,
                        )
                    elif updated.get("report"):
                        run.report, run.status = (
                            updated["report"],
                            "waiting_approval" if kind == "recruiter" else "completed",
                        )
                        run.lease_token = run.lease_expires_at = None
                        if kind == "recruiter":
                            await AgentWorkspaceService(
                                session, self.settings
                            ).notify_company(
                                run.organization_id,
                                "Review ready for approval",
                                "A source-backed review is ready in Agent Center.",
                            )
                    await session.commit()
                    if failure or updated.get("report"):
                        return
        except AgentFailure as error:
            await self._fail(rid, token, error.code)
        except Exception:  # noqa: BLE001 - redact private model/source payloads at the worker boundary
            log.error("agent_run_internal_error", extra={"run_id": str(rid)})
            await self._fail(rid, token, "AGENT_INTERNAL_ERROR")

    async def once(self):
        claim = await self.claim()
        if claim:
            await self.process(*claim)
        return bool(claim)


def deliver(message, settings):
    if settings.agent_mail_host not in {"localhost", "127.0.0.1", "mailpit"}:
        raise AgentFailure("SMTP_HOST_BLOCKED")
    email = EmailMessage()
    email["From"], email["To"] = (
        "AgentHire Demo <no-reply@agenthire.test>",
        message["recipient"],
    )
    email["Subject"], email["Message-ID"] = (
        message["subject"],
        f"<{message['id']}@agenthire.test>",
    )
    email.set_content(message["body"])
    with smtplib.SMTP(
        settings.agent_mail_host, settings.agent_mail_port, timeout=10
    ) as smtp:
        smtp.send_message(email)


async def mail_once(factory, settings, sender=deliver):
    async with factory() as session:
        row = (
            await session.execute(
                select(AgentOutbox)
                .where(
                    or_(
                        and_(
                            AgentOutbox.status == "pending",
                            or_(
                                AgentOutbox.lease_expires_at.is_(None),
                                AgentOutbox.lease_expires_at <= now(),
                            ),
                        ),
                        and_(
                            AgentOutbox.status == "sending",
                            AgentOutbox.lease_expires_at <= now(),
                        ),
                    )
                )
                .order_by(AgentOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if row.attempts >= 3:
            row.status, row.failure_code, row.lease_token, row.lease_expires_at = (
                "failed",
                "SMTP_RETRY_LIMIT",
                None,
                None,
            )
            await session.commit()
            return True
        token = uuid4()
        row.status, row.lease_token, row.lease_expires_at = (
            "sending",
            token,
            now() + timedelta(seconds=120),
        )
        row.attempts += 1
        data = {k: getattr(row, k) for k in ("id", "recipient", "subject", "body")}
        await session.commit()
    failure = False
    try:
        await asyncio.to_thread(sender, data, settings)
    except Exception:  # noqa: BLE001 - no message content or operational secrets in logs
        failure = True
    async with factory() as session:
        row = (
            await session.execute(
                select(AgentOutbox)
                .where(AgentOutbox.id == data["id"])
                .with_for_update()
            )
        ).scalar_one()
        if row.lease_token != token or row.status != "sending":
            return True
        row.status = (
            ("failed" if row.attempts >= 3 else "pending") if failure else "sent"
        )
        row.failure_code = "SMTP_UNAVAILABLE" if failure else None
        row.sent_at = None if failure else now()
        row.lease_token = None
        row.lease_expires_at = (
            now() + timedelta(seconds=row.attempts * 5) if failure else None
        )
        await session.commit()
    return True


async def main():
    settings = get_settings()
    if not settings.agents_enabled:
        raise SystemExit("Enable AGENTHIRE_AGENTS_ENABLED before starting this worker.")
    worker = AgentWorker(async_session_factory, settings)

    async def runs():
        while True:
            HEARTBEAT.touch()
            await worker.once()
            await asyncio.sleep(1)

    async def mails():
        count = 0
        while True:
            try:
                await mail_once(async_session_factory, settings)
                if count % 3600 == 0:
                    async with async_session_factory() as session:
                        await session.execute(
                            delete(ApplicantSubmission).where(
                                ApplicantSubmission.state == "draft",
                                ApplicantSubmission.created_at
                                < now() - timedelta(days=1),
                            )
                        )
                        await session.execute(
                            delete(AgentOutbox).where(
                                AgentOutbox.dedupe_key.like("verify:%"),
                                AgentOutbox.status.in_(["sent", "failed"]),
                                AgentOutbox.created_at < now() - timedelta(days=1),
                            )
                        )
                        await session.commit()
                count += 1
            except Exception:  # noqa: BLE001
                log.error("outbox_poll_failed")
            await asyncio.sleep(1)

    await asyncio.gather(runs(), mails())


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        raise SystemExit(
            0
            if HEARTBEAT.exists() and time.time() - HEARTBEAT.stat().st_mtime < 300
            else 1
        )
    asyncio.run(main())
