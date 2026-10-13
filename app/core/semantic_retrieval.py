import math

WINDOW = 100
RRF_K = 60
QUERY_VERSION = "qwen3-resume-query-v1"
RETRIEVAL_VERSION = "local-cosine-rrf-v1"
EVIDENCE_FIELDS = (
    "document_id", "candidate_id", "candidate_name", "filename", "chunk_set_id",
    "chunk_position", "start_offset", "end_offset", "text", "chunk_sha256",
    "source_document_sha256", "source_text_sha256", "score", "embedding_job_id",
)


def query_input(q: str) -> str:
    return "Instruct: Retrieve resume passages relevant to this job requirement.\nQuery: " + q


def fuse(rows: list[dict], *, mode: str, candidates: bool) -> list[dict]:
    groups, seen = {}, {"semantic": set(), "lexical": set()}
    for row in rows:
        branch = row["branch"]
        if branch not in seen or not math.isfinite(row["score"]):
            raise ValueError("Invalid retrieval observation.")
        if mode == "semantic" and branch != "semantic":
            continue
        key = (str(row["candidate_id"]),) if candidates else (
            str(row["document_id"]), str(row["chunk_set_id"]), row["chunk_position"]
        )
        if key in seen[branch]:
            continue
        seen[branch].add(key)
        group = groups.setdefault(key, {
            "candidate_id": row["candidate_id"], "candidate_name": row["candidate_name"],
            "lexical_rank": None, "semantic_rank": None, "evidence": [],
        })
        group[branch + "_rank"] = len(seen[branch])
        group["evidence"].append({name: row[name] for name in EVIDENCE_FIELDS} | {"branch": branch})
    for group in groups.values():
        group["evidence"].sort(key=lambda item: item["branch"])
        group["score"] = (
            group["evidence"][0]["score"] if mode == "semantic" else
            math.fsum(1 / (RRF_K + group[name]) for name in ("lexical_rank", "semantic_rank")
                      if group[name] is not None) / (2 / (RRF_K + 1))
        )
    return [item for _, item in sorted(groups.items(), key=lambda pair: (-pair[1]["score"], pair[0]))]
