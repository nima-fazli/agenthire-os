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

Retrieval scores measure relevance, not proficiency or hiring suitability.
LLM explanations, agents and the frontend remain future work.

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
schema drift and runs all thirteen real-stack smoke modules. It generates temporary
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

The latest committed baseline is main `242ccae`: stage 11-A, schema
`0016_document_embeddings`, local CPU model and healthy embedding worker accepted.
Stage 11-B semantic/hybrid retrieval passed Windows tests, 1241 Docker tests,
all thirteen real-stack smoke modules and the live CPU model comparison. Its
two scoped commits remain pending. The small synthetic comparison is not a
production quality or capacity benchmark. Hosted GitHub Actions and production
deployment remain unverified. No paid AI provider is required.
