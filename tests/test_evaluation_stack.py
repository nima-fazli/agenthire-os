import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.schemas.document_search import DocumentSearchHit
from app.schemas.retrieval_evaluation import ChunkPolicy
from app.services.retrieval_evaluation import RetrievalEvaluationService
from scripts.docker_smoke import SmokeFailure
from scripts.evaluation_cases import ITEM_KEYS, load_example, load_suite
from scripts.evaluation_stack import (
    SourceDocument,
    collect_observations,
    valid_provenance,
)


@pytest.fixture
def context():
    suite, example = load_suite(), load_example()
    candidates = {key: str(uuid4()) for key in ITEM_KEYS}
    job, now = str(uuid4()), datetime.now(UTC)
    text, sources, hits = "Python SQL", {}, {}
    for key, candidate_id in candidates.items():
        document, chunk_set = str(uuid4()), str(uuid4())
        source = SourceDocument(
            candidate_id,
            text,
            "a" * 64,
            chunk_set,
            ChunkPolicy(
                chunker_version="char-window-v1", max_chars=1200, overlap_chars=150
            ),
        )
        sources[document] = source
        hits[key] = {
            "candidate_id": candidate_id,
            "candidate_name": "Synthetic",
            "document_id": document,
            "filename": "quality.pdf",
            "chunk_set_id": chunk_set,
            "chunk_position": 0,
            "start_offset": 0,
            "end_offset": len(text),
            "text": text,
            "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_document_sha256": "a" * 64,
            "score": 0.1,
        }
    state = {
        "q": None,
        "calls": [],
        "page_extra": [],
        "bad_revision": False,
        "bad_q": False,
    }

    def api(method, path, *, payload=None):
        state["calls"].append((method, path, payload))
        if method == "PUT":
            state["q"] = payload["q"]
            return {
                "job_id": job,
                "q": payload["q"],
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
        if "/candidate-retrieval" in path:
            case = next(item for item in suite.ranking if item.q == state["q"])
            observed = next(item for item in example.ranking if item.key == case.key)
            items = [hits[key] for key in observed.ranked_ids] + state["page_extra"]
            return {
                "job_id": job,
                "q": "override" if state["bad_q"] else case.q,
                "profile_revision": 2 if state["bad_revision"] else 1,
                "profile_updated_at": now,
                "search_version": "simple-fold-v1",
                "retrieval_version": "best-chunk-v1",
                "score_kind": "text_relevance",
                "applicants_only": False,
                "items": items,
                "total": len(items),
                "limit": 50,
                "offset": 0,
            }
        candidate_id = path.split("/candidates/", 1)[1].split("/", 1)[0]
        key = next(item for item, value in candidates.items() if value == candidate_id)
        case = next(item for item in suite.evidence if item.item_id == key)
        criteria = [
            item.model_dump()
            | {
                "position": position,
                "evidence": hits[key] if case.expected[item.key] else None,
            }
            for position, item in enumerate(suite.criteria)
        ]
        return {
            "job_id": job,
            "candidate_id": candidate_id,
            "candidate_name": "Synthetic",
            "profile_revision": 1,
            "profile_updated_at": now,
            "observed_at": now,
            "search_version": "simple-fold-v1",
            "matching_version": "criterion-evidence-v1",
            "evidence_kind": "lexical_terms",
            "criteria": criteria,
            "summary": {
                "required_total": 2,
                "required_with_evidence": sum(
                    case.expected[key] for key in ("python", "sql")
                ),
                "preferred_total": 3,
                "preferred_with_evidence": sum(
                    case.expected[key] for key in ("go", "persian", "together")
                ),
                "ready_documents": 0
                if case.source_status == "no_documents"
                else 3
                if case.source_status == "partial"
                else 1,
                "indexed_documents": 0
                if case.source_status in {"no_documents", "not_indexed"}
                else 2
                if case.source_status == "partial"
                else 1,
                "source_status": case.source_status,
            },
        }

    return suite, candidates, job, sources, hits, state, api


def collect(context):
    suite, candidates, job, sources, _, _, api = context
    return collect_observations(
        suite,
        api,
        job_path=f"/organizations/{uuid4()}/jobs/{job}",
        candidates=candidates,
        sources=sources,
    )


def test_collector_projects_private_sources_into_anonymous_quality_observations(
    context,
):
    observed = collect(context)
    assert observed.source_kind == "real_stack"
    assert RetrievalEvaluationService().evaluate(context[0], observed).gate_passed
    encoded = observed.model_dump_json()
    assert "Python SQL" not in encoded and "candidate_name" not in encoded
    assert not any(value in encoded for value in context[1].values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_offset", -1),
        ("end_offset", 50),
        ("text", "wrong"),
        ("chunk_sha256", "b" * 64),
        ("source_text_sha256", "b" * 64),
        ("source_document_sha256", "b" * 64),
        ("chunk_set_id", str(uuid4())),
        ("candidate_id", str(uuid4())),
    ],
)
def test_wrong_source_offsets_hashes_identity_or_latest_set_fail_provenance(
    context, field, value
):
    hit = DocumentSearchHit.model_validate(context[4]["ada"] | {field: value})
    assert not valid_provenance(hit, candidate_id=context[1]["ada"], sources=context[3])


@pytest.mark.parametrize(
    "field",
    [
        "search_version",
        "retrieval_version",
        "score_kind",
        "matching_version",
        "evidence_kind",
    ],
)
def test_missing_actual_backend_metadata_is_not_filled_from_schema_defaults(
    context, field
):
    original = context[6]

    def api(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if method == "GET":
            result.pop(field, None)
        return result

    with pytest.raises(SmokeFailure, match="metadata was missing"):
        collect((*context[:6], api))


def test_unknown_document_fails_provenance(context):
    hit = DocumentSearchHit.model_validate(context[4]["ada"])
    assert not valid_provenance(hit, candidate_id=context[1]["ada"], sources={})


@pytest.mark.parametrize("field", ["bad_revision", "bad_q"])
def test_collector_rejects_inconsistent_profile_snapshots(context, field):
    context[5][field] = True
    with pytest.raises(SmokeFailure):
        collect(context)


def test_foreign_candidate_anywhere_in_results_fails_tenant_gate(context):
    context[5]["page_extra"] = [context[4]["other-tenant"]]
    observed = collect(context)
    report = RetrievalEvaluationService().evaluate(context[0], observed)
    assert not report.gate_passed and "FORBIDDEN_RESULT" in {
        item.code for item in report.failures
    }


def test_collector_records_actual_policy_variants_without_candidate_identifiers(
    context,
):
    document = context[4]["ada"]["document_id"]
    context[3][document] = replace(
        context[3][document],
        policy=ChunkPolicy(
            chunker_version="char-window-v1", max_chars=1500, overlap_chars=150
        ),
    )
    observed = collect(context)
    assert {item.max_chars for item in observed.chunk_policies} == {1200, 1500}


def test_unknown_candidate_is_anonymous_and_fails_the_reference_gate(context):
    unknown = str(uuid4())
    context[5]["page_extra"] = [context[4]["other-tenant"] | {"candidate_id": unknown}]
    observed = collect(context)
    assert unknown not in observed.model_dump_json()
    assert any(
        value.startswith("unjudged:") for value in observed.ranking[0].ranked_ids
    )
    report = RetrievalEvaluationService().evaluate(context[0], observed)
    assert not report.gate_passed and "UNJUDGED_RESULT" in {
        item.code for item in report.failures
    }
