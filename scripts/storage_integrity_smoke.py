import asyncio
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from app.core.config import get_settings
from app.core.document_reconciliation import ReconciliationError, ReconciliationStorage
from app.core.document_storage import LocalDocumentStorage
from app.db.session import async_session_factory, engine
from app.schemas.candidate_document import DocumentUpload
from app.services.candidate_document import CandidateDocumentService
from app.services.document_reconciliation import DocumentReconciliationService
from scripts.application_smoke import (
    checked_request,
    cleanup_application_rows,
    register_and_login,
    response_id,
)
from scripts.candidate_document_smoke import (
    checked_binary,
    cleanup,
    connection,
    sample_pdf,
)
from scripts.docker_smoke import SmokeFailure, log_ok

OLD_TIME = time.time() - 8 * 86_400


async def database_checks(orgs, jobs, candidates, application):
    database = await connection()
    try:
        for job, candidate in ((1, 0), (0, 1), (1, 1)):
            try:
                async with database.transaction():
                    await database.execute(
                        "INSERT INTO applications (id, organization_id, job_id, candidate_id) VALUES ($1,$2,$3,$4)",
                        uuid4(),
                        UUID(orgs[0]),
                        UUID(jobs[job]),
                        UUID(candidates[candidate]),
                    )
                    raise SmokeFailure("PostgreSQL accepted a cross-tenant Application")
            except asyncpg.ForeignKeyViolationError as error:
                if not error.constraint_name.startswith(
                    "fk_applications_organization_id_"
                ):
                    raise SmokeFailure("Unexpected Application constraint") from error
        for column, value in (
            ("organization_id", orgs[1]),
            ("job_id", jobs[1]),
            ("candidate_id", candidates[1]),
        ):
            try:
                async with database.transaction():
                    await database.execute(
                        f"UPDATE applications SET {column}=$1 WHERE id=$2",
                        UUID(value),
                        UUID(application),
                    )
                    raise SmokeFailure("PostgreSQL accepted an ownership update")
            except asyncpg.ForeignKeyViolationError:
                pass
        for table, parent in (("jobs", jobs[0]), ("candidates", candidates[0])):
            try:
                async with database.transaction():
                    await database.execute(
                        f"UPDATE {table} SET organization_id=$1 WHERE id=$2",
                        UUID(orgs[1]),
                        UUID(parent),
                    )
                    raise SmokeFailure("PostgreSQL moved a referenced parent")
            except asyncpg.ForeignKeyViolationError:
                pass
        log_ok("PostgreSQL enforces both Application tenant FKs on insert and update")

        audit = runpy.run_path(
            str(
                Path(__file__).parents[1]
                / "migrations/versions/0015_application_tenant_fks.py"
            )
        )["AUDIT_SQL"]
        async with database.transaction():
            for table in ("jobs", "candidates", "applications"):
                columns = (
                    ", job_id uuid, candidate_id uuid"
                    if table == "applications"
                    else ""
                )
                await database.execute(
                    f"CREATE TEMP TABLE {table} (id uuid, organization_id uuid{columns}) ON COMMIT DROP"
                )
            for table, identifier in (("jobs", jobs[0]), ("candidates", candidates[0])):
                await database.execute(
                    f"INSERT INTO {table} VALUES ($1,$2)",
                    UUID(identifier),
                    UUID(orgs[0]),
                )
            await database.execute(
                "INSERT INTO applications VALUES ($1,$2,$3,$4)",
                uuid4(),
                UUID(orgs[0]),
                UUID(jobs[0]),
                UUID(candidates[0]),
            )
            await database.execute(audit)
            await database.execute(
                "UPDATE applications SET organization_id=$1", UUID(orgs[1])
            )
            try:
                async with database.transaction():
                    await database.execute(audit)
                    raise SmokeFailure(
                        "Migration audit accepted legacy tenant mismatch"
                    )
            except asyncpg.CheckViolationError:
                pass
        log_ok(
            "frozen migration audit accepts valid rows and refuses legacy mismatches"
        )
    finally:
        await database.close()


def cli_check(keys, *, apply=False):
    command = [sys.executable, "-m", "scripts.reconcile_documents"]
    for key in keys:
        command += ["--key", key]
    if apply:
        command.append("--apply")
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=40, check=False
    )
    if result.returncode:
        raise SmokeFailure("Scoped reconciliation CLI failed")
    records = [json.loads(line) for line in result.stdout.splitlines()]
    if not records or records[-1].get("event") != "summary" or not records[-1]["ok"]:
        raise SmokeFailure("Reconciliation summary was missing")
    return {
        item["key"]: item["action"] for item in records if item["event"] == "object"
    }


async def live_upload_check(root, org, candidate, email, tracked):
    published, release = asyncio.Event(), asyncio.Event()

    class PausedStorage(LocalDocumentStorage):
        async def save_pdf(self, chunks, *, max_bytes):
            stored = await super().save_pdf(chunks, max_bytes=max_bytes)
            tracked.append(stored.storage_key)
            os.utime(root / stored.storage_key, (OLD_TIME, OLD_TIME))
            published.set()
            await release.wait()
            return stored

    async def chunks():
        yield sample_pdf()

    database = await connection()
    try:
        user = await database.fetchval("SELECT id FROM users WHERE email=$1", email)
    finally:
        await database.close()

    async def upload():
        async with async_session_factory() as session:
            return await CandidateDocumentService(
                session,
                PausedStorage(root),
                max_bytes=1024 * 1024,
            ).upload(
                DocumentUpload(filename="live.pdf"),
                chunks(),
                organization_id=UUID(org),
                candidate_id=UUID(candidate),
                user_id=user,
                content_type="application/pdf",
                content_length=None,
            )

    task = asyncio.create_task(upload())
    try:
        await asyncio.wait_for(published.wait(), 10)
        key = tracked[-1]
        async with async_session_factory() as session:
            try:
                await DocumentReconciliationService(
                    session, ReconciliationStorage(root)
                ).run(
                    keys=(key,),
                    apply=True,
                )
                raise SmokeFailure(
                    "Reconciliation did not wait for an uncommitted upload"
                )
            except ReconciliationError as error:
                cause = error.__cause__
                if getattr(getattr(cause, "orig", None), "sqlstate", None) != "55P03":
                    raise SmokeFailure(
                        "Expected PostgreSQL lock timeout was missing"
                    ) from error
                if not (root / key).is_file():
                    raise SmokeFailure("Live upload was deleted")
        release.set()
        await asyncio.wait_for(task, 10)
        async with async_session_factory() as session:
            outcomes = await DocumentReconciliationService(
                session, ReconciliationStorage(root)
            ).run(
                keys=(key,),
                apply=True,
            )
        if outcomes[0].action != "keep_referenced":
            raise SmokeFailure("Committed live upload was not protected")
        log_ok(
            "published uncommitted upload blocks cleanup; committed metadata protects it"
        )
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


def run(slugs, emails, tracked):
    root = get_settings().document_storage_path
    token = register_and_login(emails[0], label="integrity owner")
    orgs, jobs, candidates, documents = [], [], [], []
    for slug in slugs:
        org = response_id(
            checked_request(
                "POST",
                "/organizations",
                token=token,
                expected=201,
                payload={"name": "Integrity smoke", "slug": slug},
                step="integrity organization",
            ),
            step="organization",
        )
        orgs.append(org)
        jobs.append(
            response_id(
                checked_request(
                    "POST",
                    f"/organizations/{org}/jobs",
                    token=token,
                    expected=201,
                    payload={"title": "Engineer", "description": "Synthetic job"},
                    step="integrity job",
                ),
                step="job",
            )
        )
        candidate = response_id(
            checked_request(
                "POST",
                f"/organizations/{org}/candidates",
                token=token,
                expected=201,
                payload={"full_name": "Integrity fixture"},
                step="integrity candidate",
            ),
            step="candidate",
        )
        candidates.append(candidate)
        result = checked_binary(
            "POST",
            f"/organizations/{org}/candidates/{candidate}/documents?filename=fixture.pdf",
            token=token,
            data=sample_pdf(),
            expected=201,
            step="integrity PDF",
        )
        documents.append(json.loads(result.body)["id"])
    application = response_id(
        checked_request(
            "POST",
            f"/organizations/{orgs[0]}/applications",
            token=token,
            expected=201,
            payload={"job_id": jobs[0], "candidate_id": candidates[0]},
            step="valid integrity Application",
        ),
        step="application",
    )
    asyncio.run(database_checks(orgs, jobs, candidates, application))

    async def reference_keys():
        database = await connection()
        try:
            await database.execute(
                "UPDATE candidate_documents SET status='deleting' WHERE id=$1",
                UUID(documents[0]),
            )
            return [
                await database.fetchval(
                    "SELECT storage_key FROM candidate_documents WHERE id=$1",
                    UUID(identifier),
                )
                for identifier in documents
            ]
        finally:
            await database.close()

    references = asyncio.run(reference_keys())
    for key in references:
        os.utime(root / key, (OLD_TIME, OLD_TIME))
    orphan, temporary, young, link, hard = (
        uuid4().hex + ".pdf",
        ".upload-" + uuid4().hex[:8],
        uuid4().hex + ".pdf",
        uuid4().hex + ".pdf",
        uuid4().hex + ".pdf",
    )
    unknown = f"integrity-{uuid4().hex}.txt"
    for key in (orphan, temporary, young, unknown):
        with (root / key).open("xb") as handle:
            handle.write(b"synthetic orphan fixture")
        tracked.append(key)
    for key in (orphan, temporary):
        os.utime(root / key, (OLD_TIME, OLD_TIME))
    (root / link).symlink_to(root / unknown)
    tracked.append(link)
    os.link(root / unknown, root / hard)
    tracked.append(hard)
    selected = (*references, orphan, temporary, young, link, hard)
    preview = cli_check(selected)
    if preview != {
        **dict.fromkeys(references, "keep_referenced"),
        orphan: "would_delete",
        temporary: "would_delete",
        young: "keep_young",
        link: "keep_unsafe",
        hard: "keep_unsafe",
    }:
        raise SmokeFailure("Dry-run retention or tenant scope was incorrect")
    if any(not (root / key).exists() for key in selected):
        raise SmokeFailure("Dry-run removed an object")
    applied = cli_check(selected, apply=True)
    if applied[orphan] != "deleted" or applied[temporary] != "deleted":
        raise SmokeFailure("Old scoped orphan cleanup did not run")
    if any(applied[key] != preview[key] for key in (*references, young, link, hard)):
        raise SmokeFailure("Cleanup removed a protected object")
    if cli_check((orphan, temporary), apply=True) != {
        orphan: "missing",
        temporary: "missing",
    }:
        raise SmokeFailure("Cleanup retry was not idempotent")
    if (root / unknown).read_bytes() != b"synthetic orphan fixture":
        raise SmokeFailure("Cleanup followed a link")
    log_ok(
        "CLI dry-run age scope ready/deleting tenant references links and repeatable apply"
    )

    live_candidate = response_id(
        checked_request(
            "POST",
            f"/organizations/{orgs[0]}/candidates",
            token=token,
            expected=201,
            payload={"full_name": "Live upload fixture"},
            step="live upload candidate",
        ),
        step="candidate",
    )
    asyncio.run(live_upload_check(root, orgs[0], live_candidate, emails[0], tracked))


def main():
    seed = uuid4().hex
    slugs = [f"integrity-{seed}-a", f"integrity-{seed}-b"]
    emails = [f"integrity-{seed}@example.com"]
    tracked = []
    try:
        run(slugs, emails, tracked)
    finally:
        # Session/engine cleanup first; metadata and files are limited to our fixtures.
        asyncio.run(engine.dispose())
        for slug in slugs:
            asyncio.run(cleanup_application_rows(slug))
        asyncio.run(cleanup(slugs, emails))
        root = get_settings().document_storage_path
        for key in tracked:
            (root / key).unlink(missing_ok=True)
    print("[success] Storage and Application integrity Docker real-stack smoke passed.")


if __name__ == "__main__":
    main()
