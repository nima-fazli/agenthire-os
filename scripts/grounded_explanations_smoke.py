"""Own-tenant real-DB grounding gate; --live-model also tests Qwen3 and HTTP."""

import argparse
import asyncio
import hashlib
import json
import os
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.local_chat import ChatResult, LocalChatGenerator
from app.core.tokens import create_access_token
from app.db.session import async_session_factory, engine
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentExtraction,
    Job,
    Organization,
    OrganizationMembership,
    User,
)
from app.models.job_matching import JobMatchProfile
from app.schemas.grounded_explanations import ExplanationRequest
from app.schemas.job_matching import JobMatchProfileWrite
from app.services.grounded_explanations import GroundedExplanationService
from app.services.job_matching import JobMatchingService
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.grounded_explanations_evaluation import evaluate, load_reference


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ReferenceGenerator:
    async def generate(self, messages, schema):
        data = json.loads(messages[1]["content"])
        return ChatResult({"quotes": [{"criterion": item["key"], "source": item["source"], "quote": item["q"]}
                                     for item in data["criteria"]]}, "f" * 64, 100, 30)


class MutatingGenerator:
    def __init__(self, mutation):
        self.mutation = mutation

    async def generate(self, messages, schema):
        result = await ReferenceGenerator().generate(messages, schema)
        await self.mutation()
        return result


async def run(live=False):
    reference = load_reference()
    settings = get_settings().model_copy(update={"explanations_enabled": True})
    generator = LocalChatGenerator(settings.chat_base_url, timeout_seconds=settings.chat_timeout_seconds) if live else ReferenceGenerator()
    user, org, foreign, job, foreign_candidate = (uuid4() for _ in range(5))
    candidates = {case["key"]: uuid4() for case in reference["cases"]}
    documents, observations, digest = {}, [], None
    scope = {"organization_id": org, "user_id": user, "job_id": job}
    try:
        async with async_session_factory() as session:
            session.add_all([User(id=user, email=f"brief-{user.hex}@example.com", password_hash="synthetic"),
                Organization(id=org, name="Brief fixture", slug="brief-" + org.hex),
                Organization(id=foreign, name="Excluded fixture", slug="brief-" + foreign.hex)])
            await session.flush()
            session.add(OrganizationMembership(organization_id=org, user_id=user))
            session.add(Job(id=job, organization_id=org, title="Reference role", description="Synthetic role"))
            session.add(Candidate(id=foreign_candidate, organization_id=foreign, full_name="Excluded"))
            session.add_all([Candidate(id=identifier, organization_id=org, full_name="Reference " + key)
                             for key, identifier in candidates.items()])
            await session.flush()
            for case in reference["cases"]:
                text = case["text"]
                if text is None:
                    continue
                document, source = uuid4(), uuid4()
                documents[case["key"]] = (document, source)
                session.add(CandidateDocument(id=document, organization_id=org, candidate_id=candidates[case["key"]],
                    uploaded_by_user_id=user, filename="synthetic.pdf", content_type="application/pdf", size_bytes=100,
                    sha256=sha(document.hex), storage_key=document.hex + ".pdf", status="ready"))
                await session.flush()
                session.add(DocumentExtraction(document_id=document, status="succeeded", attempts=1, text=text,
                    page_count=1, completed_at=datetime.now(UTC)))
                await session.flush()
                session.add(DocumentChunkSet(id=source, document_id=document, source_document_sha256=sha(document.hex),
                    source_text_sha256=sha(text), source_char_count=len(text), page_count=1,
                    chunker_version="brief-fixture-v1", chunk_max_chars=1200, chunk_overlap_chars=0, chunk_count=1))
                await session.flush()
                session.add(DocumentChunk(chunk_set_id=source, position=0, start_offset=0, end_offset=len(text),
                                          text=text, sha256=sha(text)))
            await session.commit()

        async with async_session_factory() as session:
            matching = JobMatchingService(session, settings)
            service = GroundedExplanationService(session, settings, generator)
            for case in reference["cases"]:
                await matching.put_profile(JobMatchProfileWrite(criteria=[
                    {"key": "skill", "label": "Source mention", "q": case["q"], "importance": "required"},
                    {"key": "missing", "label": "Rust", "q": "Rust", "importance": "preferred"}]), **scope)
                started = time.perf_counter()
                record = {"case": case["key"]}
                try:
                    page = await service.explain(ExplanationRequest(language=case["language"]),
                                                 candidate_id=candidates[case["key"]], **scope)
                    record.update(status="ok", result=page.model_dump(mode="json"))
                    if page.generator_used:
                        digest = digest or page.model_digest
                except AppError as error:
                    record.update(status="rejected", code=error.code)
                document, source = documents.get(case["key"], (None, None))
                record.update(elapsed_ms=(time.perf_counter() - started) * 1000,
                              document_id=str(document), chunk_set_id=str(source))
                observations.append(record)
            report = evaluate(reference, observations, model_kind="live" if live else "fixture",
                              model_digest=digest, source_kind="real_stack")
            print(json.dumps(report, indent=2))
            if not report["gate_passed"]:
                raise SmokeFailure("Grounded reference gate failed")
            try:
                await service.explain(ExplanationRequest(), candidate_id=foreign_candidate, **scope)
            except AppError as error:
                if error.code != "CANDIDATE_NOT_FOUND":
                    raise
            else:
                raise SmokeFailure("Foreign candidate reached explanation")
        log_ok("English/Persian quotes, explicit missing evidence, injection guard and tenant scope")

        if live:
            token = create_access_token(subject=user, settings=settings)
            url = os.environ.get("AGENTHIRE_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
            request = urllib.request.Request(url + f"/organizations/{org}/jobs/{job}/candidates/{candidates['english']}/grounded-explanation",
                data=b'{"language":"en"}', headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})

            def read_api():
                with urllib.request.urlopen(request, timeout=settings.chat_timeout_seconds + 30) as response:
                    page = json.load(response)
                    if (response.headers.get("Cache-Control") != "private, no-store" or not page["generator_used"] or
                        page["model_digest"] != digest or page["criteria"][1]["citation"] is not None):
                        raise SmokeFailure("Live explanation HTTP contract failed")

            await asyncio.to_thread(read_api)
            log_ok("Real CPU model and authenticated private explanation HTTP")

        document, original_source = documents["english"]
        text = reference["cases"][0]["text"]
        for mode in ("profile", "deleting", "latest", "membership"):
            newer = uuid4()

            async def mutate(mode=mode, newer=newer):
                async with async_session_factory() as session:
                    if mode == "profile":
                        await session.execute(update(JobMatchProfile).where(JobMatchProfile.job_id == job)
                                              .values(revision=JobMatchProfile.revision + 1))
                    elif mode == "deleting":
                        await session.execute(update(CandidateDocument).where(CandidateDocument.id == document).values(status="deleting"))
                    elif mode == "latest":
                        session.add(DocumentChunkSet(id=newer, document_id=document, source_document_sha256=sha(document.hex),
                            source_text_sha256=sha(text), source_char_count=len(text), page_count=1,
                            chunker_version="newer-empty-brief", chunk_max_chars=1200, chunk_overlap_chars=0,
                            chunk_count=1, created_at=datetime.now(UTC) + timedelta(seconds=1)))
                    else:
                        await session.execute(delete(OrganizationMembership).where(
                            OrganizationMembership.organization_id == org, OrganizationMembership.user_id == user))
                    await session.commit()

            async with async_session_factory() as session:
                service = GroundedExplanationService(session, settings, MutatingGenerator(mutate))
                try:
                    await service.explain(ExplanationRequest(), candidate_id=candidates["english"], **scope)
                except AppError as error:
                    expected = "ORGANIZATION_NOT_FOUND" if mode == "membership" else "EXPLANATION_SNAPSHOT_CHANGED"
                    if error.code != expected:
                        raise
                else:
                    raise SmokeFailure("Changed evidence or membership returned generated output")
            async with async_session_factory() as session:
                if mode == "deleting":
                    await session.execute(update(CandidateDocument).where(CandidateDocument.id == document).values(status="ready"))
                elif mode == "latest":
                    await session.execute(delete(DocumentChunkSet).where(DocumentChunkSet.id == newer))
                elif mode == "membership":
                    session.add(OrganizationMembership(organization_id=org, user_id=user))
                await session.commit()
        log_ok("Deterministic real-DB profile/deletion/latest/membership changes discard generated output")

        async with async_session_factory() as session:
            await session.execute(update(DocumentChunk).where(DocumentChunk.chunk_set_id == original_source)
                                  .values(sha256="0" * 64))
            await session.commit()
            service = GroundedExplanationService(session, settings, ReferenceGenerator())
            try:
                await service.explain(ExplanationRequest(), candidate_id=candidates["english"], **scope)
            except AppError as error:
                if error.code != "EXPLANATION_SNAPSHOT_CHANGED":
                    raise
            else:
                raise SmokeFailure("Corrupt source reached generation")
        log_ok("Stored hashes are recomputed before source text reaches the model")
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(JobMatchProfile).where(JobMatchProfile.job_id == job))
            await session.execute(delete(Job).where(Job.id == job))
            await session.execute(delete(CandidateDocument).where(CandidateDocument.id.in_([item[0] for item in documents.values()])))
            await session.execute(delete(Candidate).where(Candidate.id.in_([*candidates.values(), foreign_candidate])))
            await session.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id == org))
            await session.execute(delete(Organization).where(Organization.id.in_([org, foreign])))
            await session.execute(delete(User).where(User.id == user))
            await session.commit()
        await engine.dispose()
    log_ok("Only this smoke's random-ID synthetic metadata was cleaned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.live_model))
    print("[success] Grounded explanations real-stack gate passed.")


if __name__ == "__main__":
    main()
