import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.text_chunking import CHUNKER_VERSION, chunk_text, text_digest
from app.core.text_search import LATEST_SET_INDEX, SEARCH_INDEX
from app.db.session import build_database_url
from app.repositories.document_search import DocumentSearchRepository
from app.schemas.document_search import DocumentSearchQuery
from app.services.document_search import DocumentSearchService
from scripts.application_smoke import checked_request, register_and_login, response_id
from scripts.candidate_document_smoke import (
    checked_binary,
    cleanup,
    connection,
    sample_pdf,
)
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.document_extraction_smoke import wait_for_result


async def verify_indexes() -> None:
    database = await connection()
    try:
        rows = await database.fetch(
            "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY($1::text[])",
            [SEARCH_INDEX, LATEST_SET_INDEX],
        )
        if {row["relname"] for row in rows if row["indisvalid"]} != {
            SEARCH_INDEX,
            LATEST_SET_INDEX,
        }:
            raise SmokeFailure("Search indexes are missing or invalid")
        async with database.transaction():
            await database.execute("SET LOCAL enable_seqscan=off")
            plan = await database.fetchval(
                "EXPLAIN (FORMAT JSON) SELECT chunk_set_id FROM document_chunks "
                "WHERE to_tsvector('simple'::regconfig, agenthire_search_text_v1(text)) "
                "@@ plainto_tsquery('simple'::regconfig, agenthire_search_text_v1($1))",
                "candidate",
            )
            if SEARCH_INDEX not in plan:
                raise SmokeFailure("Search expression cannot use its GIN index")
        values = await database.fetchrow(
            "SELECT agenthire_search_text_v1($1) AS persian, agenthire_search_text_v1($2) AS latin",
            "كَيَان\u200cنرم\u200cافزار",
            "ＣＡＦÉ",
        )
        if values["persian"] != "کیان نرم افزار" or values["latin"] != "café":
            raise SmokeFailure("Unicode search normalization was incorrect")
        log_ok("valid GIN/latest indexes and frozen Unicode normalization")
    finally:
        await database.close()


async def seed_set(document: dict, source: str, *, alternate: bool) -> UUID:
    settings = get_settings()
    size = (
        (1500 if settings.chunk_max_chars != 1500 else 1200)
        if alternate
        else settings.chunk_max_chars
    )
    chunks = chunk_text(
        source,
        max_chars=size,
        overlap_chars=settings.chunk_overlap_chars,
        max_count=settings.chunk_max_count,
    )
    chunk_set_id = uuid4()
    database = await connection()
    try:
        async with database.transaction():
            await database.execute(
                "INSERT INTO document_extractions (document_id,status,attempts,text,page_count,completed_at) "
                "VALUES ($1,'succeeded',1,$2,1,clock_timestamp()) ON CONFLICT (document_id) DO NOTHING",
                UUID(document["id"]),
                source,
            )
            await database.execute(
                "INSERT INTO document_chunk_sets (id,document_id,source_document_sha256,source_text_sha256,"
                "source_char_count,page_count,chunker_version,chunk_max_chars,chunk_overlap_chars,chunk_count,created_at) "
                "VALUES ($1,$2,$3,$4,$5,1,$6,$7,$8,$9,clock_timestamp()+interval '1 second')",
                chunk_set_id,
                UUID(document["id"]),
                document["sha256"],
                text_digest(source),
                len(source),
                CHUNKER_VERSION,
                size,
                settings.chunk_overlap_chars,
                len(chunks),
            )
            await database.executemany(
                "INSERT INTO document_chunks (chunk_set_id,position,start_offset,end_offset,text,sha256) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                [
                    (
                        chunk_set_id,
                        chunk.position,
                        chunk.start_offset,
                        chunk.end_offset,
                        chunk.text,
                        chunk.sha256,
                    )
                    for chunk in chunks
                ],
            )
        return chunk_set_id
    finally:
        await database.close()


async def set_visibility(document_id: str, *, visible: bool, extraction: bool) -> None:
    database = await connection()
    try:
        if extraction:
            await database.execute(
                "UPDATE document_extractions SET status=$2,lease_token=$3,lease_expires_at=$4 WHERE document_id=$1",
                UUID(document_id),
                "succeeded" if visible else "running",
                None if visible else uuid4(),
                None if visible else datetime.now(UTC) + timedelta(minutes=5),
            )
        else:
            await database.execute(
                "UPDATE candidate_documents SET status=$2 WHERE id=$1",
                UUID(document_id),
                "ready" if visible else "deleting",
            )
    finally:
        await database.close()


async def verify_deadline(organization_id: str, user_id: str) -> None:
    engine = create_async_engine(
        build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True
    )

    class SlowRepository(DocumentSearchRepository):
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
                await DocumentSearchRepository(session).search(
                    organization_id=UUID(organization_id),
                    user_id=UUID(user_id),
                    data=DocumentSearchQuery(q="candidate"),
                    timeout_ms=1500,
                )
                milliseconds = (
                    await session.execute(
                        text(
                            "SELECT EXTRACT(EPOCH FROM current_setting('statement_timeout')::interval) * 1000"
                        )
                    )
                ).scalar_one()
                if milliseconds != 1500:
                    raise SmokeFailure("Search execution limit was not configured")
                await session.rollback()
                service = DocumentSearchService(
                    session,
                    get_settings().model_copy(
                        update={"document_search_timeout_ms": 100}
                    ),
                )
                service._repository = SlowRepository(session)
                try:
                    await service.search_for_user(
                        DocumentSearchQuery(q="candidate"),
                        organization_id=UUID(organization_id),
                        user_id=UUID(user_id),
                    )
                except AppError as error:
                    if (
                        error.code != "DOCUMENT_SEARCH_TIMEOUT"
                        or error.status_code != 503
                    ):
                        raise SmokeFailure(
                            "Search cancellation returned an unexpected error"
                        ) from error
                else:
                    raise SmokeFailure("Slow search was not cancelled")
                if (await session.execute(text("SELECT 1"))).scalar_one() != 1:
                    raise SmokeFailure(
                        "Cancelled search did not roll back its transaction"
                    )
                await session.rollback()
            restored = (
                await database.execute(text("SHOW statement_timeout"))
            ).scalar_one()
            if restored != original:
                raise SmokeFailure("Search timeout leaked beyond its transaction")
        log_ok("real PostgreSQL search cancellation rollback and timeout reset")
    finally:
        await engine.dispose()


def run(slugs: list[str], emails: list[str]) -> None:
    owner = register_and_login(emails[0], label="search owner")
    outsider = register_and_login(emails[1], label="search outsider")
    organizations = [
        response_id(
            checked_request(
                "POST",
                "/organizations",
                token=owner,
                payload={"name": "Search Smoke", "slug": slug},
                expected=201,
                step="search organization",
            ),
            step="organization",
        )
        for slug in slugs
    ]
    org = organizations[0]

    def upload(organization: str, label: str):
        candidate = response_id(
            checked_request(
                "POST",
                f"/organizations/{organization}/candidates",
                token=owner,
                payload={"full_name": label},
                expected=201,
                step=f"{label} candidate",
            ),
            step="candidate",
        )
        base = f"/organizations/{organization}/candidates/{candidate}/documents"
        document = json.loads(
            checked_binary(
                "POST",
                base + "?filename=resume.pdf",
                token=owner,
                data=sample_pdf(),
                expected=201,
                step=f"{label} PDF",
            ).body
        )
        return document, base + f"/{document['id']}"

    def prepare(organization: str, label: str):
        document, path = upload(organization, label)
        checked_request(
            "POST",
            path + "/extraction",
            token=owner,
            payload={},
            expected=202,
            step="queue search source",
        )
        wait_for_result(path + "/extraction", owner, "succeeded")
        chunk_set = checked_request(
            "POST",
            path + "/chunks",
            token=owner,
            payload={},
            expected=201,
            step="index search source",
        ).body
        return document, path, chunk_set

    def query(
        value: str,
        *,
        organization: str = org,
        token: str | None = owner,
        expected: int = 200,
        error_code=None,
        **filters,
    ):
        return checked_request(
            "GET",
            f"/organizations/{organization}/document-search?"
            + urlencode({"q": value, **filters}),
            token=token,
            expected=expected,
            error_code=error_code,
            step="tenant-scoped document search",
        ).body

    ada, ada_path, ada_set = prepare(org, "Search Ada")
    grace, _grace_path, _grace_set = prepare(org, "Search Grace")
    other, _other_path, _other_set = prepare(organizations[1], "Other tenant")
    asyncio.run(verify_indexes())
    result = query("CANDIDATE SMOKE")
    if result["total"] != 2 or {item["document_id"] for item in result["items"]} != {
        ada["id"],
        grace["id"],
    }:
        raise SmokeFailure(
            "Search did not return only the authorized organization's documents"
        )
    for item in result["items"]:
        if (
            not math.isfinite(item["score"])
            or not 0 <= item["score"] <= 1
            or item["text"] != "Candidate document smoke"
            or item["chunk_sha256"] != hashlib.sha256(item["text"].encode()).hexdigest()
        ):
            raise SmokeFailure("Search result text or provenance was incorrect")
    first = query("candidate smoke", limit=1, offset=0)
    second = query("candidate smoke", limit=1, offset=1)
    if (
        first["total"] != 2
        or second["total"] != 2
        or first["items"][0]["document_id"] == second["items"][0]["document_id"]
    ):
        raise SmokeFailure("Search pagination was not stable")
    beyond = query("candidate smoke", offset=1000)
    if beyond["items"] != [] or beyond["total"] != 2:
        raise SmokeFailure("Empty search page lost its total")
    if query("candidate smoke", candidate_id=ada["candidate_id"])["total"] != 1:
        raise SmokeFailure("Candidate search filter was incorrect")
    if query("candidate smoke", document_id=other["id"])["total"] != 0:
        raise SmokeFailure("Cross-organization document filter exposed a result")
    if query("candidate smoke", organization=organizations[1])["total"] != 1:
        raise SmokeFailure("Second organization search scope was incorrect")
    if query("unmatchedword" + uuid4().hex)["total"] != 0:
        raise SmokeFailure("Unmatched query returned results")
    if query("candidate'); DROP TABLE users; --")["total"] != 0:
        raise SmokeFailure("Operator-like query was not treated as literal words")
    query(
        "candidate", token=outsider, expected=404, error_code="ORGANIZATION_NOT_FOUND"
    )
    query("candidate", token=None, expected=401, error_code="INVALID_ACCESS_TOKEN")
    query("& |", expected=422)
    query("candidate", limit=51, expected=422)
    private = checked_binary(
        "GET",
        f"/organizations/{org}/document-search?q=candidate",
        token=owner,
        content_type="application/json",
        expected=200,
        step="private search response",
    )
    if private.headers.get("cache-control") != "private, no-store":
        raise SmokeFailure("Search response was cacheable")
    new_set = asyncio.run(seed_set(ada, "Candidate document smoke", alternate=True))
    hits = query("candidate smoke", document_id=ada["id"])
    if hits["total"] != 1 or hits["items"][0]["chunk_set_id"] != str(new_set):
        raise SmokeFailure("Search included an older chunk version")
    checked_request(
        "GET",
        ada_path + f"/chunks/{ada_set['id']}",
        token=owner,
        step="older chunk metadata retained",
    )
    persian, _persian_path = upload(org, "Synthetic Persian search fixture")
    source = "كَيَان مهندس\u200cنرم\u200cافزار با Python و PostgreSQL"
    asyncio.run(seed_set(persian, source, alternate=False))
    matches = query("کیان مهندس نرم افزار", document_id=persian["id"])
    if matches["total"] != 1 or matches["items"][0]["text"] != source:
        raise SmokeFailure(
            "Persian search normalization changed or failed to retrieve the source"
        )
    log_ok("Persian yeh kaf marks and half-space normalization preserves source")
    for extraction in (False, True):
        try:
            asyncio.run(
                set_visibility(persian["id"], visible=False, extraction=extraction)
            )
            if query("کیان", document_id=persian["id"])["total"] != 0:
                raise SmokeFailure("Search exposed a deleting or incomplete source")
        finally:
            asyncio.run(
                set_visibility(persian["id"], visible=True, extraction=extraction)
            )
    asyncio.run(verify_deadline(org, ada["uploaded_by_user_id"]))
    checked_request(
        "DELETE", ada_path, token=owner, expected=204, step="delete searched source"
    )
    if query("candidate smoke", document_id=ada["id"])["total"] != 0:
        raise SmokeFailure("Search resurrected deleted document chunks")
    log_ok("latest-version search provenance pagination isolation and deletion")


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"search-smoke-{suffix}", f"search-other-{suffix}"]
    emails = [
        f"search-owner-{suffix}@example.com",
        f"search-outsider-{suffix}@example.com",
    ]
    try:
        run(slugs, emails)
    finally:
        asyncio.run(cleanup(slugs, emails))
    print("[success] Document search Docker real-stack smoke flow passed.", flush=True)


if __name__ == "__main__":
    main()
