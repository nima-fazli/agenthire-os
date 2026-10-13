import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.schemas.job_matching import JobMatchEvidenceRead

REFERENCE = Path(__file__).with_name("fixtures") / "grounded_explanations_v1.json"


def load_reference():
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def example_snapshot(case=None):
    """A synthetic DTO for unit tests; never label its observations real-stack."""
    case = case or load_reference()["cases"][0]
    text, now = case["text"], datetime(2026, 10, 13, tzinfo=UTC)
    evidence = None if text is None else {
        "document_id": UUID(int=3), "candidate_id": UUID(int=2), "candidate_name": "Synthetic",
        "filename": "synthetic.pdf", "chunk_set_id": UUID(int=4), "chunk_position": 0,
        "start_offset": 0, "end_offset": len(text), "text": text,
        "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_document_sha256": "b" * 64, "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "score": 0.5}
    return JobMatchEvidenceRead(job_id=UUID(int=1), candidate_id=UUID(int=2), candidate_name="Synthetic",
        profile_revision=1, profile_updated_at=now, observed_at=now,
        criteria=[{"key": "skill", "label": "Source mention", "q": case["q"], "position": 0,
                   "importance": "required", "evidence": evidence},
                  {"key": "missing", "label": "Rust", "q": "Rust", "position": 1,
                   "importance": "preferred", "evidence": None}],
        summary={"required_total": 1, "required_with_evidence": int(text is not None),
            "preferred_total": 1, "preferred_with_evidence": 0, "ready_documents": int(text is not None),
            "indexed_documents": int(text is not None), "source_status": "indexed" if text else "no_documents"})


def evaluate(reference, observations, *, model_kind, model_digest, source_kind):
    if (reference["version"] != "grounded-reference-v1" or model_kind not in {"fixture", "live"} or
        source_kind not in {"example", "real_stack"} or
        model_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", model_digest)):
        raise ValueError("Invalid reference or provenance.")
    cases = {case["key"]: case for case in reference["cases"]}
    if not cases or len(cases) != len(reference["cases"]) or len(observations) != len(cases) or {
        row["case"] for row in observations} != set(cases):
        raise ValueError("Exactly one observation per case is required.")
    results, failures = [], []
    for row in observations:
        case, issues = cases[row["case"]], []
        latency = row["elapsed_ms"]
        if type(latency) not in {float, int} or not math.isfinite(latency) or latency < 0:
            raise ValueError("Invalid latency observation.")
        if row["status"] == "rejected":
            if case["key"] != "injected" or row.get("code") not in {
                "EXPLANATION_OUTPUT_INVALID", "EXPLANATION_OUTPUT_UNGROUNDED"}:
                issues.append("unexpected_rejection")
        elif row["status"] == "ok":
            page = row["result"]
            items = {item["key"]: item for item in page["criteria"]}
            if len(page["criteria"]) != 2 or set(items) != {"skill", "missing"}:
                issues.append("criterion_coverage")
            for key, item in items.items():
                expected = key == "skill" and case["text"] is not None
                citation = item["citation"]
                if expected:
                    quote = citation["quote"] if citation else ""
                    if (item["state"] != "mention_observed" or not quote or
                        case["text"][citation["start_offset"]:citation["end_offset"]] != quote or
                        citation["document_id"] != row["document_id"] or
                        citation["chunk_set_id"] != row["chunk_set_id"] or
                        citation["quote_sha256"] != hashlib.sha256(quote.encode()).hexdigest()):
                        issues.append("invalid_citation")
                elif citation is not None or item["state"] != "no_evidence":
                    issues.append("invented_evidence")
            if page["language"] != case["language"] or page["generator_used"] != (case["text"] is not None):
                issues.append("generation_contract")
            if page["generator_used"] and (model_digest is None or page["model_digest"] != model_digest):
                issues.append("model_space")
        else:
            raise ValueError("Invalid observation status.")
        failures.extend(row["case"] + ":" + issue for issue in issues)
        results.append({"case": row["case"], "status": row["status"], "elapsed_ms": latency, "issues": issues})
    return {"version": "grounded-quality-v1", "source_kind": source_kind, "model_kind": model_kind,
        "model_tag": "qwen3:0.6b", "model_digest": model_digest, "corpus_kind": "synthetic_reference",
        "reference_sha256": hashlib.sha256(json.dumps(reference, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(), "cases": results,
        "failures": failures, "gate_passed": not failures}
