import hashlib
import json
import math
import re
from pathlib import Path

from app.core.retrieval_metrics import defined_mean, ranking_metrics
from app.core.semantic_embeddings import DIMENSIONS, ENCODING_VERSION, MODEL_TAG
from app.core.semantic_retrieval import QUERY_VERSION, RETRIEVAL_VERSION
from app.core.text_search import SEARCH_VERSION

REFERENCE = Path(__file__).with_name("fixtures") / "semantic_retrieval_v1.json"
MODES = ("lexical", "semantic", "hybrid")


def load_reference():
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def evaluate(reference, observations, *, model_digest, model_kind, source_kind):
    if reference["version"] != "semantic-reference-v1" or not reference["cases"]:
        raise ValueError("Invalid reference version or empty suite.")
    if source_kind not in {"example", "real_stack"}:
        raise ValueError("Invalid observation provenance.")
    if model_kind not in {"fixture", "live"} or not re.fullmatch(r"[0-9a-f]{64}", model_digest):
        raise ValueError("Invalid model provenance.")
    expected = {(case["key"], mode) for case in reference["cases"] for mode in MODES}
    actual = {(row["case"], row["mode"]) for row in observations}
    if actual != expected or len(observations) != len(expected):
        raise ValueError("Every reference case requires exactly three observations.")
    rows, failures = [], []
    for row in observations:
        elapsed = row["elapsed_ms"]
        if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid latency observation.")
        metrics = ranking_metrics(row["ranking"], reference["judgments"], k=1)
        if metrics["unjudged_count"]:
            failures.append(row["case"] + ":unjudged:" + row["mode"])
        if row["mode"] != "lexical" and metrics["ndcg_at_k"] != 1:
            failures.append(row["case"] + ":ranking:" + row["mode"])
        rows.append({"case": row["case"], "mode": row["mode"],
                     "elapsed_ms": row["elapsed_ms"], "metrics": metrics})
    means = {mode: defined_mean([row["metrics"]["ndcg_at_k"] for row in rows
                                if row["mode"] == mode]) for mode in MODES}
    if any(means[mode] < means["lexical"] for mode in ("semantic", "hybrid")):
        failures.append("regression_against_lexical")
    return {"version": "semantic-quality-v1", "source_kind": source_kind,
            "corpus_kind": "synthetic_reference", "model_kind": model_kind,
            "model_digest": model_digest,
            "model_tag": MODEL_TAG, "dimensions": DIMENSIONS,
            "backend_versions": {"retrieval": RETRIEVAL_VERSION, "query": QUERY_VERSION,
                                 "encoding": ENCODING_VERSION, "lexical": SEARCH_VERSION},
            "reference_sha256": hashlib.sha256(json.dumps(reference, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "mean_ndcg_at_1": means, "cases": rows, "failures": failures,
            "gate_passed": not failures}
