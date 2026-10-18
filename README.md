# AgentHire OS

Private multi-organization recruiting backend and recruiter workspace, built
with FastAPI, PostgreSQL/pgvector and locally hosted Ollama models.

The product connects scoped jobs, candidates and applications to private PDF
processing, immutable source chunks, lexical/semantic/hybrid retrieval and
traceable criterion evidence. Hiring decisions remain human. Retrieval scores
are not hiring probabilities, and a resume quotation does not prove proficiency.

## Engineering foundation

- Modular monolith with service-owned authorization and transaction boundaries.
- Tenant-scoped queries and database constraints across related entities.
- Durable extraction/embedding workers with leases, bounded attempts and fencing.
- Versioned source provenance, exact Unicode offsets and local-model contracts.
- Private operational diagnostics and isolated database/document recovery gates.
- A recruiter workspace with safe text rendering and stale-request cancellation.

## Current checkpoint

The accepted baseline is main 66de4967ab8f6c4b1764506d2e5de4f0549dfe12,
through retained private backup/restore stage 15-A3. Its native acceptance
recorded Windows 1672 tests plus 5 known skips, Docker 1677, Node 42, Ruff,
33 CI checks, 18 smokes and owned cleanup. The retained restore matched 20
database rows and 2 PDFs. See verification.md and backups.md under docs.

Stabilization stage 1 is delivered for acceptance. Brief v2 preserves the whole
assigned source chunk, rejects unrelated/partial-token anchors and uses an
independent context-retention quality gate. The recruiter client recognizes
the actual duplicate-email code. Source exports include both CI files and a
hash manifest while excluding private configuration/documents and Git history.
Native Windows/Docker and live v2 model acceptance remain pending.

Schema remains 0016_document_embeddings. Dependencies, model identities,
embedding dimensions/encoding and feature flags retain their existing contracts.
The full recruiting workflow, final bilingual design and public deployment
remain unfinished. See the seven-stage roadmap.

## Verify

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The isolated runner owns generated credentials, volumes and cleanup. Never
delete development volumes to repair a failed check. Keep actual .env, tokens,
private PDFs and personal recovery documents outside Git and delivery archives.

## Distribute source

After reviewing and committing all intended changes:

    uv run --locked --no-sync python -m scripts.source_bundle
    uv run --locked --no-sync python -m scripts.source_bundle --execute

The default is a plan. Export publishes a new ZIP beside the clean checkout;
it never overwrites an existing output. This is not a data or Git-history backup.

## Documentation

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Verification history](docs/verification.md)
- [Stabilization acceptance](docs/stabilization.md)
- [Source distribution](docs/source-distribution.md)
- [Operations](docs/operations.md)
- [Incident runbook](docs/operations-runbook.md)
- [Recovery rehearsal](docs/recovery.md)
- [Retained private backups](docs/backups.md)
- [Retrieval](docs/retrieval.md)
- [Semantic retrieval](docs/semantic.md)
- [Grounded explanations](docs/explanations.md)
- [Recruiter workspace](docs/recruiter-ui.md)
- [Roadmap](docs/roadmap.md)
