"""Scoped real-DB retrieval comparison; --live-model uses the installed CPU model."""

import argparse
import asyncio
import hashlib
import json
import os
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.core.semantic_embeddings import (
    DIMENSIONS,
    ENCODING_VERSION,
    MODEL_TAG,
    ModelIdentity,
)
from app.db.session import async_session_factory, engine
from app.models import (
    Application,
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentExtraction,
    Job,
    Organization,
    OrganizationMembership,
    User,
)
from app.models.job_search_profile import JobSearchProfile
from app.schemas.job_retrieval import JobCandidateQuery, JobSearchProfileWrite
from app.schemas.semantic_retrieval import SemanticDocumentQuery, SemanticJobQuery
from app.services.job_retrieval import JobRetrievalService
from app.services.semantic_retrieval import SemanticRetrievalService
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.fixture_session import fixture_session
from scripts.semantic_retrieval_evaluation import evaluate, load_reference


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ReferenceEncoder:
    async def identity(self):
        return ModelIdentity("f" * 64)

    async def encode(self, texts, identity):
        return tuple(tuple(1.0 if index == (1 if "watercolor" in text else 0) else 0.0
                           for index in range(DIMENSIONS)) for text in texts)


class MutatingEncoder:
    def __init__(self, inner, mutation):
        self.inner, self.mutation = inner, mutation

    async def identity(self):
        return await self.inner.identity()

    async def encode(self, texts, identity):
        values = await self.inner.encode(texts, identity)
        await self.mutation()
        return values


async def run(live=False):
    reference = load_reference()
    settings = get_settings().model_copy(update={"semantic_enabled": True})
    encoder = LocalEmbeddingEncoder(settings.embedding_base_url) if live else ReferenceEncoder()
    identity = await encoder.identity()
    passages = reference["passages"]
    vectors = await encoder.encode((passages["backend"], passages["artist"]), identity)
    user, org, foreign, job = (uuid4() for _ in range(4))
    candidates = {key: uuid4() for key in passages} | {"foreign": uuid4()}
    documents, observations = [], []
    try:
        async with async_session_factory() as session:
            session.add_all([User(id=user, email=f"semantic-{user.hex}@example.com", password_hash="synthetic"),
                Organization(id=org, name="Semantic fixture", slug=f"semantic-{org.hex}"),
                Organization(id=foreign, name="Excluded fixture", slug=f"semantic-{foreign.hex}")])
            await session.flush()
            access_session, token = fixture_session(user, settings)
            session.add(access_session)
            session.add(OrganizationMembership(organization_id=org, user_id=user))
            session.add(Job(id=job, organization_id=org, title="Reference role", description="Synthetic role"))
            session.add_all([Candidate(id=identifier, organization_id=foreign if key == "foreign" else org,
                                      full_name="Reference " + key) for key, identifier in candidates.items()])
            await session.flush()
            session.add(Application(organization_id=org, job_id=job, candidate_id=candidates["backend"]))
            for key in ("backend", "backend", "artist", "pending", "foreign"):
                text = passages.get(key, passages["backend"])
                document, source, embedding_job = uuid4(), uuid4(), uuid4()
                documents.append((document, source, key))
                session.add(CandidateDocument(id=document, organization_id=foreign if key == "foreign" else org,
                    candidate_id=candidates[key], uploaded_by_user_id=user, filename="synthetic.pdf",
                    content_type="application/pdf", size_bytes=100, sha256=sha(document.hex),
                    storage_key=document.hex + ".pdf", status="ready"))
                await session.flush()
                session.add(DocumentExtraction(document_id=document, status="succeeded", attempts=1,
                    text=text, page_count=1, completed_at=datetime.now(UTC)))
                await session.flush()
                session.add(DocumentChunkSet(id=source, document_id=document, source_document_sha256=sha(document.hex),
                    source_text_sha256=sha(text), source_char_count=len(text), page_count=1,
                    chunker_version="semantic-fixture-v1", chunk_max_chars=1200, chunk_overlap_chars=0, chunk_count=1))
                await session.flush()
                session.add(DocumentChunk(chunk_set_id=source, position=0, start_offset=0, end_offset=len(text),
                                          text=text, sha256=sha(text)))
                if key != "pending":
                    session.add(DocumentEmbeddingJob(id=embedding_job, chunk_set_id=source, model_tag=MODEL_TAG,
                        model_digest=identity.digest, encoding_version=ENCODING_VERSION, source_text_sha256=sha(text),
                        chunk_count=1, status="succeeded", attempts=1, completed_at=datetime.now(UTC)))
                    await session.flush()
                    session.add(DocumentEmbedding(job_id=embedding_job, chunk_set_id=source, position=0,
                        chunk_sha256=sha(text), embedding=vectors[1 if key == "artist" else 0]))
                await session.flush()
            await session.commit()

        scope = {"organization_id": org, "user_id": user, "job_id": job}
        keys = {identifier: key for key, identifier in candidates.items()}
        async with async_session_factory() as session:
            lexical = JobRetrievalService(session, settings)
            semantic = SemanticRetrievalService(session, settings, encoder)
            for case in reference["cases"]:
                await lexical.put_profile(JobSearchProfileWrite(q=case["q"]), **scope)
                for mode in ("lexical", "semantic", "hybrid"):
                    started = time.perf_counter()
                    page = (await lexical.retrieve(JobCandidateQuery(limit=1), **scope) if mode == "lexical"
                            else await semantic.search(SemanticJobQuery(mode=mode, limit=1), **scope))
                    observations.append({"case": case["key"], "mode": mode,
                        "ranking": [keys.get(hit.candidate_id, "unjudged") for hit in page.items],
                        "elapsed_ms": (time.perf_counter() - started) * 1000})
                    await session.rollback()
            report = evaluate(reference, observations, model_digest=identity.digest,
                              model_kind="live" if live else "fixture", source_kind="real_stack")
            print(json.dumps(report, indent=2))
            if not report["gate_passed"]:
                raise SmokeFailure("Semantic reference comparison failed")
            only = await semantic.search(SemanticJobQuery(applicants_only=True), **scope)
            if [hit.candidate_id for hit in only.items] != [candidates["backend"]]:
                raise SmokeFailure("Applicant filter or candidate grouping failed")
            doc = await semantic.search(SemanticDocumentQuery(q="Python", limit=50), organization_id=org, user_id=user)
            if doc.eligible_chunks != 4 or doc.embedded_chunks != 3:
                raise SmokeFailure("Coverage or tenant scope failed")
            if any(hit.candidate_id == candidates["foreign"] for hit in doc.items):
                raise SmokeFailure("Foreign tenant reached retrieval")
            try:
                await semantic.search(SemanticDocumentQuery(q="Python"), organization_id=foreign, user_id=user)
            except AppError as error:
                if error.code != "ORGANIZATION_NOT_FOUND":
                    raise
            else:
                raise SmokeFailure("Nonmember retrieval was accepted")
        log_ok("Three-mode quality comparison, candidate grouping, coverage and tenant/applicant scope")

        if live:
            url = os.environ.get("AGENTHIRE_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
            request = urllib.request.Request(url + f"/organizations/{org}/semantic-search",
                data=json.dumps({"q": "Python", "mode": "semantic", "limit": 1}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})

            def read_api():
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = json.load(response)
                    if response.headers.get("Cache-Control") != "private, no-store" or not payload["items"]:
                        raise SmokeFailure("Live semantic HTTP contract failed")

            await asyncio.to_thread(read_api)
            log_ok("Real CPU model and authenticated private HTTP endpoint")

        document, source, _ = documents[0]
        async with async_session_factory() as session:
            second_source = documents[1][1]
            second_job = await session.scalar(select(DocumentEmbeddingJob.id).where(
                DocumentEmbeddingJob.chunk_set_id == second_source))
            await session.execute(delete(DocumentEmbedding).where(DocumentEmbedding.job_id == second_job))
            await session.commit()
            service = SemanticRetrievalService(session, settings, encoder)
            query = SemanticDocumentQuery(q="Python", document_id=documents[1][0], mode="semantic")
            page = await service.search(query, organization_id=org, user_id=user)
            if page.items or page.embedded_chunks or page.eligible_chunks != 1:
                raise SmokeFailure("Incomplete vector set remained searchable")
            page = await service.search(query.model_copy(update={"mode": "hybrid"}), organization_id=org, user_id=user)
            if not page.items or any(e.embedding_job_id is not None for hit in page.items for e in hit.evidence):
                raise SmokeFailure("Unembedded lexical witness lost its explicit provenance")
            other_digest = "0" * 64 if identity.digest != "0" * 64 else "a" * 64
            await session.execute(update(DocumentEmbeddingJob).where(DocumentEmbeddingJob.chunk_set_id == source)
                                  .values(model_digest=other_digest))
            await session.commit()
            page = await service.search(SemanticDocumentQuery(q="Python", document_id=document, mode="semantic"),
                                        organization_id=org, user_id=user)
            if page.items or page.embedded_chunks:
                raise SmokeFailure("Incompatible model space reached retrieval")
            session.add(DocumentChunkSet(document_id=document, source_document_sha256=sha(document.hex),
                source_text_sha256=sha(passages["backend"]), source_char_count=len(passages["backend"]),
                page_count=1, chunker_version="newer-empty-fixture", chunk_max_chars=1200,
                chunk_overlap_chars=0, chunk_count=1, created_at=datetime.now(UTC) + timedelta(seconds=1)))
            await session.commit()
            page = await service.search(SemanticDocumentQuery(q="Python", document_id=document), organization_id=org, user_id=user)
            if page.items or page.eligible_chunks:
                raise SmokeFailure("Older chunk set resurfaced")
            artist = next(doc for doc, _, key in documents if key == "artist")
            await session.execute(update(CandidateDocument).where(CandidateDocument.id == artist).values(status="deleting"))
            await session.commit()
            page = await service.search(SemanticDocumentQuery(q="watercolor", document_id=artist), organization_id=org, user_id=user)
            if page.items:
                raise SmokeFailure("Deleting source remained searchable")
        log_ok("Incomplete/mixed model spaces, lexical-only coverage, latest-only and deleting sources")

        async def change_profile():
            async with async_session_factory() as session:
                await session.execute(update(JobSearchProfile).where(JobSearchProfile.job_id == job)
                                      .values(query_text="Python", revision=JobSearchProfile.revision + 1))
                await session.commit()

        async def revoke_membership():
            async with async_session_factory() as session:
                await session.execute(delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org, OrganizationMembership.user_id == user))
                await session.commit()

        for mutation, code in ((change_profile, "JOB_SEARCH_PROFILE_CHANGED"),
                               (revoke_membership, "ORGANIZATION_NOT_FOUND")):
            async with async_session_factory() as session:
                service = SemanticRetrievalService(session, settings, MutatingEncoder(encoder, mutation))
                try:
                    await service.search(SemanticJobQuery(), **scope)
                except AppError as error:
                    if error.code != code:
                        raise
                else:
                    raise SmokeFailure("Authorization/profile changed during encoding without rejection")
        log_ok("Profile revision and membership are rechecked after model encoding")
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(Application).where(Application.job_id == job))
            await session.execute(delete(JobSearchProfile).where(JobSearchProfile.job_id == job))
            await session.execute(delete(Job).where(Job.id == job))
            await session.execute(delete(CandidateDocument).where(CandidateDocument.id.in_([d for d, _, _ in documents])))
            await session.execute(delete(Candidate).where(Candidate.id.in_(list(candidates.values()))))
            await session.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id == org))
            await session.execute(delete(Organization).where(Organization.id.in_([org, foreign])))
            await session.execute(delete(User).where(User.id == user))
            await session.commit()
        await engine.dispose()
    log_ok("Synthetic fixture metadata, embeddings and profiles cleaned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.live_model))
    print("[success] Semantic retrieval real-stack comparison passed.")


if __name__ == "__main__":
    main()
