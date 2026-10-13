# AgentHire OS

A modular recruiting backend built with Python 3.12, FastAPI, async SQLAlchemy,
PostgreSQL 18 and Docker Compose. It implements tenant-scoped recruiting workflows,
private resume processing, lexical/semantic retrieval, independent criterion evidence and
versioned quality evaluation.

## Implemented

- Global users, bearer authentication, organizations and memberships.
- Organization-scoped jobs, candidates and applications.
- Application transitions, terminal states and idempotent retries.
- Private PDF upload/download/deletion with candidate-level deduplication.
- Durable extraction queue with two worker replicas, leases and stale-result fencing.
- Immutable source chunks with original text, offsets and SHA-256 provenance.
- PostgreSQL full-text search and one best resume witness per candidate.
- Explicit job search/match profiles with independent required/preferred criteria.
- Reproducible synthetic reference evaluation with quality gates.
- Application tenant consistency enforced in PostgreSQL after a migration audit.
- Private operator reconciliation with a dry-run default and guarded scoped cleanup.
- Opt-in local CPU embedding jobs with model/source versioning and atomic pgvector storage.
- Opt-in exact cosine search and bounded reciprocal-rank fusion with separate source witnesses.
- Opt-in local extractive evidence briefs with exact quotes and deterministic bilingual summaries.

Retrieval scores measure relevance, not proficiency or hiring suitability.
The recruiter frontend and release operations are the next delivery stages.

## Verify

Install Python 3.12, uv and Docker Desktop with Linux containers. Docker Compose
2.24.4 or newer is required for the isolated verification override.

From the repository root:

```powershell
uv sync --locked --no-install-project
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pytest -rs
uv run --locked --no-sync python -m scripts.ci_verify
```

The last command builds a separate temporary stack, applies migrations, checks
schema drift and runs all fourteen real-stack smoke modules. It generates temporary
test credentials, publishes no API port and cleans its own containers, networks
and volumes. It uses the existing Docker context and retains build images/cache.

Inspect its plan without running Docker:

```powershell
uv run --locked --no-sync python -m scripts.ci_verify --dry-run
```

The GitHub Actions workflow runs native Linux/Windows tests first, then this same
Docker verification on Ubuntu. A real workflow run must still be observed before
claiming hosted CI is verified.

## Documentation

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Verification and troubleshooting](docs/verification.md)
- [Retrieval and evaluation contracts](docs/retrieval.md)
- [Roadmap and delivery gates](docs/roadmap.md)
- [Free local embeddings and activation](docs/semantic.md)
- [Grounded local evidence briefs](docs/explanations.md)

The latest committed baseline is main `38e60af`: stage 11-B, schema
`0016_document_embeddings`, 1241 Docker tests, thirteen smoke modules and the
real CPU semantic comparison accepted. Its feature/test commits are `2ffc3a2`
and `38e60af`. Stage 12 adds a grounded local quote extractor and the fourteenth
smoke. Its technical acceptance passed on 2026-10-13: Windows 1306 passed / 5
platform skips, Docker 1311 passed, all 24 isolated checks and cleanup passed,
and the real CPU grounding gate and private authenticated HTTP passed. Both
stacks had no schema drift; all six normal-stack services ended healthy.
Stage 12's two scoped commits remain pending. The Persian explanation sample
took 13.81 seconds. Synthetic references and single timing samples are not
production quality or capacity benchmarks. Hosted GitHub Actions and production
deployment remain unverified. No paid AI provider is required.
