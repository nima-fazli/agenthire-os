"""Transactional public applications, scoped reviews, approvals and local outbox."""

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from app.core.agent_tools import AgentFailure, digest
from app.core.document_storage import LocalDocumentStorage
from app.core.errors import AppError, NotFoundError
from app.models.agent_workspace import (
    AgentEvent,
    AgentNotification,
    AgentOutbox,
    AgentRun,
    ApplicantAnswer,
    ApplicantIdentity,
    ApplicantSubmission,
    CareerPublication,
)
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_extraction import DocumentExtraction
from app.models.job import Job
from app.models.job_matching import JobMatchCriterion, JobMatchProfile
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.schemas.candidate_document import DocumentUpload
from app.services.access import AccessService


def now():
    return datetime.now(UTC)


def aware(value):
    return (
        value.replace(tzinfo=UTC)
        if value is not None and value.tzinfo is None
        else value
    )


def fail(code, message, status=409):
    return AppError(code=code, message=message, status_code=status)


def missing():
    return NotFoundError(
        code="PORTAL_RECORD_NOT_FOUND", message="This record is not available."
    )


def public_status(submission, application):
    if submission.state == "draft":
        return "Draft"
    if application.status in {"hired", "rejected"}:
        return "Hired" if application.status == "hired" else "Not selected"
    if submission.question_revision > submission.answered_revision:
        return "Additional information requested"
    return {
        "applied": "Received",
        "screening": "Under review",
        "interview": "Interview stage",
        "offer": "Offer stage",
    }.get(application.status, "Under review")


class AgentWorkspaceService:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings

    def enabled(self):
        if not self.settings.agents_enabled:
            raise fail(
                "AGENTS_DISABLED", "Start the stack with compose.agents.yaml.", 503
            )

    async def staff(self, organization_id, user_id, write=False):
        return await AccessService(self.session).authorize(
            organization_id,
            user_id,
            "POST" if write else "GET",
            f"/organizations/{organization_id}/agent-runs",
        )

    async def _user_lock(self, user_id):
        await self.session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

    async def verified(self, user):
        identity = await self.session.get(ApplicantIdentity, user.id)
        if (
            identity is None
            or identity.email != user.email
            or identity.verified_at is None
        ):
            raise fail(
                "EMAIL_VERIFICATION_REQUIRED",
                "Verify your email using the local Mailpit code.",
                403,
            )

    def _code_hash(self, user, code):
        return hmac.new(
            self.settings.jwt_secret.get_secret_value().encode(),
            f"{user.id}:{user.email}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def mail(self, key, email, subject, body):
        self.session.add(
            AgentOutbox(
                id=uuid4(),
                dedupe_key=key,
                recipient=email,
                subject=subject,
                body=body,
                status="pending",
                attempts=0,
            )
        )

    async def notify_company(self, organization_id, title, body):
        members = (
            (
                await self.session.execute(
                    select(OrganizationMembership.user_id)
                    .join(User, User.id == OrganizationMembership.user_id)
                    .where(
                        OrganizationMembership.organization_id == organization_id,
                        User.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for uid in members:
            self.session.add(
                AgentNotification(
                    user_id=uid, organization_id=organization_id, title=title, body=body
                )
            )

    def notify_applicant(self, submission, title, body):
        self.session.add(
            AgentNotification(user_id=submission.user_id, title=title, body=body)
        )

    async def verification_info(self, user):
        item = await self.session.get(ApplicantIdentity, user.id)
        return {
            "verified": bool(item and item.email == user.email and item.verified_at),
            "email": user.email,
        }

    async def request_verification(self, user):
        await self._user_lock(user.id)
        item = await self.session.get(ApplicantIdentity, user.id)
        if item and item.email == user.email and item.verified_at:
            return {"verified": True}
        if (
            item
            and item.requested_at
            and aware(item.requested_at) > now() - timedelta(minutes=1)
        ):
            raise fail(
                "VERIFICATION_THROTTLED",
                "Wait one minute before requesting another code.",
                429,
            )
        if item is None:
            item = ApplicantIdentity(user_id=user.id, email=user.email)
            self.session.add(item)
        code = f"{secrets.randbelow(1000000):06d}"
        item.email, item.verified_at, item.attempts = user.email, None, 0
        item.challenge_hash, item.challenge_expires_at, item.requested_at = (
            self._code_hash(user, code),
            now() + timedelta(minutes=15),
            now(),
        )
        self.mail(
            f"verify:{uuid4()}",
            user.email,
            "AgentHire — verify your applicant email",
            f"Your verification code is {code}. It expires in 15 minutes.\nEnter it in Applicant Portal. Local demo: captured by Mailpit.",
        )
        await self.session.commit()
        return {"queued": True, "verified": False}

    async def verify(self, user, data):
        await self._user_lock(user.id)
        item = await self.session.get(ApplicantIdentity, user.id)
        if (
            item is None
            or item.email != user.email
            or not item.challenge_hash
            or item.attempts >= 5
            or aware(item.challenge_expires_at) <= now()
        ):
            raise fail(
                "VERIFICATION_INVALID",
                "The code is unavailable or expired. Request a new code.",
                422,
            )
        item.attempts += 1
        if not hmac.compare_digest(
            item.challenge_hash, self._code_hash(user, data.code)
        ):
            await self.session.commit()
            raise fail("VERIFICATION_INVALID", "The code is incorrect.", 422)
        item.verified_at, item.challenge_hash, item.challenge_expires_at = (
            now(),
            None,
            None,
        )
        await self.session.commit()
        return {"verified": True}

    async def public_jobs(self, offset=0):
        rows = (
            await self.session.execute(
                select(Job, CareerPublication, Organization.name)
                .join(CareerPublication, CareerPublication.job_id == Job.id)
                .join(Organization, Organization.id == Job.organization_id)
                .where(CareerPublication.published.is_(True), Job.status == "open")
                .order_by(Job.created_at.desc(), Job.id)
                .limit(21)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                {
                    "id": j.id,
                    "title": j.title,
                    "company": name,
                    "description": p.public_description,
                }
                for j, p, name in rows[:20]
            ],
            "has_more": len(rows) > 20,
            "offset": offset,
        }

    async def published_job(self, job_id, lock=False):
        query = (
            select(Job, CareerPublication)
            .join(CareerPublication, CareerPublication.job_id == Job.id)
            .where(
                Job.id == job_id,
                Job.status == "open",
                CareerPublication.published.is_(True),
            )
        )
        if lock:
            query = query.with_for_update(of=[Job, CareerPublication])
        row = (await self.session.execute(query)).first()
        if row is None:
            raise missing()
        return row

    async def publication(self, organization_id, job_id, user, data=None):
        await self.staff(organization_id, user.id, data is not None)
        query = select(Job).where(
            Job.id == job_id, Job.organization_id == organization_id
        )
        if data is not None:
            query = query.with_for_update()
        job = (await self.session.execute(query)).scalar_one_or_none()
        if job is None:
            raise missing()
        pub = await self.session.get(CareerPublication, job_id)
        if data is not None:
            if data.published and job.status != "open":
                raise fail(
                    "PUBLICATION_JOB_NOT_OPEN", "Open the job before publishing it."
                )
            if pub is None:
                pub = CareerPublication(job_id=job_id, organization_id=organization_id)
                self.session.add(pub)
            pub.public_description, pub.published = (
                data.public_description,
                data.published,
            )
            await self.session.commit()
        return {
            "job_id": job_id,
            "published": bool(pub and pub.published),
            "public_description": pub.public_description if pub else "",
        }

    async def draft(self, user, data):
        await self.verified(user)
        await self._user_lock(user.id)
        job, _ = await self.published_job(data.job_id)
        item = (
            await self.session.execute(
                select(ApplicantSubmission).where(
                    ApplicantSubmission.user_id == user.id,
                    ApplicantSubmission.job_id == job.id,
                )
            )
        ).scalar_one_or_none()
        if item and item.state == "submitted":
            raise fail(
                "APPLICATION_ALREADY_SUBMITTED",
                "Open My applications to track your existing application.",
            )
        if item is None:
            count = (
                await self.session.execute(
                    select(func.count())
                    .select_from(ApplicantSubmission)
                    .where(
                        ApplicantSubmission.user_id == user.id,
                        ApplicantSubmission.created_at > now() - timedelta(days=1),
                    )
                )
            ).scalar_one()
            if count >= 20:
                raise fail("PORTAL_RATE_LIMIT", "Daily application limit reached.", 429)
            item = ApplicantSubmission(
                id=uuid4(),
                organization_id=job.organization_id,
                job_id=job.id,
                user_id=user.id,
                email=user.email,
                state="draft",
                question_revision=0,
                answered_revision=0,
            )
            self.session.add(item)
        item.full_name, item.resume_text = data.full_name, data.resume_text
        await self.session.commit()
        return {"id": item.id, "state": item.state}

    async def own_submission(self, submission_id, user, lock=False):
        query = select(ApplicantSubmission).where(
            ApplicantSubmission.id == submission_id,
            ApplicantSubmission.user_id == user.id,
        )
        if lock:
            query = query.with_for_update()
        item = (await self.session.execute(query)).scalar_one_or_none()
        if item is None:
            raise missing()
        return item

    async def upload_pdf(self, user, submission_id, filename, request):
        await self.verified(user)
        item = await self.own_submission(submission_id, user, True)
        if item.state != "draft":
            raise fail("SUBMISSION_IMMUTABLE", "A submitted resume cannot be replaced.")
        try:
            filename = DocumentUpload(filename=filename).filename
        except ValueError:
            raise fail(
                "INVALID_FILENAME",
                "Use a PDF filename without paths or control characters.",
                422,
            ) from None
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/pdf"
        ):
            raise fail("UNSUPPORTED_DOCUMENT_TYPE", "Upload a PDF file.", 415)
        raw = bytearray()
        try:
            async with asyncio.timeout(self.settings.document_upload_timeout_seconds):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > min(
                        self.settings.document_max_bytes, 5 * 1024 * 1024
                    ):
                        raise fail(
                            "DOCUMENT_TOO_LARGE",
                            "Applicant PDFs must be at most 5 MiB.",
                            413,
                        )
                    raw.extend(chunk)
        except TimeoutError:
            raise fail("UPLOAD_TIMEOUT", "Upload timed out. Try again.", 408) from None
        if not re.fullmatch(rb"%PDF-(?:1\.[0-7]|2\.0)", raw[:8]) or not raw[
            -1024:
        ].rstrip().endswith(b"%%EOF"):
            raise fail("INVALID_PDF", "The file is not a PDF container.", 422)
        item.pdf_content, item.pdf_filename = bytes(raw), filename
        await self.session.commit()
        return {"uploaded": True, "size_bytes": len(raw)}

    def new_run(self, submission, user_id, mode, kind="recruiter", goal=None):
        run = AgentRun(
            id=uuid4(),
            organization_id=submission.organization_id,
            submission_id=submission.id,
            requested_by_user_id=user_id,
            kind=kind,
            mode=mode,
            goal=goal
            or "Review every saved criterion using source evidence. Clarify only unclear experience.",
            model=self.settings.agent_model if mode == "live" else "replay-v1",
            status="queued",
            checkpoint={},
            steps=0,
            attempts=0,
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
        )
        self.session.add(run)
        return run

    async def submit(self, user, submission_id, mode):
        await self.verified(user)
        item = await self.own_submission(submission_id, user, True)
        if item.state == "submitted":
            return {"id": item.id, "state": item.state, "already_submitted": True}
        await self.published_job(item.job_id, True)
        if len(item.resume_text.strip()) < 40 and item.pdf_content is None:
            raise fail(
                "RESUME_REQUIRED",
                "Upload a PDF or paste at least 40 characters of resume text.",
                422,
            )
        candidate = Candidate(
            id=uuid4(),
            organization_id=item.organization_id,
            full_name=item.full_name,
            email=item.email,
        )
        self.session.add(candidate)
        await self.session.flush()
        application = Application(
            id=uuid4(),
            organization_id=item.organization_id,
            job_id=item.job_id,
            candidate_id=candidate.id,
            status="applied",
        )
        self.session.add(application)
        await self.session.flush()
        storage, stored = (
            LocalDocumentStorage(self.settings.document_storage_path),
            None,
        )
        try:
            if item.pdf_content:
                if self.session.bind.dialect.name == "postgresql":
                    await self.session.execute(
                        text("LOCK TABLE candidate_documents IN ROW EXCLUSIVE MODE")
                    )

                async def content():
                    yield item.pdf_content

                stored = await storage.save_pdf(content(), max_bytes=5 * 1024 * 1024)
                document = CandidateDocument(
                    id=uuid4(),
                    organization_id=item.organization_id,
                    candidate_id=candidate.id,
                    uploaded_by_user_id=user.id,
                    filename=item.pdf_filename,
                    content_type="application/pdf",
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    storage_key=stored.storage_key,
                    status="ready",
                )
                self.session.add(document)
                await self.session.flush()
                self.session.add(
                    DocumentExtraction(
                        document_id=document.id, status="queued", attempts=0
                    )
                )
                item.document_id = document.id
            (
                item.candidate_id,
                item.application_id,
                item.state,
                item.submitted_at,
                item.pdf_content,
            ) = candidate.id, application.id, "submitted", now(), None
            run = self.new_run(item, user.id, mode)
            self.mail(
                f"receipt:{item.id}",
                item.email,
                "AgentHire — application received",
                "Your application has been received. Sign in to Applicant Portal to track it. Reference: "
                + str(item.id),
            )
            self.notify_applicant(
                item,
                "Application received",
                "Your resume has been received. Track it here.",
            )
            await self.notify_company(
                item.organization_id,
                "New application",
                "A new application is ready for review: " + item.full_name,
            )
            await self.session.commit()
            return {"id": item.id, "state": "submitted", "run_id": run.id}
        except BaseException:
            await self.session.rollback()
            if stored:
                persisted = (
                    await self.session.execute(
                        select(CandidateDocument.id).where(
                            CandidateDocument.storage_key == stored.storage_key
                        )
                    )
                ).first()
                if persisted is None:
                    await storage.delete(stored.storage_key)
            raise

    async def portal_list(self, user):
        rows = (
            await self.session.execute(
                select(ApplicantSubmission, Job, Application)
                .join(Job, Job.id == ApplicantSubmission.job_id)
                .outerjoin(
                    Application, Application.id == ApplicantSubmission.application_id
                )
                .where(ApplicantSubmission.user_id == user.id)
                .order_by(ApplicantSubmission.created_at.desc())
                .limit(50)
            )
        ).all()
        return [
            {
                "id": s.id,
                "job_id": s.job_id,
                "job_title": j.title,
                "full_name": s.full_name,
                "state": s.state,
                "status": public_status(s, a),
                "question": s.public_question,
                "question_revision": s.question_revision,
                "answered_revision": s.answered_revision,
                "has_pdf": bool(s.document_id or s.pdf_content),
                "submitted_at": s.submitted_at,
            }
            for s, j, a in rows
        ]

    async def answer(self, user, submission_id, data):
        await self.verified(user)
        item = await self.own_submission(submission_id, user, True)
        if (
            item.state != "submitted"
            or data.question_revision != item.question_revision
            or not item.public_question
        ):
            raise fail("QUESTION_CHANGED", "Refresh the application before answering.")
        application = await self.session.get(Application, item.application_id)
        if application.status in {"hired", "rejected"}:
            raise fail("APPLICATION_CLOSED", "This application process has completed.")
        if item.answered_revision == data.question_revision:
            return {"saved": True, "already_answered": True}
        self.session.add(
            ApplicantAnswer(
                submission_id=item.id,
                question_revision=data.question_revision,
                text=data.text,
            )
        )
        item.answered_revision = data.question_revision
        run = self.new_run(item, user.id, data.mode)
        await self.notify_company(
            item.organization_id,
            "Applicant replied",
            "A clarification answer is ready for review.",
        )
        await self.session.commit()
        return {"saved": True, "run_id": run.id}

    async def list_submissions(self, oid, user):
        await self.staff(oid, user.id)
        rows = (
            await self.session.execute(
                select(ApplicantSubmission, Job.title, Application.status)
                .join(Job, Job.id == ApplicantSubmission.job_id)
                .join(Application, Application.id == ApplicantSubmission.application_id)
                .where(
                    ApplicantSubmission.organization_id == oid,
                    ApplicantSubmission.state == "submitted",
                )
                .order_by(ApplicantSubmission.submitted_at.desc())
                .limit(50)
            )
        ).all()
        return [
            {
                "id": s.id,
                "full_name": s.full_name,
                "job_title": title,
                "status": status,
                "submitted_at": s.submitted_at,
                "candidate_id": s.candidate_id,
                "application_id": s.application_id,
            }
            for s, title, status in rows
        ]

    async def run_limit(self, uid):
        await self._user_lock(uid)
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.requested_by_user_id == uid,
                    AgentRun.created_at > now() - timedelta(days=1),
                )
            )
        ).scalar_one()
        if count >= 50:
            raise fail("AGENT_RATE_LIMIT", "Daily run limit reached.", 429)

    async def create_run(self, oid, sid, user, data):
        await self.staff(oid, user.id, True)
        await self.run_limit(user.id)
        submission = (
            await self.session.execute(
                select(ApplicantSubmission)
                .where(
                    ApplicantSubmission.id == sid,
                    ApplicantSubmission.organization_id == oid,
                    ApplicantSubmission.state == "submitted",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if submission is None:
            raise missing()
        return await self._queue_run(submission, user, data, "recruiter")

    async def ask(self, user, sid, data):
        await self.verified(user)
        await self.run_limit(user.id)
        submission = await self.own_submission(sid, user, True)
        if submission.state != "submitted":
            raise missing()
        return await self._queue_run(submission, user, data, "applicant")

    async def _queue_run(self, submission, user, data, kind):
        active = (
            await self.session.execute(
                select(AgentRun.id).where(
                    AgentRun.submission_id == submission.id,
                    AgentRun.kind == kind,
                    AgentRun.status.in_(["queued", "running"]),
                )
            )
        ).first()
        if active:
            return {"id": active.id, "already_queued": True}
        run = self.new_run(submission, user.id, data.mode, kind, data.goal)
        await self.session.commit()
        return {"id": run.id}

    async def get_run(self, oid, rid, user, write=False):
        await self.staff(oid, user.id, write)
        query = select(AgentRun).where(
            AgentRun.id == rid, AgentRun.organization_id == oid
        )
        if write:
            query = query.with_for_update()
        run = (await self.session.execute(query)).scalar_one_or_none()
        if run is None:
            raise missing()
        return run

    async def run_view(self, run, events=False):
        result = {
            k: getattr(run, k)
            for k in (
                "id",
                "submission_id",
                "kind",
                "mode",
                "goal",
                "model",
                "status",
                "steps",
                "attempts",
                "report",
                "source_fingerprint",
                "failure_code",
                "input_tokens",
                "output_tokens",
                "elapsed_ms",
                "created_at",
                "updated_at",
                "approved_at",
            )
        }
        result["model_digest"] = run.checkpoint.get("model_digest")
        if events:
            rows = (
                (
                    await self.session.execute(
                        select(AgentEvent)
                        .where(AgentEvent.run_id == run.id)
                        .order_by(AgentEvent.sequence)
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            result["events"] = [
                {
                    "sequence": e.sequence,
                    "type": e.event_type,
                    "payload": e.payload,
                    "created_at": e.created_at,
                }
                for e in rows
            ]
        return result

    async def runs(self, oid, user):
        await self.staff(oid, user.id)
        rows = (
            (
                await self.session.execute(
                    select(AgentRun)
                    .where(AgentRun.organization_id == oid)
                    .order_by(AgentRun.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [await self.run_view(r) for r in rows]

    async def own_agent_run(self, user, rid):
        run = (
            await self.session.execute(
                select(AgentRun).where(
                    AgentRun.id == rid,
                    AgentRun.kind == "applicant",
                    AgentRun.requested_by_user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise missing()
        return {
            "id": run.id,
            "status": run.status,
            "mode": run.mode,
            "answer": run.report.get("answer") if run.report else None,
            "message": "The assistant could not complete this request. Try again later."
            if run.status == "failed"
            else None,
        }

    async def snapshot(self, run, lock=False):
        s = await self.session.get(ApplicantSubmission, run.submission_id)
        if (
            s is None
            or s.organization_id != run.organization_id
            or s.state != "submitted"
        ):
            raise AgentFailure("SOURCE_UNAVAILABLE")
        jq = select(Job).where(
            Job.id == s.job_id, Job.organization_id == s.organization_id
        )
        job = (
            await self.session.execute(jq.with_for_update() if lock else jq)
        ).scalar_one()
        app = await self.session.get(Application, s.application_id)
        pub = await self.session.get(CareerPublication, job.id)
        if run.kind == "applicant":
            value = {
                "public_job": {
                    "title": job.title,
                    "description": pub.public_description
                    if pub and pub.published
                    else "The public description has been withdrawn.",
                },
                "public_status": public_status(s, app),
                "public_question": s.public_question,
            }
            return value, digest(value)
        if app.status in {"hired", "rejected"}:
            raise AgentFailure("APPLICATION_CLOSED")
        pq = select(JobMatchProfile).where(JobMatchProfile.job_id == job.id)
        profile = (
            await self.session.execute(pq.with_for_update() if lock else pq)
        ).scalar_one_or_none()
        criteria = (
            (
                await self.session.execute(
                    select(JobMatchCriterion)
                    .where(JobMatchCriterion.job_id == job.id)
                    .order_by(JobMatchCriterion.position)
                )
            )
            .scalars()
            .all()
        )
        if profile is None or not criteria:
            raise AgentFailure("JOB_CRITERIA_REQUIRED")
        sources = (
            [{"id": f"resume:{s.id}", "text": s.resume_text}] if s.resume_text else []
        )
        if s.document_id:
            document, extraction = (
                await self.session.get(CandidateDocument, s.document_id),
                await self.session.get(DocumentExtraction, s.document_id),
            )
            if (
                document is None
                or document.organization_id != s.organization_id
                or document.candidate_id != s.candidate_id
                or document.status != "ready"
            ):
                raise AgentFailure("SOURCE_UNAVAILABLE")
            if extraction is None or extraction.status in {"queued", "running"}:
                raise AgentFailure("PDF_EXTRACTION_PENDING")
            if extraction.status != "succeeded":
                raise AgentFailure("PDF_EXTRACTION_FAILED")
            sources.append({"id": f"pdf:{s.document_id}", "text": extraction.text})
        answers = (
            (
                await self.session.execute(
                    select(ApplicantAnswer)
                    .where(ApplicantAnswer.submission_id == s.id)
                    .order_by(ApplicantAnswer.question_revision)
                )
            )
            .scalars()
            .all()
        )
        sources.extend({"id": f"answer:{a.id}", "text": a.text} for a in answers)
        if not sources or sum(len(x["text"].encode()) for x in sources) > 100000:
            raise AgentFailure("SOURCE_BUDGET_EXCEEDED")
        value = {
            "job_title": job.title,
            "job_status": job.status,
            "job_updated": str(job.updated_at),
            "application_status": app.status,
            "criteria_revision": profile.revision,
            "criteria": [
                {k: getattr(c, k) for k in ("key", "label", "query_text", "importance")}
                for c in criteria
            ],
            "sources": sources,
        }
        return value, digest(value)

    async def approve(self, oid, rid, user, data):
        run = await self.get_run(oid, rid, user, True)
        s = (
            await self.session.execute(
                select(ApplicantSubmission)
                .where(ApplicantSubmission.id == run.submission_id)
                .with_for_update()
            )
        ).scalar_one()
        if run.kind != "recruiter":
            raise missing()
        if run.approved_at and data.decision == "approve":
            return {"status": "completed", "already_approved": True}
        if (
            run.status != "waiting_approval"
            or data.source_fingerprint != run.source_fingerprint
        ):
            raise fail("REVIEW_CHANGED", "Refresh the review before approving it.")
        try:
            _, fingerprint = await self.snapshot(run, True)
        except AgentFailure:
            raise fail(
                "REVIEW_STALE", "Sources are unavailable. Create a fresh review."
            ) from None
        if fingerprint != run.source_fingerprint:
            raise fail(
                "REVIEW_STALE",
                "Sources, criteria or application changed. Create a fresh review.",
            )
        question = run.report.get("question") if data.decision == "approve" else None
        if question:
            if s.question_revision >= 5:
                raise fail(
                    "CLARIFICATION_LIMIT",
                    "Continue with a human review after five clarifications.",
                )
            s.public_question, s.question_revision = question, s.question_revision + 1
            self.mail(
                f"clarification:{run.id}",
                s.email,
                "AgentHire — additional information requested",
                question
                + "\nSign in to Applicant Portal to answer. Reference: "
                + str(s.id),
            )
            self.notify_applicant(s, "Additional information requested", question)
        run.status, run.approved_at = (
            ("completed", now()) if data.decision == "approve" else ("cancelled", None)
        )
        run.lease_token = run.lease_expires_at = None
        self.session.add(
            AgentEvent(
                run_id=run.id,
                sequence=run.steps + 1,
                event_type="human_approved"
                if data.decision == "approve"
                else "human_dismissed",
                payload={
                    "actor_user_id": str(user.id),
                    "question_queued": bool(question),
                },
            )
        )
        await self.session.commit()
        return {"status": run.status, "question_queued": bool(question)}

    async def cancel(self, oid, rid, user):
        run = await self.get_run(oid, rid, user, True)
        if run.status in {"queued", "running", "waiting_approval"}:
            run.status, run.lease_token, run.lease_expires_at = "cancelled", None, None
        await self.session.commit()
        return {"status": run.status}

    async def notifications(self, user, oid=None):
        if oid:
            await self.staff(oid, user.id)
        rows = (
            (
                await self.session.execute(
                    select(AgentNotification)
                    .where(
                        AgentNotification.user_id == user.id,
                        AgentNotification.organization_id == oid,
                    )
                    .order_by(AgentNotification.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [
            {k: getattr(n, k) for k in ("id", "title", "body", "read_at", "created_at")}
            for n in rows
        ]

    async def read_notification(self, user, nid):
        item = (
            await self.session.execute(
                select(AgentNotification)
                .where(
                    AgentNotification.id == nid, AgentNotification.user_id == user.id
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is None:
            raise missing()
        if item.organization_id:
            await self.staff(item.organization_id, user.id)
        item.read_at = now()
        await self.session.commit()
        return {"read": True}

    async def mail_status(self, oid, user, retry=False):
        await self.staff(oid, user.id, retry)
        submissions = (
            await self.session.execute(
                select(ApplicantSubmission.id, ApplicantSubmission.application_id)
                .where(ApplicantSubmission.organization_id == oid)
                .order_by(ApplicantSubmission.created_at.desc())
                .limit(1000)
            )
        ).all()
        runs = (
            (
                await self.session.execute(
                    select(AgentRun.id)
                    .where(
                        AgentRun.organization_id == oid,
                        AgentRun.approved_at.is_not(None),
                    )
                    .order_by(AgentRun.created_at.desc())
                    .limit(1000)
                )
            )
            .scalars()
            .all()
        )
        keys = [f"receipt:{s.id}" for s in submissions] + [
            f"clarification:{rid}" for rid in runs
        ]
        keys += [
            f"status:{s.application_id}:{state}"
            for s in submissions
            for state in ["screening", "interview", "offer", "hired", "rejected"]
        ]
        query = (
            select(AgentOutbox)
            .where(AgentOutbox.dedupe_key.in_(keys))
            .order_by(AgentOutbox.created_at.desc())
            .limit(50)
        )
        if retry:
            query = query.where(AgentOutbox.status == "failed").with_for_update(
                skip_locked=True
            )
        rows = (await self.session.execute(query)).scalars().all() if keys else []
        queued = 0
        if retry:
            for row in rows:
                if row.status == "failed":
                    (
                        row.status,
                        row.attempts,
                        row.failure_code,
                        row.lease_token,
                        row.lease_expires_at,
                    ) = "pending", 0, None, None, None
                    queued += 1
            await self.session.commit()
            return {"queued": queued}
        return [
            {
                k: getattr(r, k)
                for k in (
                    "id",
                    "recipient",
                    "subject",
                    "status",
                    "attempts",
                    "failure_code",
                    "created_at",
                )
            }
            for r in rows
        ]


async def queue_status_notice(session, application, settings):
    submission = (
        await session.execute(
            select(ApplicantSubmission).where(
                ApplicantSubmission.application_id == application.id,
                ApplicantSubmission.organization_id == application.organization_id,
            )
        )
    ).scalar_one_or_none()
    if submission:
        svc = AgentWorkspaceService(session, settings)
        status = public_status(submission, application)
        svc.mail(
            f"status:{application.id}:{application.status}",
            submission.email,
            "AgentHire — application status updated",
            "Your application status: " + status,
        )
        svc.notify_applicant(
            submission,
            "Application status updated",
            "Your application status: " + status,
        )
