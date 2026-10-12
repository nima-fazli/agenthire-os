import hashlib
from dataclasses import dataclass

from app.schemas.job_matching import JobMatchEvidenceRead
from app.schemas.job_retrieval import JobCandidatePage, JobSearchProfileRead
from app.schemas.retrieval_evaluation import (
    ChunkPolicy,
    EvaluationObservations,
    EvaluationSuite,
)
from app.services.retrieval_evaluation import suite_digest
from scripts.docker_smoke import SmokeFailure


@dataclass(frozen=True)
class SourceDocument:
    candidate_id: str
    text: str
    document_sha256: str
    chunk_set_id: str
    policy: ChunkPolicy


def valid_provenance(
    hit, *, candidate_id: str, sources: dict[str, SourceDocument]
) -> bool:
    source = sources.get(str(hit.document_id))
    if source is None:
        return False
    return (
        str(hit.candidate_id) == candidate_id == source.candidate_id
        and str(hit.chunk_set_id) == source.chunk_set_id
        and 0 <= hit.start_offset < hit.end_offset <= len(source.text)
        and source.text[hit.start_offset : hit.end_offset] == hit.text
        and hashlib.sha256(hit.text.encode()).hexdigest() == hit.chunk_sha256
        and hashlib.sha256(source.text.encode()).hexdigest() == hit.source_text_sha256
        and source.document_sha256 == hit.source_document_sha256
    )


def collect_observations(
    suite: EvaluationSuite,
    api,
    *,
    job_path: str,
    candidates: dict[str, str],
    sources: dict[str, SourceDocument],
) -> EvaluationObservations:
    identifiers = {value: key for key, value in candidates.items()}
    if len(identifiers) != len(candidates):
        raise SmokeFailure("Evaluation candidate identities were not unique")
    ranking, evidence, search_versions, retrieval_versions, matching_versions = (
        [],
        [],
        set(),
        set(),
        set(),
    )
    job_id = job_path.rsplit("/", 1)[1]
    for case in suite.ranking:
        profile = JobSearchProfileRead.model_validate(
            api("PUT", job_path + "/search-profile", payload={"q": case.q})
        )
        page_data = api("GET", job_path + "/candidate-retrieval?limit=50")
        if not {"search_version", "retrieval_version", "score_kind"}.issubset(
            page_data
        ):
            raise SmokeFailure("Evaluation retrieval version metadata was missing")
        page = JobCandidatePage.model_validate(page_data)
        if (
            str(profile.job_id) != job_id
            or str(page.job_id) != job_id
            or profile.q != case.q
            or page.q != case.q
            or page.profile_revision != profile.revision
            or page.total != len(page.items)
            or page.applicants_only
            or page.offset != 0
            or page.limit != 50
        ):
            raise SmokeFailure("Evaluation retrieval profile or page was inconsistent")
        search_versions.add(page.search_version)
        retrieval_versions.add(page.retrieval_version)
        rows, invalid = [], 0
        for hit in page.items:
            candidate_id = str(hit.candidate_id)
            key = identifiers.get(candidate_id)
            if key is None:
                key = (
                    "unjudged:" + hashlib.sha256(candidate_id.encode()).hexdigest()[:16]
                )
            rows.append(key)
            invalid += not valid_provenance(
                hit, candidate_id=candidate_id, sources=sources
            )
        ranking.append(
            {"key": case.key, "ranked_ids": rows, "provenance_failures": invalid}
        )

    expected_criteria = [
        item.model_dump() | {"position": position}
        for position, item in enumerate(suite.criteria)
    ]
    for case in suite.evidence:
        candidate_id = candidates[case.item_id]
        report_data = api(
            "GET", job_path + f"/candidates/{candidate_id}/match-evidence"
        )
        if not {"search_version", "matching_version", "evidence_kind"}.issubset(
            report_data
        ):
            raise SmokeFailure("Evaluation matching version metadata was missing")
        report = JobMatchEvidenceRead.model_validate(report_data)
        actual_criteria = [
            item.model_dump(exclude={"evidence"}) for item in report.criteria
        ]
        if (
            str(report.job_id) != job_id
            or str(report.candidate_id) != candidate_id
            or actual_criteria != expected_criteria
            or report.profile_revision != case.profile_revision
        ):
            raise SmokeFailure(
                "Evaluation matching identity or criterion snapshot changed"
            )
        search_versions.add(report.search_version)
        matching_versions.add(report.matching_version)
        evidence.append(
            {
                "key": case.key,
                "profile_revision": report.profile_revision,
                "source_status": report.summary.source_status,
                "criteria": [
                    {
                        "key": item.key,
                        "found": item.evidence is not None,
                        "provenance_valid": valid_provenance(
                            item.evidence, candidate_id=candidate_id, sources=sources
                        )
                        if item.evidence is not None
                        else None,
                    }
                    for item in report.criteria
                ],
            }
        )
    if any(
        len(values) != 1
        for values in (search_versions, retrieval_versions, matching_versions)
    ):
        raise SmokeFailure("Evaluation backend versions were incomplete or mixed")
    return EvaluationObservations.model_validate(
        {
            "suite_sha256": suite_digest(suite),
            "source_kind": "real_stack",
            "search_version": next(iter(search_versions)),
            "retrieval_version": next(iter(retrieval_versions)),
            "matching_version": next(iter(matching_versions)),
            "chunk_policies": [
                {
                    "chunker_version": version,
                    "max_chars": size,
                    "overlap_chars": overlap,
                }
                for version, size, overlap in sorted(
                    {
                        (
                            source.policy.chunker_version,
                            source.policy.max_chars,
                            source.policy.overlap_chars,
                        )
                        for source in sources.values()
                    }
                )
            ],
            "ranking": ranking,
            "evidence": evidence,
        }
    )
