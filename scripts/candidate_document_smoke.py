import asyncio
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import asyncpg

from app.core.config import get_settings
from app.core.document_storage import LocalDocumentStorage
from scripts.application_smoke import checked_request, register_and_login, response_id
from scripts.docker_smoke import API_BASE_URL, SmokeFailure, log_ok
from scripts.smoke_cleanup import cleanup_smoke_data


@dataclass(frozen=True)
class BinaryResponse:
    status: int
    body: bytes
    headers: dict[str, str]


def checked_binary(
    method: str,
    path: str,
    *,
    expected: int,
    step: str,
    token: str | None = None,
    data=None,
    content_type: str = "application/pdf",
    error_code: str | None = None,
) -> BinaryResponse:
    headers = {"Content-Type": content_type}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{API_BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        try:
            response = urlopen(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            result = BinaryResponse(
                response.status,
                response.read(),
                {name.lower(): value for name, value in response.headers.items()},
            )
    except URLError as error:
        raise SmokeFailure(f"{step}: API could not be reached") from error
    if result.status != expected:
        raise SmokeFailure(f"{step}: expected HTTP {expected}, got {result.status}")
    if (
        error_code is not None
        and json.loads(result.body)["error"]["code"] != error_code
    ):
        raise SmokeFailure(f"{step}: unexpected domain error")
    log_ok(step)
    return result


def sample_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 50 740 Td (Candidate document smoke) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream",
    ]
    data = b"%PDF-1.7\n"
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return (
        data
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


async def connection():
    return await asyncpg.connect(
        host=os.environ["AGENTHIRE_POSTGRES_HOST"],
        port=int(os.environ["AGENTHIRE_POSTGRES_PORT"]),
        database=os.environ["AGENTHIRE_POSTGRES_DB"],
        user=os.environ["AGENTHIRE_POSTGRES_USER"],
        password=os.environ["AGENTHIRE_POSTGRES_PASSWORD"],
    )


async def check_database_tenant_constraint(
    document: dict, other_organization_id: str
) -> None:
    database = await connection()
    try:
        try:
            async with database.transaction():
                await database.execute(
                    "INSERT INTO candidate_documents "
                    "(id, organization_id, candidate_id, uploaded_by_user_id, filename, "
                    "content_type, size_bytes, sha256, storage_key, status) "
                    "VALUES ($1, $2, $3, $4, 'invalid.pdf', 'application/pdf', 10, $5, $6, 'ready')",
                    uuid4(),
                    UUID(other_organization_id),
                    UUID(document["candidate_id"]),
                    UUID(document["uploaded_by_user_id"]),
                    "f" * 64,
                    uuid4().hex + ".pdf",
                )
                raise SmokeFailure(
                    "Database accepted a cross-tenant candidate reference"
                )
        except asyncpg.ForeignKeyViolationError:
            log_ok("PostgreSQL rejects cross-tenant document ownership")
    finally:
        await database.close()


async def cleanup(slugs: list[str], emails: list[str]) -> None:
    database = await connection()
    storage = LocalDocumentStorage(get_settings().document_storage_path)
    try:
        async with database.transaction():
            rows = await database.fetch(
                "SELECT storage_key FROM candidate_documents WHERE organization_id IN "
                "(SELECT id FROM organizations WHERE slug = ANY($1::text[]))",
                slugs,
            )
            for row in rows:
                await storage.delete(row["storage_key"])
            for table in ("candidate_documents", "candidates"):
                await database.execute(
                    f"DELETE FROM {table} WHERE organization_id IN "
                    "(SELECT id FROM organizations WHERE slug = ANY($1::text[]))",
                    slugs,
                )
    finally:
        await database.close()
    for slug in slugs:
        await cleanup_smoke_data(organization_slug=slug, user_emails=[])
    await cleanup_smoke_data(organization_slug=slugs[0], user_emails=emails)
    log_ok("document smoke metadata and file cleanup")


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="document owner")
    outsider = register_and_login(emails[1], label="document outsider")
    organizations = []
    for slug in slugs:
        created = checked_request(
            "POST",
            "/organizations",
            token=owner,
            expected=201,
            payload={"name": "Document Smoke", "slug": slug},
            step="document organization",
        )
        organizations.append(response_id(created, step="organization"))
    org = organizations[0]

    def candidate(label: str) -> str:
        created = checked_request(
            "POST",
            f"/organizations/{org}/candidates",
            token=owner,
            payload={"full_name": label},
            expected=201,
            step=f"{label} candidate",
        )
        return f"/organizations/{org}/candidates/{response_id(created, step=label)}/documents"

    path = candidate("Document")
    pdf = sample_pdf()
    upload_path = path + "?filename=resume.pdf"
    uploaded = checked_binary(
        "POST", upload_path, token=owner, data=pdf, expected=201, step="PDF upload"
    )
    document = json.loads(uploaded.body)
    if (
        "storage_key" in document
        or document["sha256"] != hashlib.sha256(pdf).hexdigest()
    ):
        raise SmokeFailure("Upload metadata was incorrect or exposed the storage key")
    document_path = f"{path}/{document['id']}"
    checked_request("GET", document_path, token=owner, step="document metadata")
    listed = checked_request(
        "GET", path + "?limit=1&offset=0", token=owner, step="document pagination"
    )
    if len(listed.body) != 1:
        raise SmokeFailure("Document list was incorrect")
    downloaded = checked_binary(
        "GET",
        document_path + "/content",
        token=owner,
        expected=200,
        step="private PDF download",
    )
    if (
        downloaded.body != pdf
        or downloaded.headers.get("x-content-type-options") != "nosniff"
    ):
        raise SmokeFailure("Downloaded bytes or attachment headers were incorrect")
    checked_binary(
        "POST",
        upload_path,
        token=owner,
        data=pdf,
        expected=409,
        error_code="DOCUMENT_ALREADY_EXISTS",
        step="duplicate PDF rejection",
    )
    checked_binary(
        "POST",
        upload_path,
        token=owner,
        data=b"not a PDF",
        expected=422,
        error_code="INVALID_PDF",
        step="invalid PDF rejection",
    )
    checked_binary(
        "POST",
        upload_path,
        token=owner,
        data=pdf,
        content_type="text/html",
        expected=415,
        error_code="UNSUPPORTED_DOCUMENT_TYPE",
        step="unsupported media rejection",
    )
    oversized = iter(
        [b"%PDF-1.7\n", b"x" * get_settings().document_max_bytes, b"\n%%EOF"]
    )
    checked_binary(
        "POST",
        upload_path,
        token=owner,
        data=oversized,
        expected=413,
        error_code="DOCUMENT_TOO_LARGE",
        step="chunked upload size limit",
    )
    for method, target, data in [
        ("POST", upload_path, pdf),
        ("GET", path, None),
        ("GET", document_path, None),
        ("GET", document_path + "/content", None),
        ("DELETE", document_path, None),
    ]:
        checked_binary(
            method,
            target,
            token=outsider,
            data=data,
            expected=404,
            error_code="ORGANIZATION_NOT_FOUND",
            step=f"document outsider {method}",
        )
    checked_binary(
        "GET",
        document_path + "/content",
        expected=401,
        error_code="INVALID_ACCESS_TOKEN",
        step="document missing bearer token",
    )
    wrong_org = document_path.replace(org, organizations[1])
    checked_request(
        "GET",
        wrong_org,
        token=owner,
        expected=404,
        error_code="CANDIDATE_NOT_FOUND",
        step="member cross-organization candidate isolation",
    )
    other_path = candidate("Other")
    checked_request(
        "GET",
        other_path + f"/{document['id']}",
        token=owner,
        expected=404,
        error_code="DOCUMENT_NOT_FOUND",
        step="cross-candidate document isolation",
    )
    checked_binary(
        "POST",
        other_path + "?filename=resume.pdf",
        token=owner,
        data=pdf,
        expected=201,
        step="same bytes allowed for another candidate",
    )
    asyncio.run(check_database_tenant_constraint(document, organizations[1]))
    concurrent_path = candidate("Concurrent")
    barrier = Barrier(2)

    def concurrent_upload(_):
        barrier.wait(timeout=10)
        request = Request(
            f"{API_BASE_URL}{concurrent_path}?filename=resume.pdf",
            data=pdf,
            headers={
                "Content-Type": "application/pdf",
                "Authorization": f"Bearer {owner}",
            },
            method="POST",
        )
        try:
            response = urlopen(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            response.read()
            return response.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(concurrent_upload, range(2)))
    if statuses != [201, 409]:
        raise SmokeFailure(
            f"Concurrent upload returned {statuses}, expected [201, 409]"
        )
    concurrent = checked_request(
        "GET", concurrent_path, token=owner, step="concurrent upload result"
    )
    if len(concurrent.body) != 1:
        raise SmokeFailure("Concurrent upload did not leave exactly one document")
    checked_request(
        "DELETE", document_path, token=owner, expected=204, step="PDF deletion"
    )
    checked_request(
        "DELETE", document_path, token=owner, expected=204, step="repeat PDF deletion"
    )
    checked_request(
        "GET",
        document_path,
        token=owner,
        expected=404,
        error_code="DOCUMENT_NOT_FOUND",
        step="deleted document hidden",
    )
    checked_binary(
        "POST",
        upload_path,
        token=owner,
        data=pdf,
        expected=201,
        step="reupload after deletion",
    )


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"document-smoke-{suffix}", f"document-smoke-other-{suffix}"]
    emails = [
        f"document-owner-{suffix}@example.com",
        f"document-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup(slugs, emails))
    print(
        "[success] Candidate document Docker real-stack smoke flow passed.", flush=True
    )


if __name__ == "__main__":
    main()
