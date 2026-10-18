# Grounded local evidence briefs

POST /organizations/{org}/jobs/{job}/candidates/{candidate}/grounded-explanation
accepts only a presentation language, fa or en; the default remains fa.
The endpoint requires authentication, membership, scoped parents and a saved
match profile. Success is private/no-store. Sources and criteria are server-owned.

## Version 2 citation contract

explanation_version is extractive-brief-v2, prompt_version is
local-quote-selection-v2 and citation_policy is assigned-chunk-context-v1.

The local model selects one exact contiguous anchor per witnessed criterion.
The anchor must contain all complete lexical query terms, occur in the assigned
source and not cut a source token. English case, Unicode compatibility forms
and the specified Persian/Arabic variants are folded only for relevance checks.
The original source text is never rewritten. This guard does not replace or
modify PostgreSQL's frozen simple-fold-v1 search normalization.

The server returns the entire original assigned chunk as citation.quote, not
the short anchor. Its absolute Unicode code-point start/end offsets and SHA-256
cover that full chunk. Negation and qualifications before or after the anchor
therefore remain visible. Multiple criteria may cite the same full context.
The model anchor remains limited to 400 characters; context is bounded by the
existing maximum chunk size of 4000 characters and the 6000-byte prompt budget.

This is a source quotation, not a semantic entailment check or a proficiency
assessment. Information outside the assigned chunk is not reconstructed.
No evidence means no current searchable witness, not absence of a skill.
Scores are retrieval relevance, never hiring probability.

## Grounding and lifecycle

The server writes summaries and missing-evidence states. Free model prose,
tools, hiring recommendations and suitability scores are not accepted.
Exact source hashes, slice identity, parent scope, membership, profile revision
and newest source are verified before/after generation. Changed snapshots are
discarded. PDF filesystem bytes are not reread by the citation SQL checks.
Generated text is not stored. Read sessions close around model work.

Invalid/invented/unrelated model output fails closed. Revoked access is 404,
changed evidence is 409, oversized input is 422 and model/grounding failures
use safe 503 codes. There is no automatic repair, retry or provider fallback.
An all-missing-evidence result needs no model call and claims no token usage.

## Local runtime and privacy

AGENTHIRE_EXPLANATIONS_ENABLED remains false by default. qwen3:0.6b uses the
existing directly local Ollama HTTP transport; inventory digest is pinned and
rechecked. CPU-only, nonstreaming, think=false, num_ctx=8192, num_predict=1024
and keep_alive=0 remain unchanged. No dependency or migration is added.

Prompts contain untrusted source text, which may contain personal information.
Omitting identity metadata does not anonymize it. Prompt size is bounded without
silent slicing. Duplicate JSON keys, nonfinite values, extra fields and truncated
model output remain rejected. One API-process transport slot remains occupied
until its worker thread ends, including after caller cancellation/timeouts.
This is not distributed rate limiting. Model contention still needs measurement.

## Evaluation and acceptance

grounded_explanations_v2.json is a new nine-case synthetic reference. It includes
English/Persian negation, qualifications in a later sentence, multiple terms,
punctuated terms, hostile instructions and no documents. The independent
grounded-quality-v2 evaluator expects the complete literal fixture context,
offsets and hashes; it does not call the production anchor validator.
Reports contain case outcomes/timings/provenance, not private source text.

Existing isolated CI uses a deterministic generator against real PostgreSQL;
it does not download or invoke a model. Live inference is opt-in through the
existing scripts.grounded_explanations_smoke --live-model operator workflow.
Lifecycle mutation checks and owned cleanup remain mandatory.

Stage 12's accepted v1 CPU samples on 2026-10-13 took roughly 10-19 seconds
for the three generated cases. Those historical samples and the old four-case
fixture do not certify v2. Native/live v2 acceptance is pending. Wider corpus,
fairness, concurrent capacity and latency-percentile evidence remain future work.
Schema remains 0016_document_embeddings. See stabilization.md and verification.md.
