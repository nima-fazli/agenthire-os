"""Two-tenant synthetic API fixture retained until its owned stack is removed."""

import argparse
import asyncio
import hashlib
import json

import asyncpg

from app.core.benchmark_metrics import Measurements
from app.core.config import get_settings
from scripts.benchmark_http import BenchmarkClient, BenchmarkFailure
from scripts.candidate_document_smoke import checked_binary, connection, sample_pdf
from scripts.docker_smoke import SMOKE_PASSWORD, SmokeFailure
from scripts.recovery_objects import require_scope
from scripts.workload_benchmark import Workload, WorkloadConfig


def fixture_ids(seed):
    if not isinstance(seed, str) or len(seed) != 32 or any(char not in "0123456789abcdef" for char in seed):
        raise ValueError("Invalid recovery fixture identity.")
    return [hashlib.sha256((seed + str(index)).encode()).hexdigest()[:32] for index in range(2)]


def seed_fixture(seed):
    for identity in fixture_ids(seed):
        measurements = Measurements()
        workload = Workload(BenchmarkClient("http://api:8000", measurements), measurements,
                            WorkloadConfig(items=1, concurrency=1), run_id=identity)
        workload.prepare()
        workload.one(0)


async def fixture_rows(seed, *, require_vectors=True):
    database = await connection()
    try:
        async with database.transaction(readonly=True):
            await database.execute("SET LOCAL statement_timeout = '3000ms'")
            result = []
            for identity in fixture_ids(seed):
                rows = await database.fetch("""
                    SELECT o.id AS organization, j.id AS job, c.id AS candidate, d.id AS document,
                           d.uploaded_by_user_id AS owner,
                           a.status AS application_status, e.status AS extraction_status,
                           (SELECT count(*) FROM document_chunks ch JOIN document_chunk_sets cs
                            ON cs.id=ch.chunk_set_id WHERE cs.document_id=d.id) AS chunks
                    FROM organizations o JOIN jobs j ON j.organization_id=o.id
                    JOIN candidates c ON c.organization_id=o.id
                    JOIN candidate_documents d ON d.candidate_id=c.id AND d.organization_id=o.id
                    JOIN applications a ON a.candidate_id=c.id AND a.job_id=j.id
                    JOIN document_extractions e ON e.document_id=d.id
                    WHERE o.slug=$1
                """, "workload-" + identity)
                if (len(rows) != 1 or rows[0]["application_status"] != "screening"
                        or rows[0]["extraction_status"] != "succeeded" or rows[0]["chunks"] < 1):
                    raise ValueError("Recovery fixture state was not preserved.")
                row = dict(rows[0])
                if require_vectors:
                    vectors = await database.fetch("""
                        SELECT v.embedding::text AS value FROM document_embeddings v
                        JOIN document_embedding_jobs e ON e.id=v.job_id
                        JOIN document_chunk_sets s ON s.id=e.chunk_set_id
                        WHERE s.document_id=$1 AND e.status='succeeded'
                    """, row["document"])
                    expected = [1.0] + [0.0] * 1023
                    if len(vectors) != row["chunks"] or any(json.loads(vector["value"]) != expected for vector in vectors):
                        raise ValueError("Recovery vector values were not preserved.")
                    row["vectors"] = len(vectors)
                result.append(row)
            return result
    finally:
        await database.close()


async def seed_vectors(seed):
    from app.db.session import async_session_factory, engine
    from app.schemas.document_embeddings import EmbeddingRequest
    from app.services.candidate_document import CandidateDocumentService
    from app.services.document_embeddings import (
        DocumentEmbeddingService,
        EmbeddingProcessor,
    )
    from scripts.document_embeddings_smoke import FixtureEncoder

    settings = get_settings().model_copy(update={"semantic_enabled": True})
    encoder = FixtureEncoder()
    try:
        for row in await fixture_rows(seed, require_vectors=False):
            async with async_session_factory() as session:
                documents = CandidateDocumentService(session, None, max_bytes=settings.document_max_bytes)
                service = DocumentEmbeddingService(session, documents, encoder, settings)
                job, created = await service.request(row["document"], EmbeddingRequest(),
                    organization_id=row["organization"], candidate_id=row["candidate"], user_id=row["owner"])
                if not created:
                    raise ValueError("Recovery vector fixture already exists.")
                job_id = job.id
            if not await EmbeddingProcessor(async_session_factory, encoder, settings).run_one(job_id=job_id):
                raise ValueError("Recovery vector fixture was not processed.")
    finally:
        await engine.dispose()


def verify_fixture(seed):
    rows = asyncio.run(fixture_rows(seed))
    tokens = []
    for identity, row in zip(fixture_ids(seed), rows, strict=True):
        client = BenchmarkClient("http://api:8000", Measurements())
        token = client.call("POST", "/auth/login", phase="login", payload={
            "email": "workload-" + identity + "@example.com", "password": SMOKE_PASSWORD,
        })["access_token"]
        tokens.append(token)
        path = f"/organizations/{row['organization']}/candidates/{row['candidate']}/documents/{row['document']}"
        response = checked_binary("GET", path + "/content", token=token, expected=200, step="recovered PDF bytes")
        if response.body != sample_pdf():
            raise ValueError("Recovered PDF bytes changed.")
        page = client.call("GET", f"/organizations/{row['organization']}/jobs/{row['job']}/candidate-retrieval?limit=8",
                           phase="retrieval", token=token)
        if (page.get("total") != 1 or len(page["items"]) != 1
                or page["items"][0]["candidate_id"] != str(row["candidate"])
                or page["items"][0]["document_id"] != str(row["document"])):
            raise ValueError("Recovered retrieval state changed.")
    foreign = rows[1]
    path = f"/organizations/{foreign['organization']}/candidates/{foreign['candidate']}/documents/{foreign['document']}/content"
    checked_binary("GET", path, token=tokens[0], expected=404, error_code="ORGANIZATION_NOT_FOUND", step="recovered tenant isolation")
    checked_binary("GET", path, expected=401, error_code="INVALID_ACCESS_TOKEN", step="recovered authentication")
    return {"organizations": 2, "documents": 2, "pdf_downloads_verified": 2,
            "lexical_retrievals_verified": 2, "tenant_isolation_verified": True,
            "embedding_vectors_verified": sum(row["vectors"] for row in rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "verify"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        require_scope(args.project)
        fixture_ids(args.run_id)
        if args.action == "seed":
            seed_fixture(args.run_id)
            asyncio.run(seed_vectors(args.run_id))
        report = verify_fixture(args.run_id)
        print(json.dumps({"status": "passed", **report, "models_checked": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, BenchmarkFailure,
            SmokeFailure, asyncpg.PostgresError, asyncpg.InterfaceError):
        print(json.dumps({"status": "failed", "diagnostic": "recovery_fixture_unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
