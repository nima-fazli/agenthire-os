# Local semantic indexing

Stage 11-A prepares source-bound embeddings. Semantic/hybrid retrieval and its
quality comparison are stage 11-B; lexical retrieval remains available now.

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
Stage 11-B must measure semantic/hybrid ranking, coverage, latency and regressions
against the existing versioned lexical reference before claiming improvement.

Source references:
- [Qwen model card and license](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Ollama model distribution](https://ollama.com/library/qwen3-embedding:0.6b)
- [Embedding API](https://docs.ollama.com/api/embed)
- [Local-only configuration](https://docs.ollama.com/faq)
