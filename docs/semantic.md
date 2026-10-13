# Local semantic indexing

Stage 11-A provides accepted source-bound embeddings. Stage 11-B provides optional
semantic/hybrid retrieval, verified on real PostgreSQL and the local CPU model.
The existing lexical endpoints retain their contracts.

## Free local runtime

The selected model is qwen3-embedding:0.6b (Apache-2.0), served by local Ollama
0.40.3 (MIT). No cloud model, account, API key or paid inference is required.
Compose publishes no Ollama port and sets OLLAMA_NO_CLOUD=1. The application
accepts only explicit local endpoints, bypasses HTTP proxies and refuses redirects.
Only the initial public image/model downloads require Internet access.

The CPU profile uses one Ollama request at a time, a 3 GiB memory limit, two CPUs,
an 8192-token context and batches of four chunks. This is a starting configuration
for an 8-16 GiB machine; actual latency and peak memory require local measurement.
Inputs are never silently truncated. A context overflow fails the job safely.

## Contracts and lifecycle

- Feature flag: AGENTHIRE_SEMANTIC_ENABLED, false by default.
- Model tag: qwen3-embedding:0.6b; full digest resolved from the local model inventory.
- Encoding version: qwen3-raw-l2-v1; raw passage text, 1024 finite L2-normalized values.
- POST /organizations/{org}/candidates/{candidate}/documents/{document}/embedding-jobs
  accepts only {"retry": false}; new work returns 202, existing work returns 200.
- GET the same path plus /{job_id} returns private status/provenance, never vectors
  or lease tokens. Authentication, membership and every parent scope are required.
- Extraction and immutable chunks must already exist. One job is unique for each
  chunk set, model digest and encoding version. A model change creates a new space.

The durable queue uses SKIP LOCKED, bounded attempts, expiring leases and a fresh
token on every claim. Each batch verifies the model digest before/after inference
and renews its lease. Complete vectors publish in one transaction. Expired tokens,
deleted sources and obsolete chunk sets cannot publish. Cancellation leaves work
recoverable through lease expiry. No partial vectors become searchable.

PostgreSQL enforces fixed dimensions, approximately unit length and composite
job/source/chunk relationships. Document deletion cascades through all embedding
jobs and vectors. Historical model/source versions are retained until their source
is deleted; automatic retention and approximate-neighbor indexes are future work.
Stop embedding workers before replacing local model tags. Model upgrades require
an explicit new digest and a fresh quality check; tag mutation is an operator action.

## Verification and activation

First run ordinary unit/Ruff checks and scripts.ci_verify. Its twelfth smoke uses
deterministic vectors only for its own synthetic tenant and exact job IDs. It tests
the real database pipeline, vector transport, constraints, lease fences and cascade.
It never processes another tenant's queue. This is not a real-model quality test.

Then enable the optional local profile in PowerShell:

```powershell
$env:AGENTHIRE_SEMANTIC_ENABLED = "true"
docker compose --profile semantic up -d --wait ollama
docker compose --profile semantic exec -T ollama ollama pull qwen3-embedding:0.6b
docker compose --profile semantic --profile smoke build api migrate extraction-worker smoke embedding-worker
docker compose --profile semantic up -d --no-build --wait --scale extraction-worker=2 api extraction-worker
docker compose --profile semantic --profile smoke run --rm smoke python -m scripts.document_embeddings_smoke --live-model
docker compose --profile semantic up -d --no-build --wait --scale extraction-worker=2 api extraction-worker embedding-worker
```

Run the live smoke before starting an embedding worker. It uses only synthetic
passages, calls the real CPU model and checks basic Persian/English ordering. Its
tiny fixture establishes compatibility, not population-level retrieval quality.
The thirteenth CI smoke compares lexical, semantic and hybrid candidate ranking
on a separate versioned synthetic reference and records per-call elapsed time.
Fixture encoders prove DB behavior; only --live-model evaluates the real encoder.
The tiny reference and timing samples are not a production benchmark.

Source references:
- [Qwen model card and license](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Ollama model distribution](https://ollama.com/library/qwen3-embedding:0.6b)
- [Embedding API](https://docs.ollama.com/api/embed)
- [Local-only configuration](https://docs.ollama.com/faq)

## Stage 11-B retrieval contracts

POST /organizations/{org}/semantic-search accepts q, mode (semantic/hybrid),
limit (1-50), min_similarity (0-1) and optional candidate_id/document_id.
POST /organizations/{org}/jobs/{job}/semantic-candidate-retrieval accepts mode,
limit, min_similarity and applicants_only; its query comes from the saved job
search profile. Query text, model choice and profile revision are server-owned
for that job endpoint. Successful responses are private/no-store.

Only ready sources with succeeded extraction and the newest chunk set qualify.
Stored PDF provenance, recomputed text/chunk hashes, offsets and exact slices
are checked in SQL; this query does not read filesystem bytes. Semantic rows
require a complete succeeded embedding job matching model digest and encoding.
Coverage counts distinguish eligible and embedded chunks. Empty embeddings are
not treated as an empty corpus; hybrid may return explicitly lexical-only evidence.

Exact cosine search uses pgvector <=> and a bounded 100-result branch window.
The similarity threshold applies to the semantic branch only. Candidate mode
selects one best chunk per candidate per branch before fusion: duplicate resumes
do not accumulate ranks. Equal-weight RRF uses k=60 and divides by 2/61. The score
is a ranking statistic; cosine and RRF are not interchangeable probabilities.
Each branch keeps its own source witness. Chunk mode keeps distinct chunks.

There is no offset pagination or claim that the bounded pool is the full corpus.
The response includes branch_window, pool_truncated, pooled_count and coverage.
Model failures/disabled processing return 503; lexical fallback is an explicit
caller choice using the existing lexical API. Query encoding has a whole-operation
deadline; SQL has a transaction-local deadline. Read transactions close before
encoding and after retrieval. Membership, job ownership and captured profile
revision/timestamp are rechecked in the same result statement.

After copying stage 11-B files, run native tests and scripts.ci_verify. Enable the
semantic profile, rebuild api/smoke with the new source, then run:

```powershell
docker compose --profile semantic --profile smoke run --rm smoke python -m scripts.semantic_retrieval_smoke --live-model
```

The smoke creates only random-ID synthetic sources and succeeded vector rows;
it never consumes queued jobs or processes another tenant's documents. It also
checks authenticated HTTP when live, applicant/tenant scope, partial/mixed spaces,
obsolete/deleting sources and membership/profile changes during encoding. Fixture
cleanup runs in finally. Schema stays at 0016; no new package or paid service.

## Recorded stage 11-B acceptance

On 2026-10-13, Windows ran 1236 passed / 5 known platform skips; Docker ran
1241 passed. Ruff, all 23 isolated checks, 13 smoke modules and cleanup passed.
The normal stack remained healthy, including the restored embedding worker.
Both stacks reported 0016_document_embeddings with no migration drift.

The fixture and live runs used the same synthetic-reference SHA-256:
f0b3ced7daecd80a2d702f5d0bf46c7a871c3a46cc09973d1c2551d2ff819178.
The live model digest was:
ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d.

Mean nDCG@1 was 0.333333 for lexical, 1.0 for semantic and 1.0 for hybrid.
Semantic/hybrid ranked the relevant candidate first for all three reference cases.
The live run also passed authenticated HTTP, source/model eligibility, tenant and
applicant scope, profile/membership race checks and synthetic fixture cleanup.

| Live query case | Lexical ms | Semantic ms | Hybrid ms |
| --- | --- | --- | --- |
| Literal | 35.99 | 647.44 | 466.19 |
| English paraphrase | 10.19 | 693.95 | 606.52 |
| Persian | 32.17 | 2718.23 | 3821.88 |

These are single service-call samples on a tiny synthetic corpus, not latency
percentiles or production throughput. Persian inference took longer in this run.
Broader corpus evaluation and load testing remain release work. Technical
acceptance and commits are complete: feature 2ffc3a2, tests 38e60af.

Stage 12 adds optional grounded briefs using qwen3:0.6b in the same Ollama runtime;
see [explanation contracts and recorded acceptance](explanations.md). Native,
Docker and real CPU explanation gates passed on 2026-10-13; scoped commits remain
pending. The embedding worker was restored and healthy after the live measurement.
Ollama keeps one model loaded, so generation and embedding share capacity and
model switching. The semantic endpoints and encoding contracts stay unchanged.
