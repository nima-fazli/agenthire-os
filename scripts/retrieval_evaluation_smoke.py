import asyncio
import hashlib
import json
from uuid import uuid4

from app.schemas.job_matching import JobMatchProfileRead
from app.schemas.retrieval_evaluation import ChunkPolicy, EvaluationReport
from app.services.retrieval_evaluation import RetrievalEvaluationService
from scripts.application_smoke import checked_request, register_and_login
from scripts.candidate_document_smoke import checked_binary, sample_pdf
from scripts.docker_smoke import SmokeFailure, log_ok
from scripts.document_extraction_smoke import wait_for_result
from scripts.document_search_smoke import seed_set
from scripts.evaluation_cases import (
    ITEM_KEYS,
    PERSIAN_SOURCE,
    RESUME_TEXT,
    ascii_resume_pdf,
    load_suite,
)
from scripts.evaluation_stack import SourceDocument, collect_observations
from scripts.job_matching_smoke import split_skills_pdf
from scripts.job_retrieval_smoke import cleanup_retrieval


def run(slugs: list[str], emails: list[str]) -> EvaluationReport:
    suite = load_suite()
    owner = register_and_login(emails[0], label="quality owner")

    def api(method, path, *, payload=None, expected=200):
        if method == "GET":
            response = checked_binary(
                method,
                path,
                token=owner,
                content_type="application/json",
                expected=expected,
                step="private quality observation",
            )
            if response.headers.get("cache-control") != "private, no-store":
                raise SmokeFailure("Quality source response was cacheable")
            return json.loads(response.body)
        return checked_request(
            method,
            path,
            token=owner,
            payload=payload,
            expected=expected,
            step="quality fixture",
        ).body

    organizations = [
        api(
            "POST",
            "/organizations",
            payload={"name": "Quality Reference", "slug": slug},
            expected=201,
        )["id"]
        for slug in slugs
    ]
    org = organizations[0]
    job = api(
        "POST",
        f"/organizations/{org}/jobs",
        payload={
            "title": "Quality reference job",
            "description": "Python SQL",
            "status": "open",
        },
        expected=201,
    )["id"]
    job_path = f"/organizations/{org}/jobs/{job}"
    profile = JobMatchProfileRead.model_validate(
        api(
            "PUT",
            job_path + "/match-profile",
            payload={"criteria": [item.model_dump() for item in suite.criteria]},
        )
    )
    if profile.revision != 1:
        raise SmokeFailure("Fresh evaluation profile did not start at revision one")
    candidates, sources = {}, {}
    for key in ITEM_KEYS:
        organization = organizations[1] if key == "other-tenant" else org
        candidates[key] = api(
            "POST",
            f"/organizations/{organization}/candidates",
            payload={"full_name": "Synthetic " + key},
            expected=201,
        )["id"]

    def upload(key, data):
        organization = organizations[1] if key == "other-tenant" else org
        parent = f"/organizations/{organization}/candidates/{candidates[key]}/documents"
        document = json.loads(
            checked_binary(
                "POST",
                parent + "?filename=quality.pdf",
                token=owner,
                data=data,
                expected=201,
                step="quality PDF upload",
            ).body
        )
        if (
            document["sha256"] != hashlib.sha256(data).hexdigest()
            or document["size_bytes"] != len(data)
            or document["candidate_id"] != candidates[key]
            or document["organization_id"] != organization
        ):
            raise SmokeFailure("Quality PDF metadata did not describe its fixture")
        return document, parent + "/" + document["id"]

    def index(key, document, path):
        api("POST", path + "/extraction", payload={}, expected=202)
        wait_for_result(path + "/extraction", owner, "succeeded")
        source = api("GET", path + "/extraction/text")["text"]
        chunks = api("POST", path + "/chunks", payload={}, expected=201)
        sources[document["id"]] = SourceDocument(
            candidates[key],
            source,
            document["sha256"],
            chunks["id"],
            ChunkPolicy(
                chunker_version=chunks["chunker_version"],
                max_chars=chunks["chunk_max_chars"],
                overlap_chars=chunks["chunk_overlap_chars"],
            ),
        )

    for key in ("ada", "grace", "linus", "bruno", "other-tenant"):
        data = (
            split_skills_pdf() if key == "bruno" else ascii_resume_pdf(RESUME_TEXT[key])
        )
        document, path = upload(key, data)
        index(key, document, path)
    duplicate, duplicate_path = upload(
        "ada", ascii_resume_pdf(RESUME_TEXT["ada"]) + b"\n"
    )
    index("ada", duplicate, duplicate_path)
    upload("ada", ascii_resume_pdf(RESUME_TEXT["ada"]) + b"\n\n")
    upload("pending", ascii_resume_pdf(RESUME_TEXT["pending"]))
    persian, persian_path = upload("kian", sample_pdf())
    latest = asyncio.run(seed_set(persian, PERSIAN_SOURCE, alternate=False))
    persian_chunks = api("GET", persian_path + f"/chunks/{latest}")
    sources[persian["id"]] = SourceDocument(
        candidates["kian"],
        PERSIAN_SOURCE,
        persian["sha256"],
        str(latest),
        ChunkPolicy(
            chunker_version=persian_chunks["chunker_version"],
            max_chars=persian_chunks["chunk_max_chars"],
            overlap_chars=persian_chunks["chunk_overlap_chars"],
        ),
    )
    observations = collect_observations(
        suite, api, job_path=job_path, candidates=candidates, sources=sources
    )
    return RetrievalEvaluationService().evaluate(suite, observations)


def main() -> None:
    suffix = uuid4().hex
    slugs = [f"quality-smoke-{suffix}", f"quality-other-{suffix}"]
    emails = [f"quality-owner-{suffix}@example.com"]
    try:
        report = run(slugs, emails)
        if report.source_kind != "real_stack":
            raise SmokeFailure(
                "Real-stack quality evaluation received example observations"
            )
        print(report.model_dump_json(indent=2), flush=True)
        if not report.gate_passed:
            raise SmokeFailure("Retrieval quality reference gate failed")
        log_ok(
            "reference ranking metrics evidence labels provenance readiness and tenant exclusion"
        )
    finally:
        asyncio.run(cleanup_retrieval(slugs, emails))
    print(
        "[success] Retrieval quality Docker real-stack evaluation passed.", flush=True
    )


if __name__ == "__main__":
    main()
