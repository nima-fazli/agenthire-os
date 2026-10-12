# AgentHire OS

A modular recruiting backend built with Python 3.12, FastAPI, async SQLAlchemy,
PostgreSQL 18 and Docker Compose. It implements tenant-scoped recruiting workflows,
private resume processing, lexical retrieval, independent criterion evidence and
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

Retrieval scores measure lexical relevance. Criterion evidence does not verify a
skill or determine hiring suitability. Embeddings, LLM explanations, agents and
the frontend remain future work.

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
schema drift and runs all ten real-stack smoke modules. It generates temporary
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

The last user-verified baseline before the CI stage is main `62da13a`: all 998
Docker tests passed, Alembic head `0014_create_job_match_profiles` had no drift,
and the real-stack synthetic evaluation passed. This records a baseline, not a
production deployment or a hosted CI result.
