import math
from collections.abc import Mapping, Sequence


def ranking_metrics(
    ranked: Sequence[str], judgments: Mapping[str, int], *, k: int
) -> dict:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer.")
    if len(set(ranked)) != len(ranked):
        raise ValueError("Ranking must not contain duplicate items.")
    if any(
        type(grade) is not int or not 0 <= grade <= 3 for grade in judgments.values()
    ):
        raise ValueError("Relevance grades must be integers from zero to three.")
    top = ranked[:k]
    grades = [judgments.get(item, 0) for item in top]
    relevant = sum(grade > 0 for grade in judgments.values())
    hits = sum(grade > 0 for grade in grades)

    def dcg(values):
        return math.fsum(
            (2**grade - 1) / math.log2(position + 2)
            for position, grade in enumerate(values)
        )

    ideal = dcg(sorted(judgments.values(), reverse=True)[:k])
    reciprocal = next(
        (1 / (position + 1) for position, grade in enumerate(grades) if grade > 0),
        0.0,
    )
    return {
        "k": k,
        "retrieved_count": len(ranked),
        "returned_at_k": len(top),
        "relevant_count": relevant,
        "hits_at_k": hits,
        "unjudged_count": sum(item not in judgments for item in ranked),
        "precision_at_k": hits / k,
        "recall_at_k": hits / relevant if relevant else None,
        "ndcg_at_k": dcg(grades) / ideal if ideal else None,
        "reciprocal_rank_at_k": reciprocal if relevant else None,
    }


def confusion_counts(
    expected: Mapping[str, bool], observed: Mapping[str, bool]
) -> dict:
    if expected.keys() != observed.keys():
        raise ValueError("Expected and observed criterion keys must match.")
    if any(
        type(value) is not bool for value in (*expected.values(), *observed.values())
    ):
        raise ValueError("Evidence labels must be booleans.")
    counts = dict.fromkeys(
        ("true_positive", "false_positive", "false_negative", "true_negative"), 0
    )
    for key, actual in observed.items():
        name = (
            ("true_positive" if actual else "false_negative")
            if expected[key]
            else ("false_positive" if actual else "true_negative")
        )
        counts[name] += 1
    return counts


def evidence_rates(counts: Mapping[str, int]) -> dict:
    names = ("true_positive", "false_positive", "false_negative", "true_negative")
    if set(counts) != set(names) or any(
        type(value) is not int or value < 0 for value in counts.values()
    ):
        raise ValueError("Confusion counts must be nonnegative integers.")
    tp, fp, fn, tn = (counts[name] for name in names)
    return {
        "evidence_checks": tp + fp + fn + tn,
        "evidence_precision": tp / (tp + fp) if tp + fp else None,
        "evidence_recall": tp / (tp + fn) if tp + fn else None,
        "evidence_accuracy": (tp + tn) / (tp + fp + fn + tn)
        if tp + fp + fn + tn
        else None,
    }


def defined_mean(values: Sequence[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    if any(not math.isfinite(value) for value in defined):
        raise ValueError("Metrics must be finite.")
    return math.fsum(defined) / len(defined) if defined else None
