import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import build_database_url
from app.repositories.job_matching import JobMatchingRepository
from app.services.job_matching import JobMatchingService
from scripts.application_smoke import checked_request, register_and_login
from scripts.candidate_document_smoke import checked_binary, connection, sample_pdf
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.document_extraction_smoke import wait_for_result
from scripts.document_search_smoke import seed_set, set_visibility
from scripts.job_retrieval_smoke import cleanup_retrieval


def split_skills_pdf(*, duplicate: bool = False) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R 6 0 R 8 0 R] /Count 3 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page in range(3):
        contents = 5 + page * 2
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            + f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents} 0 R >>".encode()
        )
        lines = [b"BT /F1 9 Tf 12 TL 40 750 Td"]
        for row in range(50):
            number = page * 50 + row
            value = (
                "Python"
                if number == 0
                else "SQL"
                if number == 149
                else f"Neutral record {number:04d} teamwork delivery communication documentation stability"
            )
            lines.append(f"({value}) Tj T*".encode())
        stream = b"\n".join(lines) + b"\nET\n"
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream"
        )
    data = b"%PDF-1.7\n"
    offsets = []
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(data)
    count = len(objects) + 1
    data += f"xref\n0 {count}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    data += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return data + b"\n" if duplicate else data


def criterion(key: str, q: str, importance: str = "required") -> dict:
    return {"key": key, "label": key, "q": q, "importance": importance}


async def verify_deadline(scope: dict) -> None:
    engine = create_async_engine(
        build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True
    )

    class SlowRepository(JobMatchingRepository):
        @staticmethod
        def evidence_statement(**_):
            return select(func.pg_sleep(1))

    try:
        async with engine.connect() as database:
            original = (
                await database.execute(text("SHOW statement_timeout"))
            ).scalar_one()
            await database.rollback()
            async with AsyncSession(bind=database, expire_on_commit=False) as session:
                service = JobMatchingService(
                    session,
                    get_settings().model_copy(
                        update={"document_search_timeout_ms": 100}
                    ),
                )
                service._repository = SlowRepository(session)
                try:
                    await service.evidence(
                        **{key: UUID(value) for key, value in scope.items()}
                    )
                except AppError as error:
                    if (
                        error.code != "MATCH_EVIDENCE_TIMEOUT"
                        or error.status_code != 503
                    ):
                        raise SmokeFailure(
                            "Unexpected match evidence cancellation"
                        ) from error
                else:
                    raise SmokeFailure("Slow evidence query was not cancelled")
                if (await session.execute(text("SELECT 1"))).scalar_one() != 1:
                    raise SmokeFailure("Cancelled match evidence did not roll back")
                await session.rollback()
            if (
                await database.execute(text("SHOW statement_timeout"))
            ).scalar_one() != original:
                raise SmokeFailure("Evidence timeout leaked beyond its transaction")
        log_ok("real matching evidence deadline rollback and timeout reset")
    finally:
        await engine.dispose()


async def verify_cascade(organization: str, job: str) -> None:
    database = await connection()
    try:
        await database.execute(
            "DELETE FROM jobs WHERE id=$1 AND organization_id=$2",
            UUID(job),
            UUID(organization),
        )
        for table in ("job_match_profiles", "job_match_criteria"):
            if await database.fetchval(
                f"SELECT count(*) FROM {table} WHERE job_id=$1", UUID(job)
            ):
                raise SmokeFailure(
                    "Job deletion did not cascade through match criteria"
                )
        log_ok("PostgreSQL job profile and criterion deletion cascade")
    finally:
        await database.close()


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="matching owner")
    outsider = register_and_login(emails[1], label="matching outsider")

    def api(method, path, **kwargs):
        return checked_request(
            method,
            path,
            token=kwargs.pop("token", owner),
            step=kwargs.pop("step", "matching evidence"),
            **kwargs,
        ).body

    organizations = [
        api(
            "POST",
            "/organizations",
            payload={"name": "Matching Smoke", "slug": slug},
            expected=201,
        )["id"]
        for slug in slugs
    ]
    org = organizations[0]

    def job(organization):
        return api(
            "POST",
            f"/organizations/{organization}/jobs",
            payload={
                "title": "Engineer",
                "description": "Python SQL",
                "status": "open",
            },
            expected=201,
        )["id"]

    def candidate(organization, name):
        return api(
            "POST",
            f"/organizations/{organization}/candidates",
            payload={"full_name": name},
            expected=201,
        )["id"]

    job_id, temporary_job = job(org), job(org)
    subject, empty, other = (
        candidate(org, "Split skills"),
        candidate(org, "No documents"),
        candidate(organizations[1], "Other tenant"),
    )
    base = f"/organizations/{org}/jobs/{job_id}"

    def path(candidate_id):
        return base + f"/candidates/{candidate_id}/match-evidence"

    def evidence(candidate_id=subject):
        return api("GET", path(candidate_id))

    def put(criteria):
        return api("PUT", base + "/match-profile", payload={"criteria": criteria})

    criteria = [
        criterion("python", "Python"),
        criterion("sql", "SQL"),
        criterion("go", "Go", "preferred"),
        criterion("together", "Python SQL", "preferred"),
    ]
    api(
        "GET",
        base + "/match-profile",
        expected=404,
        error_code="JOB_MATCH_PROFILE_NOT_FOUND",
    )
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=10)
        return put(criteria)

    with ThreadPoolExecutor(max_workers=2) as executor:
        profiles = list(executor.map(create, range(2)))
    if (
        profiles[0] != profiles[1]
        or profiles[0]["revision"] != 1
        or put(criteria) != profiles[0]
    ):
        raise SmokeFailure(
            "Concurrent match profile creation or retry was not idempotent"
        )
    if evidence(empty)["summary"]["source_status"] != "no_documents":
        raise SmokeFailure("Candidate without documents borrowed another source")

    def upload(organization, candidate_id, data):
        parent = f"/organizations/{organization}/candidates/{candidate_id}/documents"
        result = json.loads(
            checked_binary(
                "POST",
                parent + "?filename=resume.pdf",
                token=owner,
                data=data,
                expected=201,
                step="matching resume upload",
            ).body
        )
        return result, parent + "/" + result["id"]

    def index(document_path):
        api("POST", document_path + "/extraction", payload={}, expected=202)
        wait_for_result(document_path + "/extraction", owner, "succeeded")
        source = api("GET", document_path + "/extraction/text")["text"]
        chunk_set = api("POST", document_path + "/chunks", payload={}, expected=201)
        return source, chunk_set

    document, document_path = upload(org, subject, split_skills_pdf())
    if evidence()["summary"]["source_status"] != "not_indexed":
        raise SmokeFailure("Unextracted source was treated as evidence")
    source, _chunk_set = index(document_path)
    if source.index("SQL") - source.index("Python") <= 4000:
        raise SmokeFailure("Independent-skill fixture did not separate its terms")
    sources = {document["id"]: (document, source)}
    upload(organizations[1], other, split_skills_pdf())
    api("PUT", base + "/search-profile", payload={"q": "Python SQL"})
    if api("GET", base + "/candidate-retrieval")["total"] != 0:
        raise SmokeFailure("Combined query unexpectedly matched the split terms")
    report = evidence()

    def verify_report(value):
        if (
            value["summary"]["required_with_evidence"] != 2
            or value["summary"]["preferred_with_evidence"] != 0
        ):
            raise SmokeFailure("Independent criterion evidence counts were incorrect")
        for item in value["criteria"]:
            hit = item["evidence"]
            if hit is None:
                continue
            file, text_value = sources[hit["document_id"]]
            if (
                text_value[hit["start_offset"] : hit["end_offset"]] != hit["text"]
                or hit["chunk_sha256"]
                != hashlib.sha256(hit["text"].encode()).hexdigest()
                or hit["source_text_sha256"]
                != hashlib.sha256(text_value.encode()).hexdigest()
                or hit["source_document_sha256"] != file["sha256"]
            ):
                raise SmokeFailure("Criterion witness lost original source provenance")

    verify_report(report)
    if (
        report["criteria"][0]["evidence"]["chunk_position"]
        == report["criteria"][1]["evidence"]["chunk_position"]
    ):
        raise SmokeFailure("Split terms did not use independent chunk witnesses")
    duplicate, duplicate_path = upload(org, subject, split_skills_pdf(duplicate=True))
    if evidence()["summary"]["source_status"] != "partial":
        raise SmokeFailure("Partially indexed documents were not reported")
    duplicate_source, _ = index(duplicate_path)
    if duplicate_source != source:
        raise SmokeFailure("Duplicate fixture changed its extracted source")
    sources[duplicate["id"]] = (duplicate, duplicate_source)
    verify_report(evidence())
    if evidence()["summary"]["indexed_documents"] != 2:
        raise SmokeFailure("Indexed document count was incorrect")
    for extraction in (False, True):
        try:
            asyncio.run(
                set_visibility(document["id"], visible=False, extraction=extraction)
            )
            hidden = evidence()
            if any(
                item["evidence"] and item["evidence"]["document_id"] == document["id"]
                for item in hidden["criteria"]
            ):
                raise SmokeFailure("Deleting or incomplete source remained visible")
        finally:
            asyncio.run(
                set_visibility(document["id"], visible=True, extraction=extraction)
            )
    for method, target in (
        ("PUT", base + "/match-profile"),
        ("GET", base + "/match-profile"),
        ("GET", path(subject)),
    ):
        kwargs = {"payload": {"criteria": criteria}} if method == "PUT" else {}
        for token, expected, code in (
            (outsider, 404, "ORGANIZATION_NOT_FOUND"),
            (None, 401, "INVALID_ACCESS_TOKEN"),
        ):
            api(
                method,
                target,
                token=token,
                expected=expected,
                error_code=code,
                **kwargs,
            )
    api("GET", path(other), expected=404, error_code="CANDIDATE_NOT_FOUND")
    api(
        "GET",
        f"/organizations/{organizations[1]}/jobs/{job_id}/match-profile",
        expected=404,
        error_code="JOB_NOT_FOUND",
    )
    api("GET", path(subject) + "?q=override", expected=422)
    api(
        "PUT",
        base + "/match-profile",
        payload={"criteria": [criteria[0], criteria[0]]},
        expected=422,
    )
    private = checked_binary(
        "GET",
        path(subject),
        token=owner,
        content_type="application/json",
        expected=200,
        step="private matching evidence",
    )
    if private.headers.get("cache-control") != "private, no-store":
        raise SmokeFailure("Matching evidence was cacheable")
    latest = asyncio.run(seed_set(document, "Python", alternate=True))
    sources[document["id"]] = (document, "Python")
    api("DELETE", duplicate_path, expected=204)
    changed = evidence()
    if (
        changed["summary"]["required_with_evidence"] != 1
        or changed["criteria"][0]["evidence"]["chunk_set_id"] != str(latest)
        or changed["criteria"][1]["evidence"] is not None
    ):
        raise SmokeFailure("Evidence used an older set or a deleted source")
    persian_document, _persian_path = upload(org, empty, sample_pdf())
    persian_source = "كَيَان مهندس\u200cنرم\u200cافزار"
    asyncio.run(seed_set(persian_document, persian_source, alternate=False))
    updated = put([criterion("persian", "کیان مهندس نرم افزار")])
    persian = evidence(empty)
    if (
        updated["revision"] != 2
        or persian["profile_revision"] != 2
        or persian["criteria"][0]["evidence"]["text"] != persian_source
    ):
        raise SmokeFailure(
            "Persian criterion normalization or profile revision was incorrect"
        )
    definitions = [criterion("python", "Python")], [criterion("sql", "SQL")]
    barrier = Barrier(3)

    def update_profile(index):
        barrier.wait(timeout=10)
        return put(definitions[index])

    def read_snapshot():
        barrier.wait(timeout=10)
        return evidence()

    with ThreadPoolExecutor(max_workers=3) as executor:
        writes = [executor.submit(update_profile, index) for index in range(2)]
        reading = executor.submit(read_snapshot)
        profiles = [future.result() for future in writes]
        snapshot = reading.result()
    versions = {2: "کیان مهندس نرم افزار"} | {
        value["revision"]: value["criteria"][0]["q"] for value in profiles
    }
    if (
        sorted(value["revision"] for value in profiles) != [3, 4]
        or len(snapshot["criteria"]) != 1
        or snapshot["criteria"][0]["q"] != versions[snapshot["profile_revision"]]
    ):
        raise SmokeFailure("Concurrent profile replacement produced a mixed snapshot")
    asyncio.run(
        verify_deadline(
            {
                "organization_id": org,
                "user_id": document["uploaded_by_user_id"],
                "job_id": job_id,
                "candidate_id": subject,
            }
        )
    )
    api("DELETE", document_path, expected=204)
    deleted = evidence()
    if deleted["summary"]["source_status"] != "no_documents" or any(
        item["evidence"] for item in deleted["criteria"]
    ):
        raise SmokeFailure("Deleted source evidence was resurrected")
    api(
        "PUT",
        f"/organizations/{org}/jobs/{temporary_job}/match-profile",
        payload={"criteria": [criterion("temporary", "Python")]},
    )
    asyncio.run(verify_cascade(org, temporary_job))
    log_ok(
        "independent criteria provenance source readiness atomic revisions isolation and deletion"
    )


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"matching-smoke-{suffix}", f"matching-other-{suffix}"]
    emails = [
        f"matching-owner-{suffix}@example.com",
        f"matching-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup_retrieval(slugs, emails))
    print(
        "[success] Job matching evidence Docker real-stack smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
