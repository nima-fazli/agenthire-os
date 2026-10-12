# Retrieval and evidence

## Current contracts

| Capability | Version | Behavior |
| --- | --- | --- |
| Document search | simple-fold-v1 | Literal normalized PostgreSQL all-term search |
| Candidate retrieval | best-chunk-v1 | One best ready/latest resume chunk per candidate |
| Criterion evidence | criterion-evidence-v1 | Independent best witness for each job criterion |
| Chunking | char-window-v1 | Exact Unicode character slices, default 1200/150 overlap |
| Quality evaluation | retrieval-quality-v1 | Versioned reference suite and observation provenance |

The frozen SQL normalization function folds common Persian/Arabic variants,
half-spaces and marks while preserving original source text. Search uses
`plainto_tsquery('simple', ...)`, not user-supplied query syntax. All surviving words
in one query must occur within the same chunk. New normalization requires a new
version/function/index, not changing the immutable v1 function.

Only ready documents, succeeded extractions and each document's newest chunk set
are searchable. Counts and pages use one snapshot. Tenant and membership predicates
remain in repository SQL. Search/retrieval/evidence enforce transaction-local
statement timeouts and safe rollback/reset on cancellation.

## Job profiles

Search profiles contain an explicit query. Match profiles contain 1–10 ordered
criteria with key, label, query and required/preferred importance. Identical retries
preserve revisions; changed definitions advance the current revision. These are
current definitions, not an immutable historical profile archive.

Different criteria may use different chunks/documents. Duplicate resumes do not
inflate criterion counts or sum relevance ranks. Source coverage is reported as
no_documents, not_indexed, partial or indexed. Missing lexical evidence does not
prove absence of a skill, and a found word does not prove proficiency.

## Reference evaluation

The synthetic suite contains eight candidate keys, five ranking cases and seven
evidence cases with five criteria each. Suite/corpus SHA values bind the reference,
PDF fixtures, source states, criteria, queries and thresholds. Reports record actual
backend versions and chunk policy, avoiding raw source text/identities/tokens.

Precision@k uses denominator k; recall uses all relevant reference candidates.
nDCG uses graded exponential gains; reciprocal rank is truncated at k. Positive
reference queries are macro-averaged. Expected-empty queries have undefined
recall/nDCG/RR, are counted separately and must return no candidates.

Forbidden/unjudged results, provenance/readiness mismatches and failed configured
quality thresholds fail the gate. Evidence metrics use exact TP/FP/FN/TN labels.
Malformed/stale observations are input errors, not low scores to average away.

```powershell
uv run --locked --no-sync python -m scripts.retrieval_evaluation --example
```

This is an example, not a real backend run. The tenth Docker smoke collects actual
API observations and requires `source_kind: real_stack` and `gate_passed: true`.

The verified baseline has mean precision/recall 0.875, nDCG 0.9032867981913646 and
MRR 1.0. All 35 evidence labels match. The combined Python/SQL case retrieves only
one of two reference resumes (recall 0.5), exposing the one-chunk lexical limit.
These are synthetic measurements. The Persian database fixture does not test OCR
or Persian PDF extraction. Semantic retrieval must beat a versioned baseline with
the same tenant/provenance constraints before replacing current behavior.
