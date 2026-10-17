# AgentHire OS

Tenant-scoped recruiting, private PDFs and free local CPU models. Backend stages
through 12 and the stage 13-A recruiter workspace are committed. The latest
observed user checkpoint is main 92c23fd, following b604ec6, with a clean tree.

/workspace/ supports accounts, organizations/jobs, profiles, candidates,
retrieval, source evidence and private PDF processing. The current Persian UI
is preserved. Stage 13-B and the final English-first bilingual design are
deferred until the user requests frontend work.

Stage 14-A adds /ready, server-generated request IDs, safe structured HTTP
events, bounded container logs and local operator diagnostics. /health retains
its existing liveness contract. No migration, dependency or model changes.
New Docker/PostgreSQL acceptance is pending execution on the user's machine.

## Check

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The current isolated plan has 27 checks, including 16 smokes, plus separate
cleanup. Historical accepted 13-A results were Windows Python 1347 passed / 5
platform skips, Docker Python 1352 passed, Node 42 passed and all 26 former CI
checks passed. Alembic was at 0016_document_embeddings with no drift.
These historical results do not establish acceptance of the new stage.

See [Operations](docs/operations.md), [Verification](docs/verification.md),
[Recruiter workspace](docs/recruiter-ui.md) and [Roadmap](docs/roadmap.md).
The personal recovery document stays outside Git.
