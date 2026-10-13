# Grounded local evidence briefs

Stage 12 adds an optional extractive brief for one candidate and a saved job match
profile. Native, Docker and real CPU model acceptance passed on 2026-10-13;
the two scoped commits are pending.
It uses qwen3:0.6b (Apache-2.0) through the existing local Ollama 0.40.3 runtime.
No paid provider, account, API key, SDK dependency or new migration is required.

## API and meaning

POST /organizations/{org}/jobs/{job}/candidates/{candidate}/grounded-explanation
accepts only {"language":"fa"} or {"language":"en"}; Persian is the default.
Authentication, membership, job/candidate ownership and a saved match profile are
required. Success is private/no-store. The profile and evidence remain server-owned.

The existing criterion-evidence-v1 lexical reader selects witnesses. The model
selects exact contiguous quotes from those witnesses. Server code writes the
bilingual summary, missing-evidence states and explanatory sentences. Arbitrary
model prose, tools, hiring recommendations or suitability scores are not accepted.
This is an extractive explanation feature, not an open-ended chat assistant.

Every found criterion requires one quote from its assigned source. Missing criteria
cannot gain citations. The exact quote, character offsets, document/chunk identity
and hashes are returned alongside the full original witness text. Offsets count
Unicode code points in the original extraction. Quoting does
not establish proficiency or the truth of a resume statement; negation and wider
context remain available in the witness. No evidence means no current searchable
witness, not evidence of absence of a skill.

## Grounding and lifecycle

Before generation, SQL verifies the selected ready documents, succeeded extraction,
newest chunk sets, stored PDF provenance, recomputed text/chunk hashes and exact
slices. This endpoint does not reread filesystem PDF bytes. After generation,
the evidence snapshot is read again. Changed profile/criteria, source selection,
coverage or candidate metadata discard the result. A final SQL statement rechecks
membership, parent ownership, profile/criteria and cited sources, and requires
the quote itself to match the criterion's frozen lexical query.

No generated text is persisted. Read transactions close before model work and
after response assembly. Database work uses transaction-local statement_timeout.
Revoked access returns 404; changed evidence returns 409. Model, malformed output,
fabricated quotes, digest changes and capacity failures return safe 503 errors.
An oversized prompt returns 422/EXPLANATION_INPUT_TOO_LARGE. There is no automatic
repair, second inference attempt or silent provider fallback. If every criterion
lacks evidence, an explicit missing-evidence brief needs no model call and reports
null model tag/digest and zero token usage.

## Runtime limits and privacy

AGENTHIRE_EXPLANATIONS_ENABLED is false by default and independent of the embedding
flag. AGENTHIRE_CHAT_BASE_URL permits only direct local HTTP port 11434 endpoints.
Proxies and redirects are disabled. Model inventory digest is captured and checked
after generation; stop work before model-tag changes. Generation is CPU-only,
nonstreaming, think=false, num_ctx=8192, num_predict=1024 and keep_alive=0.

The prompt contains criterion keys/queries and deduplicated full witness text.
Candidate identity metadata, UUIDs and filenames are omitted; the original witness
text can still contain personal information. Sources are untrusted JSON data.
The UTF-8 prompt budget is 6000 bytes including instructions and schema. Oversized
inputs are rejected without slicing. JSON duplicate keys/nonfinite numbers, extra
fields, truncated completion and unexpected reasoning/tool output are rejected.
Fixed sampling settings do not promise bitwise identical outputs across runtimes.

Each API process permits one chat transport at a time and rejects concurrent
requests as busy. Cancellation/deadline keeps capacity occupied until the worker
thread finishes; no prompt or result is logged by this feature. This is not a
distributed rate limiter. Ollama also shares one inference/model slot with the
embedding worker, so model switching and contention require local measurement.

## Acceptance

The four-case synthetic reference covers English, Persian, hostile source commands
and no documents. CI uses a deterministic generator on real PostgreSQL; it does
not require Ollama or download a model. The fourteenth smoke checks exact citations,
missing evidence and tenant scope. Deterministic mutations test profile, deleting,
newest-source and membership changes after generation, plus source hash corruption.
These database mutations use a fixture generator even during the live run; they
verify repeatable lifecycle fences rather than races timed against real inference.

After native tests and scripts.ci_verify, enable explanations, rebuild API/smoke,
pull qwen3:0.6b once inside the existing Ollama container, pause the embedding worker
for measurement, and run scripts.grounded_explanations_smoke --live-model. Restore
the worker in finally. The live gate requires ordinary English/Persian extraction
and private authenticated HTTP; hostile input must remain grounded or be rejected
by the output guard. Only random-ID fixture metadata is created/cleaned.

The report records reference hash, actual model digest, fixture/live provenance,
case outcomes and elapsed service-call samples without source text. It is not a
production accuracy, fairness, capacity or latency-percentile benchmark.
Schema remains 0016_document_embeddings. Hosted Actions/deployment are unverified.

## Recorded stage 12 acceptance

On 2026-10-13, Windows ran 1306 passed / 5 known platform skips in 30.71 seconds.
Docker ran 1311 passed without skips in 32.13 seconds. Native/Docker Ruff, all
24 isolated checks, 14 smoke modules and the separate cleanup passed. The CI
and normal stacks reported 0016_document_embeddings with no migration drift.

Both grounded-quality-v1 reports used this synthetic-reference SHA-256:
710f8d10077db2bb381a85a2b978537d6d6675aefdc98f9ab39005d2ac7c212a.
The CI report used a deterministic fixture generator. The live report used
qwen3:0.6b on CPU with this actual model digest:
7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435.

| Live service case | Result | Elapsed ms |
| --- | --- | --- |
| English | ok | 18984.53 |
| Persian | ok | 13812.31 |
| Hostile source commands | ok | 10490.15 |
| No documents | ok; no model call | 46.97 |

Both gates passed with no reported issues or failures. The live smoke also
passed authenticated private HTTP, tenant scope, the deterministic database
mutation checks, recomputed source hashes and cleanup of its own fixture metadata.
The embedding worker was restored; API, both extraction workers, embedding worker,
Ollama and PostgreSQL were healthy at the final observation.

These are single service-call samples from four synthetic cases. Wider quality,
concurrent load, peak memory and latency percentiles remain unmeasured. Generation
took roughly 10-19 seconds in these samples; the recruiter UI needs explicit
loading/cancellation behavior. Restart counts were not measured by this run.
Technical acceptance is complete; feature/test commit hashes are not yet recorded.

Primary sources:
- https://ollama.com/library/qwen3:0.6b
- https://huggingface.co/Qwen/Qwen3-0.6B
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/capabilities/structured-outputs
