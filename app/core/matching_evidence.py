from collections.abc import Iterable

MATCHING_VERSION = "criterion-evidence-v1"


def summarize_evidence(
    outcomes: Iterable[tuple[str, bool]],
    *,
    ready_documents: int,
    indexed_documents: int,
) -> dict:
    if not 0 <= indexed_documents <= ready_documents:
        raise ValueError(
            "Indexed document count must be within the ready document count."
        )
    counts = {
        "required_total": 0,
        "required_with_evidence": 0,
        "preferred_total": 0,
        "preferred_with_evidence": 0,
    }
    for importance, found in outcomes:
        if importance not in {"required", "preferred"} or not isinstance(found, bool):
            raise ValueError("Unsupported evidence outcome.")
        if found and indexed_documents == 0:
            raise ValueError("Evidence requires an indexed document.")
        counts[f"{importance}_total"] += 1
        counts[f"{importance}_with_evidence"] += int(found)
    source_status = (
        "no_documents"
        if ready_documents == 0
        else "not_indexed"
        if indexed_documents == 0
        else "partial"
        if indexed_documents < ready_documents
        else "indexed"
    )
    return counts | {
        "ready_documents": ready_documents,
        "indexed_documents": indexed_documents,
        "source_status": source_status,
    }
