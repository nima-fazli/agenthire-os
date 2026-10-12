import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from scripts.application_smoke import checked_request, register_and_login, response_id
from scripts.candidate_document_smoke import (
    checked_binary,
    cleanup,
    connection,
    sample_pdf,
)
from scripts.docker_smoke import SmokeFailure, log_ok, request_json
from scripts.document_extraction_smoke import seed_lease, wait_for_result


def long_pdf() -> bytes:
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
            text = f"AgentHire source {page * 50 + row:04d} Python SQL PostgreSQL FastAPI tenant isolation"
            lines.append(f"({text}) Tj T*".encode())
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
    return (
        data
        + f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


async def counts(document_id: str, chunk_set_id: str) -> tuple[int, int]:
    database = await connection()
    try:
        return (
            await database.fetchval(
                "SELECT count(*) FROM document_chunk_sets WHERE document_id=$1",
                UUID(document_id),
            ),
            await database.fetchval(
                "SELECT count(*) FROM document_chunks WHERE chunk_set_id=$1",
                UUID(chunk_set_id),
            ),
        )
    finally:
        await database.close()


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="chunk owner")
    outsider = register_and_login(emails[1], label="chunk outsider")
    organizations = [
        response_id(
            checked_request(
                "POST",
                "/organizations",
                token=owner,
                payload={"name": "Chunk Smoke", "slug": slug},
                expected=201,
                step="chunk organization",
            ),
            step="organization",
        )
        for slug in slugs
    ]
    org = organizations[0]

    def upload(label: str, pdf: bytes) -> tuple[dict, str, str]:
        candidate = response_id(
            checked_request(
                "POST",
                f"/organizations/{org}/candidates",
                token=owner,
                payload={"full_name": label},
                expected=201,
                step=f"{label} candidate",
            ),
            step="candidate",
        )
        path = f"/organizations/{org}/candidates/{candidate}/documents"
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
        return document, path + f"/{document['id']}", candidate

    def extract(path: str, expected: str = "succeeded") -> None:
        checked_request(
            "POST",
            path + "/extraction",
            token=owner,
            payload={},
            expected=202,
            step="queue chunk source",
        )
        wait_for_result(path + "/extraction", owner, expected)

    document, path, candidate = upload("Long source", long_pdf())
    chunks_path = path + "/chunks"
    checked_request(
        "POST",
        chunks_path,
        token=owner,
        payload={},
        expected=404,
        error_code="EXTRACTION_NOT_FOUND",
        step="unextracted source cannot be chunked",
    )
    extract(path)
    source = checked_request(
        "GET", path + "/extraction/text", token=owner, step="chunk source text"
    ).body["text"]
    chunk_set = checked_request(
        "POST",
        chunks_path,
        token=owner,
        payload={},
        expected=201,
        step="atomic chunk generation",
    ).body
    digest = hashlib.sha256(source.encode()).hexdigest()
    if (
        chunk_set["source_text_sha256"] != digest
        or chunk_set["source_document_sha256"] != document["sha256"]
        or chunk_set["source_char_count"] != len(source)
        or chunk_set["chunk_count"] < 2
    ):
        raise SmokeFailure("Chunk source provenance was incorrect")
    cached = checked_request(
        "POST", chunks_path, token=owner, payload={}, step="cached chunk generation"
    ).body
    if cached["id"] != chunk_set["id"]:
        raise SmokeFailure("Repeated chunk generation changed the set ID")
    history = checked_request(
        "GET",
        chunks_path + "?limit=1&offset=0",
        token=owner,
        step="chunk version history",
    ).body
    if history["total"] != 1 or history["items"][0]["id"] != chunk_set["id"]:
        raise SmokeFailure("Chunk history was incorrect")
    set_path = chunks_path + f"/{chunk_set['id']}"
    checked_request("GET", set_path, token=owner, step="chunk metadata")
    all_chunks = []
    for offset in range(0, chunk_set["chunk_count"], 2):
        page = checked_request(
            "GET",
            set_path + f"/items?limit=2&offset={offset}",
            token=owner,
            step="private chunk pagination",
        ).body
        if page["total"] != chunk_set["chunk_count"]:
            raise SmokeFailure("Chunk pagination total changed")
        all_chunks.extend(page["items"])
    reconstructed = ""
    overlap = chunk_set["chunk_overlap_chars"]
    for position, chunk in enumerate(all_chunks):
        content = source[chunk["start_offset"] : chunk["end_offset"]]
        if (
            chunk["position"] != position
            or chunk["text"] != content
            or chunk["sha256"] != hashlib.sha256(content.encode()).hexdigest()
        ):
            raise SmokeFailure("Chunk offsets or checksum were incorrect")
        if (
            position
            and chunk["start_offset"]
            != all_chunks[position - 1]["end_offset"] - overlap
        ):
            raise SmokeFailure("Chunk coverage had a gap")
        reconstructed += content[overlap:] if position else content
    if reconstructed != source or len(all_chunks) != chunk_set["chunk_count"]:
        raise SmokeFailure("Chunk pages did not reconstruct the source")
    log_ok("exact source reconstruction and chunk checksums")
    for method, target in [
        ("POST", chunks_path),
        ("GET", chunks_path),
        ("GET", set_path),
        ("GET", set_path + "/items"),
    ]:
        checked_request(
            method,
            target,
            token=outsider,
            payload={} if method == "POST" else None,
            expected=404,
            error_code="ORGANIZATION_NOT_FOUND",
            step=f"chunk outsider {method}",
        )
    checked_request(
        "GET",
        set_path + "/items",
        expected=401,
        error_code="INVALID_ACCESS_TOKEN",
        step="chunk missing token",
    )
    checked_request(
        "GET",
        set_path.replace(org, organizations[1]),
        token=owner,
        expected=404,
        error_code="CANDIDATE_NOT_FOUND",
        step="chunk cross-organization isolation",
    )
    checked_request(
        "GET",
        chunks_path + f"/{uuid4()}",
        token=owner,
        expected=404,
        error_code="CHUNK_SET_NOT_FOUND",
        step="missing chunk set",
    )
    checked_request(
        "POST",
        chunks_path,
        token=owner,
        payload={"chunk_max_chars": 1},
        expected=422,
        step="server-owned chunk policy",
    )
    _, pending_path, _ = upload("Pending", sample_pdf())
    pending_document = checked_request(
        "GET", pending_path, token=owner, step="pending source metadata"
    ).body
    asyncio.run(seed_lease(pending_document, expired=False))
    checked_request(
        "POST",
        pending_path + "/chunks",
        token=owner,
        payload={},
        expected=409,
        error_code="EXTRACTION_NOT_READY",
        step="running source cannot be chunked",
    )
    _, invalid_path, _ = upload("Invalid source", b"%PDF-1.7\ninvalid\n%%EOF")
    extract(invalid_path, "failed")
    checked_request(
        "POST",
        invalid_path + "/chunks",
        token=owner,
        payload={},
        expected=409,
        error_code="EXTRACTION_FAILED",
        step="failed source cannot be chunked",
    )
    concurrent_doc, concurrent_path, other_candidate = upload(
        "Concurrent", sample_pdf()
    )
    extract(concurrent_path)
    barrier = Barrier(2)

    def enqueue(_):
        barrier.wait(timeout=10)
        return request_json(
            "POST", concurrent_path + "/chunks", token=owner, payload={}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(enqueue, range(2)))
    if sorted(response.status_code for response in responses) != [200, 201]:
        raise SmokeFailure(
            "Concurrent generation did not return one new and one cached set"
        )
    concurrent_set = responses[0].body
    if responses[1].body["id"] != concurrent_set["id"]:
        raise SmokeFailure("Concurrent generation created distinct sets")
    if asyncio.run(counts(concurrent_doc["id"], concurrent_set["id"])) != (
        1,
        concurrent_set["chunk_count"],
    ):
        raise SmokeFailure(
            "Concurrent generation persisted duplicate or partial chunks"
        )
    log_ok("concurrent generation is idempotent in PostgreSQL")
    checked_request(
        "GET",
        set_path.replace(candidate, other_candidate),
        token=owner,
        expected=404,
        error_code="DOCUMENT_NOT_FOUND",
        step="cross-candidate chunk isolation",
    )
    checked_request(
        "GET",
        chunks_path + f"/{concurrent_set['id']}/items",
        token=owner,
        expected=404,
        error_code="CHUNK_SET_NOT_FOUND",
        step="cross-document chunk set isolation",
    )
    checked_request(
        "DELETE", path, token=owner, expected=204, step="delete chunked document"
    )
    if asyncio.run(counts(document["id"], chunk_set["id"])) != (0, 0):
        raise SmokeFailure("Document deletion did not cascade to all chunks")
    checked_request(
        "GET",
        set_path + "/items",
        token=owner,
        expected=404,
        error_code="DOCUMENT_NOT_FOUND",
        step="deleted chunks hidden",
    )
    log_ok("document extraction chunk-set and chunk deletion cascade")

    race_document, race_path, _ = upload("Delete race", sample_pdf())
    extract(race_path)
    delete_barrier = Barrier(2)

    def change(method):
        delete_barrier.wait(timeout=10)
        return request_json(
            method,
            race_path + ("/chunks" if method == "POST" else ""),
            token=owner,
            payload={} if method == "POST" else None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        created, deleted = list(executor.map(change, ["POST", "DELETE"]))
    if deleted.status_code != 204 or created.status_code not in {201, 404}:
        raise SmokeFailure("Concurrent generation and document deletion failed")
    set_id = created.body["id"] if created.status_code == 201 else str(uuid4())
    if asyncio.run(counts(race_document["id"], set_id)) != (0, 0):
        raise SmokeFailure("Concurrent deletion left a chunk set behind")
    log_ok("concurrent generation and document deletion leave no chunks")


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"chunk-smoke-{suffix}", f"chunk-other-{suffix}"]
    emails = [
        f"chunk-owner-{suffix}@example.com",
        f"chunk-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup(slugs, emails))
    print("[success] Document chunk Docker real-stack smoke flow passed.", flush=True)


if __name__ == "__main__":
    main()
