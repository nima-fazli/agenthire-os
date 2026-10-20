# Local semantic retrieval

Optional semantic and hybrid retrieval use PostgreSQL/pgvector and local Ollama.
The lexical endpoints retain their independent contracts. The current database
head is `0017_access_sessions`.

## Model and indexing contracts

- `AGENTHIRE_SEMANTIC_ENABLED` remains false by default.
- Model: `qwen3-embedding:0.6b`; dimensions: 1024.
- Encoding: `qwen3-raw-l2-v1`; query template: `qwen3-resume-query-v1`.
- Passage text is embedded without rewriting. Vectors are finite and L2-normalized.
- Inputs are not silently truncated; each model batch verifies the full digest.
- Local transports bypass proxies and refuse redirects. Ollama has no public port.

Create an embedding job for a ready, extracted, chunked document:

`POST /organizations/{org}/candidates/{candidate}/documents/{document}/embedding-jobs`

The body is `{"retry": false}`. New work returns 202; existing work returns 200.
GET the same path plus `/{job_id}` returns private status and provenance, never
vectors or lease tokens. A job is unique for chunk set, model digest, and encoding.

The durable queue uses SKIP LOCKED, expiring leases, bounded attempts, and fencing.
Complete vectors publish in one transaction. Stale leases, deleted sources, and
obsolete chunk sets cannot publish. Document deletion cascades to its embeddings.
Stop embedding workers before changing model tags. A new model digest needs a
new compatible embedding space and a fresh quality evaluation.

## Search endpoints

| Endpoint | Input |
| --- | --- |
| `POST /organizations/{org}/semantic-search` | q, mode, limit, min_similarity, optional candidate_id/document_id |
| `POST /organizations/{org}/jobs/{job}/semantic-candidate-retrieval` | mode, limit, min_similarity, applicants_only; q comes from the saved job profile |

Mode is semantic or hybrid, limit is 1-50, and min_similarity is 0-1.
Successful responses are private/no-store. Authentication, membership, and all
parent scopes are required. Membership and captured profile revision/timestamp
are rechecked after query encoding.

Only ready documents with succeeded extraction and their latest valid chunk set
are eligible. SQL recomputes text/chunk hashes, offsets, and source slices; it
does not reopen PDF filesystem bytes. Semantic rows require a complete succeeded
job in the same model space. Eligible and embedded coverage counts stay distinct.
Hybrid can return an explicitly lexical-only witness when embedding is absent.

Exact pgvector cosine search uses a 100-result window per branch. Candidate mode
selects one best chunk per candidate per branch before equal-weight RRF with
k=60. Duplicate resumes do not accumulate ranks. Each branch retains its witness.
Cosine and RRF are ranking statistics, not hiring probabilities or proficiency.
The similarity threshold applies only to the semantic branch.

## Verification

`scripts.semantic_retrieval_smoke` covers applicant/tenant scope, incompatible
model spaces, incomplete embeddings, obsolete sources, and profile/membership
changes during encoding. Its live HTTP path now uses a tracked session.
Ordinary CI uses deterministic vectors and does not certify real model quality.

The historical stage 11-B three-case evaluation achieved mean nDCG@1 of 1.0 for
semantic and hybrid. That small result does not establish performance on the
larger stage 4 reference. See [AI quality](ai-quality.md) for current thresholds,
report provenance, and pending native acceptance.

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_run --execute
```

This isolated command preserves the normal stack's model volumes and flags.
