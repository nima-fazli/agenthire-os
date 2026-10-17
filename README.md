# AgentHire OS

Private multi-organization recruiting backend and recruiter workspace, built
with FastAPI, PostgreSQL/pgvector and local Ollama models.

The backend includes scoped jobs/candidates/applications, private PDFs, durable
extraction, immutable chunks, lexical/semantic/hybrid retrieval and exact grounded
quotes. Model scores are retrieval evidence, never a hiring probability.

## Current checkpoint

Backend stages 0-12 and UI 13-A are committed through main 92c23fd.
The latest supplied 14-A terminal passed Windows Python 1386 + 5 platform skips,
Docker Python 1391, Node 42, Ruff, 27 isolated checks and separate cleanup.
Normal-stack schema was 0016_document_embeddings without drift. Its two commit
hashes have not been supplied; commit accepted 14-A before copying 14-B1 files.

14-B1 adds private queue limits, aggregate Compose inventory, bounded local HTTP
latency probes and real PostgreSQL timeout/read-only rollback exercises. Its CI
plan has 30 checks, 17 smokes and separate cleanup, including explicit checks of
both extraction workers. New user Docker acceptance and commits remain pending.

## Verify

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify

The isolated runner owns separate generated credentials and volumes. Never use
development-volume deletion to repair a failed check. Keep .env and private PDFs
out of Git and delivery archives. Personal recovery documents stay outside Git.

## Documentation

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Verification](docs/verification.md)
- [Operations](docs/operations.md)
- [Incident runbook](docs/operations-runbook.md)
- [Retrieval](docs/retrieval.md)
- [Semantic retrieval](docs/semantic.md)
- [Grounded explanations](docs/explanations.md)
- [Recruiter workspace](docs/recruiter-ui.md)
- [Roadmap](docs/roadmap.md)
