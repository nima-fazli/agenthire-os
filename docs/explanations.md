# Grounded local evidence briefs

`POST /organizations/{org}/jobs/{job}/candidates/{candidate}/grounded-explanation`
accepts a presentation language. English (`en`) is the default and the workspace
always requests English. Explicit `fa` requests remain a legacy API capability;
there is no Farsi workspace mode. Source quotations retain their original text.

A tracked session, membership, scoped parents, and a saved criterion profile are
required. Successful responses are private/no-store. The model selects source
anchors; it does not decide suitability or recommend hiring.

## Version 2 citation contract

| Contract | Value |
| --- | --- |
| explanation_version | extractive-brief-v2 |
| prompt_version | local-quote-selection-v2 |
| citation_policy | assigned-chunk-context-v1 |
| matching_version | criterion-evidence-v1 |

For each witnessed criterion, the model selects an exact contiguous anchor of at
most 400 characters from its assigned source. All complete query terms must be
present. The original source text is never rewritten.

The server retains the entire assigned chunk as citation.quote, including any
negation or qualification before/after the anchor. Offsets use Unicode code
points. Hashes identify the full quote, chunk, source text, and source document.
The maximum chunk size remains 4000 characters and the prompt budget remains
6000 UTF-8 bytes. Text is not silently sliced to fit.

This is not a semantic entailment or proficiency test. Context outside the
assigned chunk is not reconstructed. No evidence means no current searchable
witness. The server writes summary and missing-evidence prose; free model prose,
tools, and hiring recommendations are not accepted.

## Validation and failure behavior

Hashes, slices, parents, membership, profile revision, and latest source are
verified before/after inference. Changed snapshots are discarded. Citation SQL
does not reopen PDF filesystem bytes. Generated text is not persisted, and read
transactions are closed around model work.

| Condition | Result |
| --- | --- |
| No evidence | No model call and no claimed token usage |
| Missing access or candidate | 404 |
| Snapshot changed | 409 |
| Input exceeds prompt budget | 422 |
| Invalid/ungrounded output or provider failure | 503 with a safe code |

There is no automatic output repair, retry, or provider fallback. Duplicate JSON
keys, nonfinite numbers, extra fields, and truncated outputs remain rejected.

## Local runtime and evaluation

`AGENTHIRE_EXPLANATIONS_ENABLED` remains false by default. The existing
`qwen3:0.6b` runtime is CPU-only with think=false, num_ctx=8192, num_predict=1024,
temperature=0, seed=17, and keep_alive=0. Digest identity is checked before/after.
The process-local transport lock remains held until the model thread finishes,
including when a waiting request is cancelled. It is not distributed rate limiting.

Resume text may contain personal information. Excluding identity metadata does
not anonymize the source. Keep the local model endpoint private.

The older nine-case v2 reference and lifecycle mutation tests remain. Their live
session path is compatible with stage 3. Historical v1 measurements do not
certify v2. The broader reference and independent evaluator are documented in
[AI quality](ai-quality.md). Native live acceptance is still pending.
Schema remains `0017_access_sessions`; stage 4 adds no migration.
