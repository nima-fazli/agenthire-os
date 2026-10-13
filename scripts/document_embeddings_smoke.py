"""Real DB pipeline smoke; --live-model also calls the installed local CPU model."""

import argparse
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.core.semantic_embeddings import DIMENSIONS, ModelIdentity, normalized_vector
from app.db.session import async_session_factory, engine
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentExtraction,
    Organization,
    OrganizationMembership,
    User,
)
from app.repositories.document_embeddings import (
    DocumentEmbeddingRepository,
    EmbeddingTask,
)
from app.schemas.document_embeddings import EmbeddingRequest
from app.services.candidate_document import CandidateDocumentService
from app.services.document_embeddings import (
    DocumentEmbeddingService,
    EmbeddingProcessor,
)
from scripts.docker_smoke import SmokeFailure, log_ok

PASSAGES = (
    "I built Python APIs with FastAPI, PostgreSQL, and Docker.",
    "I specialize in watercolor painting and gallery exhibition curation.",
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class FixtureEncoder:
    async def identity(self):
        return ModelIdentity("f" * 64)

    async def encode(self, texts, identity):
        # Only isolated synthetic fixture jobs use these deterministic vectors.
        return tuple(normalized_vector([1.0] + [0.0] * (DIMENSIONS - 1)) for _ in texts)


async def run(live: bool):
    settings = get_settings().model_copy(update={"semantic_enabled": True})
    encoder = LocalEmbeddingEncoder(settings.embedding_base_url) if live else FixtureEncoder()
    user_id, org_id, candidate_id, document_id, source_id = (uuid4() for _ in range(5))
    job_id = None
    text = "\n".join(PASSAGES)
    try:
        async with async_session_factory() as session:
            session.add_all([
                User(id=user_id, email=f"embedding-{user_id.hex}@example.com", password_hash="synthetic"),
                Organization(id=org_id, name="Synthetic embedding fixture", slug=f"embedding-{org_id.hex}"),
            ])
            await session.flush()
            session.add_all([
                Candidate(id=candidate_id, organization_id=org_id, full_name="Synthetic embedding candidate"),
                OrganizationMembership(organization_id=org_id, user_id=user_id),
            ])
            await session.flush()
            session.add(CandidateDocument(id=document_id, organization_id=org_id, candidate_id=candidate_id,
                uploaded_by_user_id=user_id, filename="synthetic.pdf", content_type="application/pdf",
                size_bytes=100, sha256=sha("synthetic PDF"), storage_key=f"{document_id.hex}.pdf", status="ready"))
            await session.flush()
            session.add(DocumentExtraction(document_id=document_id, status="succeeded", attempts=1,
                text=text, page_count=1, completed_at=datetime.now(UTC)))
            await session.flush()
            session.add(DocumentChunkSet(id=source_id, document_id=document_id,
                source_document_sha256=sha("synthetic PDF"), source_text_sha256=sha(text),
                source_char_count=len(text), page_count=1, chunker_version="smoke-v1",
                chunk_max_chars=1200, chunk_overlap_chars=0, chunk_count=2))
            await session.flush()
            offset = 0
            for position, passage in enumerate(PASSAGES):
                session.add(DocumentChunk(chunk_set_id=source_id, position=position,
                    start_offset=offset, end_offset=offset + len(passage), text=passage, sha256=sha(passage)))
                offset += len(passage) + 1
            await session.commit()

        scope = {"organization_id": org_id, "candidate_id": candidate_id, "user_id": user_id}
        async with async_session_factory() as session:
            documents = CandidateDocumentService(session, None, max_bytes=settings.document_max_bytes)
            service = DocumentEmbeddingService(session, documents, encoder, settings)
            job, created = await service.request(document_id, EmbeddingRequest(), **scope)
            again, repeated = await service.request(document_id, EmbeddingRequest(), **scope)
            job_id = job.id
            if not created or repeated or again.id != job.id:
                raise SmokeFailure("Embedding request was not idempotent")
            repo = DocumentEmbeddingRepository(session)
            if await repo.get_scoped(job.id, organization_id=uuid4(), candidate_id=candidate_id, document_id=document_id):
                raise SmokeFailure("Embedding status crossed tenant scope")
            await session.rollback()
        log_ok("Versioned queue creation, idempotent request and tenant scope")

        async with async_session_factory() as session:
            repo = DocumentEmbeddingRepository(session)
            task = await repo.claim(max_attempts=3, lease_seconds=300, job_id=job_id)
            await session.commit()
            if task is None:
                raise SmokeFailure("Fixture embedding task could not be claimed")
            stale = EmbeddingTask(task.id, task.chunk_set_id, task.model_digest, task.chunk_count, uuid4())
            if await repo.finish(stale, (), (), "EMBEDDING_INTERNAL_ERROR"):
                raise SmokeFailure("Stale lease published a result")
            if await repo.claim(max_attempts=3, lease_seconds=300, job_id=job_id):
                raise SmokeFailure("Running task was claimed twice")
            await session.execute(update(DocumentEmbeddingJob).where(DocumentEmbeddingJob.id == job_id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
            if await repo.renew(task, 300):
                raise SmokeFailure("Expired lease renewed itself")
            await session.commit()
        log_ok("Claim exclusion, stale-result fencing and expired lease rejection")

        if not await EmbeddingProcessor(async_session_factory, encoder, settings).run_one(job_id=job_id):
            raise SmokeFailure("Fixture task was not processed")
        async with async_session_factory() as session:
            job = await session.get(DocumentEmbeddingJob, job_id)
            rows = (await session.execute(select(DocumentEmbedding).where(DocumentEmbedding.job_id == job_id)
                .order_by(DocumentEmbedding.position))).scalars().all()
            if job.status != "succeeded" or job.attempts != 2 or len(rows) != 2:
                raise SmokeFailure("Embedding publication was incomplete")
            if any(len(row.embedding) != DIMENSIONS for row in rows):
                raise SmokeFailure("Wrong vector dimensions were persisted")
            stats = await session.execute(select(func.vector_dims(DocumentEmbedding.embedding),
                func.vector_norm(DocumentEmbedding.embedding)).where(DocumentEmbedding.job_id == job_id))
            if any(dim != DIMENSIONS or not 0.999 <= norm <= 1.001 for dim, norm in stats):
                raise SmokeFailure("PostgreSQL vector invariants failed")
            try:
                async with session.begin_nested():
                    session.add(DocumentEmbedding(job_id=job_id, position=9, chunk_set_id=uuid4(),
                        chunk_sha256="a" * 64, embedding=rows[0].embedding))
                    await session.flush()
            except IntegrityError:
                pass
            else:
                raise SmokeFailure("PostgreSQL accepted mismatched embedding provenance")
        log_ok("Atomic complete publication, PostgreSQL vector round-trip and composite FKs")

        if live:
            queries = (
                "Find a backend engineer experienced with databases and API development.",
                "مهندس بک‌اند با تجربهٔ توسعهٔ API و پایگاه داده",
            )
            vectors = await encoder.encode(tuple(
                "Instruct: Retrieve resume passages relevant to this job requirement.\nQuery: " + query
                for query in queries
            ), ModelIdentity(job.model_digest))
            for vector in vectors:
                relevant = sum(a * b for a, b in zip(vector, rows[0].embedding, strict=True))
                unrelated = sum(a * b for a, b in zip(vector, rows[1].embedding, strict=True))
                if relevant <= unrelated:
                    raise SmokeFailure("Local model failed the basic bilingual fixture")
            log_ok("Real local CPU model, 1024 dimensions and basic Persian/English ordering")
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(CandidateDocument).where(CandidateDocument.id == document_id))
            remaining = await session.scalar(select(func.count()).select_from(DocumentEmbeddingJob)
                .where(DocumentEmbeddingJob.chunk_set_id == source_id))
            if remaining:
                raise SmokeFailure("Embedding jobs did not cascade after source deletion")
            await session.execute(delete(Candidate).where(Candidate.id == candidate_id))
            await session.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id == org_id))
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()
    log_ok("Fixture metadata and vectors were cleaned with source cascade")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.live_model))
    print("[success] Local embedding smoke passed: " + ("live model" if args.live_model else "DB pipeline fixture"))


if __name__ == "__main__":
    main()
