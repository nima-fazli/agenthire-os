import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.pdf_extraction import ExtractedPdf
from app.db.session import build_database_url
from app.repositories.document_extraction import (
    DocumentExtractionRepository,
    ExtractionTask,
)
from scripts.application_smoke import checked_request, register_and_login, response_id
from scripts.candidate_document_smoke import (
    checked_binary,
    cleanup,
    connection,
    sample_pdf,
)
from scripts.docker_smoke import SmokeFailure, expect_status, log_ok, request_json


def wait_for_result(path: str, token: str, expected: str) -> dict:
    deadline = time.monotonic() + max(
        60, get_settings().extraction_timeout_seconds + 30
    )
    while time.monotonic() < deadline:
        response = request_json("GET", path, token=token)
        expect_status(response, 200, step="extraction polling")
        state = response.body["status"]
        if state in {"succeeded", "failed"}:
            if state != expected:
                raise SmokeFailure(
                    f"Extraction ended as {state}: {response.body.get('failure_code')}"
                )
            log_ok(f"extraction {expected}")
            return response.body
        time.sleep(0.2)
    raise SmokeFailure("Extraction did not finish before the smoke deadline")


async def seed_lease(document: dict, *, expired: bool) -> ExtractionTask:
    database = await connection()
    try:
        row = await database.fetchrow(
            "SELECT storage_key, size_bytes, sha256 FROM candidate_documents WHERE id=$1",
            UUID(document["id"]),
        )
        token = uuid4()
        offset = -60 if expired else 300
        await database.execute(
            "INSERT INTO document_extractions (document_id, status, attempts, lease_token, lease_expires_at) "
            "VALUES ($1, 'running', 1, $2, clock_timestamp() + ($3 * interval '1 second'))",
            UUID(document["id"]),
            token,
            offset,
        )
        return ExtractionTask(
            UUID(document["id"]),
            row["storage_key"],
            row["size_bytes"],
            row["sha256"],
            token,
        )
    finally:
        await database.close()


async def finish(task: ExtractionTask) -> bool:
    engine = create_async_engine(
        build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True
    )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            accepted = await DocumentExtractionRepository(session).finish_if_owned(
                task, result=ExtractedPdf("stale result", 1)
            )
            await session.commit()
            return accepted
    finally:
        await engine.dispose()


async def job_count(document_id: str) -> int:
    database = await connection()
    try:
        return await database.fetchval(
            "SELECT count(*) FROM document_extractions WHERE document_id=$1",
            UUID(document_id),
        )
    finally:
        await database.close()


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="extraction owner")
    outsider = register_and_login(emails[1], label="extraction outsider")
    organizations = [
        response_id(
            checked_request(
                "POST",
                "/organizations",
                token=owner,
                payload={"name": "Extraction Smoke", "slug": slug},
                expected=201,
                step="extraction organization",
            ),
            step="organization",
        )
        for slug in slugs
    ]
    org = organizations[0]

    def upload(label: str, pdf: bytes) -> tuple[dict, str]:
        candidate = checked_request(
            "POST",
            f"/organizations/{org}/candidates",
            token=owner,
            payload={"full_name": label},
            expected=201,
            step=f"{label} candidate",
        )
        path = f"/organizations/{org}/candidates/{response_id(candidate, step=label)}/documents"
        document = json.loads(
            checked_binary(
                "POST",
                path + "?filename=resume.pdf",
                token=owner,
                data=pdf,
                expected=201,
                step=f"{label} PDF",
            ).body
        )
        return document, path + f"/{document['id']}"

    _document, path = upload("Text", sample_pdf())
    extraction = path + "/extraction"
    checked_request(
        "GET",
        extraction,
        token=owner,
        expected=404,
        error_code="EXTRACTION_NOT_FOUND",
        step="unrequested extraction",
    )
    checked_request(
        "POST",
        extraction,
        token=owner,
        payload={},
        expected=202,
        step="queue PDF extraction",
    )
    completed = wait_for_result(extraction, owner, "succeeded")
    if (
        completed["attempts"] != 1
        or completed["page_count"] != 1
        or "lease_token" in completed
    ):
        raise SmokeFailure("Extraction metadata was incorrect")
    text = checked_request(
        "GET", extraction + "/text", token=owner, step="private extracted text"
    )
    if "Candidate document smoke" not in text.body["text"]:
        raise SmokeFailure("Expected PDF text was missing")
    checked_request(
        "POST", extraction, token=owner, payload={}, step="cached extraction"
    )
    for method, target in [
        ("POST", extraction),
        ("GET", extraction),
        ("GET", extraction + "/text"),
    ]:
        checked_request(
            method,
            target,
            token=outsider,
            payload={} if method == "POST" else None,
            expected=404,
            error_code="ORGANIZATION_NOT_FOUND",
            step=f"extraction outsider {method}",
        )
    checked_request(
        "GET",
        extraction + "/text",
        expected=401,
        error_code="INVALID_ACCESS_TOKEN",
        step="extraction missing token",
    )
    checked_request(
        "GET",
        extraction.replace(org, organizations[1]),
        token=owner,
        expected=404,
        error_code="CANDIDATE_NOT_FOUND",
        step="cross-organization extraction isolation",
    )
    _invalid, invalid_path = upload("Invalid", b"%PDF-1.7\ninvalid\n%%EOF")
    invalid_extraction = invalid_path + "/extraction"
    checked_request(
        "POST",
        invalid_extraction,
        token=owner,
        payload={},
        expected=202,
        step="queue malformed PDF",
    )
    result = wait_for_result(invalid_extraction, owner, "failed")
    if result["failure_code"] != "PDF_INVALID":
        raise SmokeFailure("Malformed PDF did not return a safe failure code")
    checked_request(
        "GET",
        invalid_extraction + "/text",
        token=owner,
        expected=409,
        error_code="EXTRACTION_FAILED",
        step="failed extraction hides text",
    )
    for attempt in range(2, get_settings().extraction_max_attempts + 1):
        checked_request(
            "POST",
            invalid_extraction,
            token=owner,
            payload={"retry": True},
            expected=202,
            step="explicit extraction retry",
        )
        if wait_for_result(invalid_extraction, owner, "failed")["attempts"] != attempt:
            raise SmokeFailure("Extraction retry attempt count was incorrect")
    checked_request(
        "POST",
        invalid_extraction,
        token=owner,
        payload={"retry": True},
        expected=409,
        error_code="EXTRACTION_RETRY_LIMIT",
        step="bounded extraction retries",
    )
    _, blank_path = upload(
        "Blank", sample_pdf().replace(b"Candidate document smoke", b" " * 24)
    )
    checked_request(
        "POST",
        blank_path + "/extraction",
        token=owner,
        payload={},
        expected=202,
        step="queue PDF without text",
    )
    if (
        wait_for_result(blank_path + "/extraction", owner, "failed")["failure_code"]
        != "PDF_NO_TEXT"
    ):
        raise SmokeFailure("PDF without a text layer was not identified")
    concurrent_doc, concurrent_path = upload("Concurrent", sample_pdf())
    barrier = Barrier(2)

    def enqueue(_):
        barrier.wait(timeout=10)
        return request_json(
            "POST", concurrent_path + "/extraction", token=owner, payload={}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(enqueue, range(2)))
    if any(response.status_code not in {200, 202} for response in responses):
        raise SmokeFailure("Concurrent extraction request failed")
    wait_for_result(concurrent_path + "/extraction", owner, "succeeded")
    if asyncio.run(job_count(concurrent_doc["id"])) != 1:
        raise SmokeFailure("Concurrent requests created duplicate extraction jobs")
    recovery_doc, recovery_path = upload("Recovery", sample_pdf())
    old_task = asyncio.run(seed_lease(recovery_doc, expired=True))
    expected = "succeeded" if get_settings().extraction_max_attempts > 1 else "failed"
    wait_for_result(recovery_path + "/extraction", owner, expected)
    if asyncio.run(finish(old_task)):
        raise SmokeFailure("Expired worker result was accepted")
    log_ok("expired lease recovery and stale result rejection")
    fenced_doc, fenced_path = upload("Fencing", sample_pdf())
    active = asyncio.run(seed_lease(fenced_doc, expired=False))
    stale = ExtractionTask(
        active.document_id,
        active.storage_key,
        active.size_bytes,
        active.sha256,
        uuid4(),
    )
    if asyncio.run(finish(stale)):
        raise SmokeFailure("Wrong lease token was accepted")
    checked_request(
        "DELETE",
        fenced_path,
        token=owner,
        expected=204,
        step="delete running extraction document",
    )
    if asyncio.run(finish(active)) or asyncio.run(job_count(fenced_doc["id"])) != 0:
        raise SmokeFailure("Deleted extraction was resurrected")
    log_ok("lease fencing and cascading extraction deletion")


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"extraction-smoke-{suffix}", f"extraction-other-{suffix}"]
    emails = [
        f"extraction-owner-{suffix}@example.com",
        f"extraction-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup(slugs, emails))
    print(
        "[success] Document extraction Docker real-stack smoke flow passed.", flush=True
    )


if __name__ == "__main__":
    main()
