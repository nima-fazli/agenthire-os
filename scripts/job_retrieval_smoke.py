import asyncio
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import build_database_url
from app.repositories.job_retrieval import JobRetrievalRepository
from app.schemas.job_retrieval import JobCandidateQuery
from app.services.job_retrieval import JobRetrievalService
from scripts.application_smoke import checked_request, register_and_login, response_id
from scripts.candidate_document_smoke import (
    checked_binary,
    cleanup,
    connection,
    sample_pdf,
)
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.document_chunk_smoke import long_pdf
from scripts.document_extraction_smoke import wait_for_result
from scripts.document_search_smoke import seed_set, set_visibility


def equivalent_resume_pdf() -> bytes:
    return long_pdf() + b"\n"


async def verify_deadline(org: str, user: str, job: str) -> None:
    engine = create_async_engine(
        build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True
    )

    class SlowRepository(JobRetrievalRepository):
        @staticmethod
        def statement(**_):
            return select(func.pg_sleep(1))

    try:
        async with engine.connect() as database:
            original = (
                await database.execute(text("SHOW statement_timeout"))
            ).scalar_one()
            await database.rollback()
            async with AsyncSession(bind=database, expire_on_commit=False) as session:
                service = JobRetrievalService(
                    session,
                    get_settings().model_copy(
                        update={"document_search_timeout_ms": 100}
                    ),
                )
                service._repository = SlowRepository(session)
                try:
                    await service.retrieve(
                        JobCandidateQuery(),
                        organization_id=UUID(org),
                        user_id=UUID(user),
                        job_id=UUID(job),
                    )
                except AppError as error:
                    if (
                        error.code != "CANDIDATE_RETRIEVAL_TIMEOUT"
                        or error.status_code != 503
                    ):
                        raise SmokeFailure(
                            "Unexpected candidate retrieval cancellation"
                        ) from error
                else:
                    raise SmokeFailure("Slow candidate retrieval was not cancelled")
                if (await session.execute(text("SELECT 1"))).scalar_one() != 1:
                    raise SmokeFailure(
                        "Retrieval cancellation did not recover its transaction"
                    )
                await session.rollback()
            if (
                await database.execute(text("SHOW statement_timeout"))
            ).scalar_one() != original:
                raise SmokeFailure(
                    "Candidate retrieval timeout leaked beyond its transaction"
                )
        log_ok("real candidate retrieval cancellation rollback and timeout reset")
    finally:
        await engine.dispose()


async def cleanup_retrieval(slugs: list[str], emails: list[str]) -> None:
    database = await connection()
    try:
        await database.execute(
            "DELETE FROM applications WHERE organization_id IN "
            "(SELECT id FROM organizations WHERE slug=ANY($1::text[]))",
            slugs,
        )
    finally:
        await database.close()
    await cleanup(slugs, emails)


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="retrieval owner")
    outsider = register_and_login(emails[1], label="retrieval outsider")
    organizations = [
        response_id(
            checked_request(
                "POST",
                "/organizations",
                token=owner,
                payload={"name": "Retrieval Smoke", "slug": slug},
                expected=201,
                step="retrieval organization",
            ),
            step="organization",
        )
        for slug in slugs
    ]
    org = organizations[0]

    def create_job(organization):
        return response_id(
            checked_request(
                "POST",
                f"/organizations/{organization}/jobs",
                token=owner,
                payload={
                    "title": "Backend engineer",
                    "description": "Python SQL",
                    "status": "open",
                },
                expected=201,
                step="retrieval job",
            ),
            step="job",
        )

    job, other_job, empty_job = (
        create_job(org),
        create_job(organizations[1]),
        create_job(org),
    )
    base = f"/organizations/{org}/jobs/{job}"

    def put(q, **kwargs):
        return checked_request(
            "PUT",
            base + "/search-profile",
            token=owner,
            payload={"q": q},
            step="explicit job search profile",
            **kwargs,
        ).body

    def retrieve(**params):
        return checked_request(
            "GET",
            base + "/candidate-retrieval?" + urlencode(params),
            token=owner,
            step="one best resume witness per candidate",
        ).body

    for suffix in ("/search-profile", "/candidate-retrieval"):
        checked_request(
            "GET",
            base + suffix,
            token=owner,
            expected=404,
            error_code="JOB_SEARCH_PROFILE_NOT_FOUND",
            step="unconfigured job profile",
        )
    barrier = Barrier(2)

    def concurrent_put(_):
        barrier.wait(timeout=10)
        return put("Python SQL")

    with ThreadPoolExecutor(max_workers=2) as executor:
        profiles = list(executor.map(concurrent_put, range(2)))
    if profiles[0] != profiles[1] or profiles[0]["revision"] != 1:
        raise SmokeFailure("Concurrent identical profile writes were not idempotent")
    if put("  Python SQL  ") != profiles[0]:
        raise SmokeFailure("Unchanged profile changed its revision or metadata")
    log_ok("concurrent PostgreSQL profile creation and unchanged retries")
    checked_request(
        "PUT",
        f"/organizations/{organizations[1]}/jobs/{other_job}/search-profile",
        token=owner,
        payload={"q": "Python SQL"},
        step="other tenant profile",
    )

    sources = {}

    def upload(organization, candidate, pdf):
        path = f"/organizations/{organization}/candidates/{candidate}/documents"
        document = json.loads(
            checked_binary(
                "POST",
                path + "?filename=resume.pdf",
                token=owner,
                data=pdf,
                expected=201,
                step="retrieval resume upload",
            ).body
        )
        return document, path + "/" + document["id"]

    def candidate(organization, name):
        return response_id(
            checked_request(
                "POST",
                f"/organizations/{organization}/candidates",
                token=owner,
                payload={"full_name": name},
                expected=201,
                step="retrieval candidate",
            ),
            step="candidate",
        )

    def prepare(organization, candidate_id, pdf):
        document, path = upload(organization, candidate_id, pdf)
        checked_request(
            "POST",
            path + "/extraction",
            token=owner,
            payload={},
            expected=202,
            step="extract retrieval resume",
        )
        wait_for_result(path + "/extraction", owner, "succeeded")
        source = checked_request(
            "GET", path + "/extraction/text", token=owner, step="retrieval source text"
        ).body["text"]
        chunk_set = checked_request(
            "POST",
            path + "/chunks",
            token=owner,
            payload={},
            expected=201,
            step="chunk retrieval source",
        ).body
        if chunk_set["chunk_count"] < 2:
            raise SmokeFailure(
                "Retrieval fixture did not produce multiple matching chunks"
            )
        sources[document["id"]] = (document, source)
        return document, path

    ada, grace = candidate(org, "Retrieval Ada"), candidate(org, "Retrieval Grace")
    other = candidate(organizations[1], "Other tenant")
    ada_doc, ada_path = prepare(org, ada, long_pdf())
    grace_doc, _grace_path = prepare(org, grace, long_pdf())
    prepare(organizations[1], other, long_pdf())
    page = retrieve()
    if page["total"] != 2 or {item["candidate_id"] for item in page["items"]} != {
        ada,
        grace,
    }:
        raise SmokeFailure(
            "Candidate count included duplicate chunks or another tenant"
        )
    for item in page["items"]:
        document, source = sources[item["document_id"]]
        if (
            source[item["start_offset"] : item["end_offset"]] != item["text"]
            or item["chunk_sha256"] != hashlib.sha256(item["text"].encode()).hexdigest()
            or item["source_text_sha256"] != hashlib.sha256(source.encode()).hexdigest()
            or item["source_document_sha256"] != document["sha256"]
            or not math.isfinite(item["score"])
            or not 0 <= item["score"] <= 1
        ):
            raise SmokeFailure("Candidate evidence did not preserve source provenance")
    ada_score = next(
        item["score"] for item in page["items"] if item["candidate_id"] == ada
    )
    _ada_copy, copy_path = prepare(org, ada, equivalent_resume_pdf())
    repeated = retrieve()
    if (
        repeated["total"] != 2
        or len(repeated["items"]) != 2
        or next(
            item["score"] for item in repeated["items"] if item["candidate_id"] == ada
        )
        != ada_score
    ):
        raise SmokeFailure(
            "Repeated identical evidence inflated the candidate score or count"
        )
    first, second, beyond = (
        retrieve(limit=1),
        retrieve(limit=1, offset=1),
        retrieve(offset=1000),
    )
    if (
        first["total"] != 2
        or second["total"] != 2
        or first["items"][0]["candidate_id"] == second["items"][0]["candidate_id"]
        or beyond["items"] != []
        or beyond["total"] != 2
    ):
        raise SmokeFailure("Candidate pagination or empty-page count was incorrect")
    checked_request(
        "POST",
        f"/organizations/{org}/applications",
        token=owner,
        payload={"job_id": job, "candidate_id": ada},
        expected=201,
        step="retrieval applicant",
    )
    checked_request(
        "POST",
        f"/organizations/{org}/applications",
        token=owner,
        payload={"job_id": empty_job, "candidate_id": grace},
        expected=201,
        step="other job applicant",
    )
    applicants = retrieve(applicants_only="true")
    if applicants["total"] != 1 or applicants["items"][0]["candidate_id"] != ada:
        raise SmokeFailure("Applicant filter did not remain scoped to its job")
    for method, suffix in (
        ("PUT", "/search-profile"),
        ("GET", "/search-profile"),
        ("GET", "/candidate-retrieval"),
    ):
        kwargs = {"payload": {"q": "Python"}} if method == "PUT" else {}
        for token, expected, code in (
            (outsider, 404, "ORGANIZATION_NOT_FOUND"),
            (None, 401, "INVALID_ACCESS_TOKEN"),
        ):
            checked_request(
                method,
                base + suffix,
                token=token,
                expected=expected,
                error_code=code,
                step="retrieval authorization",
                **kwargs,
            )
    checked_request(
        "GET",
        f"/organizations/{organizations[1]}/jobs/{job}/candidate-retrieval",
        token=owner,
        expected=404,
        error_code="JOB_NOT_FOUND",
        step="cross-organization job hidden",
    )
    for params in ({"q": "override"}, {"limit": 51}, {"offset": -1}):
        checked_request(
            "GET",
            base + "/candidate-retrieval?" + urlencode(params),
            token=owner,
            expected=422,
            step="retrieval input validation",
        )
    private = checked_binary(
        "GET",
        base + "/candidate-retrieval",
        token=owner,
        content_type="application/json",
        expected=200,
        step="private candidate evidence",
    )
    if private.headers.get("cache-control") != "private, no-store":
        raise SmokeFailure("Candidate evidence response was cacheable")
    persian_doc, persian_path = upload(
        org, candidate(org, "Persian fixture"), sample_pdf()
    )
    source = "كَيَان مهندس\u200cنرم\u200cافزار"
    asyncio.run(seed_set(persian_doc, source, alternate=False))
    profile = put("کیان مهندس نرم افزار")
    persian = retrieve()
    if (
        profile["revision"] != 2
        or persian["profile_revision"] != 2
        or persian["q"] != profile["q"]
        or persian["items"][0]["text"] != source
    ):
        raise SmokeFailure(
            "Candidate retrieval lost its Persian source or profile revision"
        )
    for extraction in (False, True):
        try:
            asyncio.run(
                set_visibility(persian_doc["id"], visible=False, extraction=extraction)
            )
            if retrieve()["total"] != 0:
                raise SmokeFailure("Retrieval exposed deleting or incomplete source")
        finally:
            asyncio.run(
                set_visibility(persian_doc["id"], visible=True, extraction=extraction)
            )
    put("unmatchedword" + uuid4().hex)
    if retrieve()["total"] != 0:
        raise SmokeFailure("Unmatched job profile returned candidates")
    checked_request(
        "DELETE", persian_path, token=owner, expected=204, step="delete Persian fixture"
    )
    put("Python SQL")
    asyncio.run(seed_set(grace_doc, "No relevant keywords", alternate=True))
    if retrieve()["total"] != 1:
        raise SmokeFailure("Candidate retrieval used an older chunk version")
    asyncio.run(verify_deadline(org, ada_doc["uploaded_by_user_id"], job))
    checked_request(
        "DELETE",
        ada_path,
        token=owner,
        expected=204,
        step="delete first candidate resume",
    )
    if retrieve()["total"] != 1:
        raise SmokeFailure("Candidate with another matching resume disappeared")
    checked_request(
        "DELETE",
        copy_path,
        token=owner,
        expected=204,
        step="delete last matching resume",
    )
    if retrieve()["total"] != 0:
        raise SmokeFailure("Deleted evidence remained in candidate retrieval")
    log_ok(
        "candidate grouping best evidence profile revisions applicants pagination and isolation"
    )


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"retrieval-smoke-{suffix}", f"retrieval-other-{suffix}"]
    emails = [
        f"retrieval-owner-{suffix}@example.com",
        f"retrieval-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup_retrieval(slugs, emails))
    print(
        "[success] Job candidate retrieval Docker real-stack smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
