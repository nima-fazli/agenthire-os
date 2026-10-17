# Verification

## Observed 14-A baseline

Latest supplied user terminal, after the committed 13-A main 92c23fd:

| Check | Observed result |
| --- | --- |
| Windows Python with warnings as errors | 1386 passed, 5 platform skips |
| Docker Python | 1391 passed, no skips |
| Node / Ruff | 42 passed / passed on both platforms |
| Isolated runner | 27 checks and separate cleanup exited zero |
| Normal stack | API/PostgreSQL/two extraction workers healthy |
| Alembic current/check | 0016_document_embeddings / no drift |
| operations_smoke | Passed in isolated and normal stacks |
| Commits | 14-A hashes not supplied; last observed HEAD remains 92c23fd |

Do not reuse the 14-A result as acceptance of the new 14-B1 code. Commit the
accepted 14-A files before replacing files with this delivery.

## 14-B1 acceptance

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The plan has 30 checks and separate cleanup: the previous 16 smokes, the new
operations_failure_smoke and two indexed extraction-worker healthchecks.
Record actual platform-specific counts and exits. Rebuild/start the normal
API/migrate/extraction-worker images, keep two extraction workers, check schema,
run both operations smokes and private diagnostics. On the host run
stack_diagnostics and operations_probe. Queue thresholds are explicit operator
policies and can fail independently of core readiness.

The runner retains isolated credentials/volumes, first-failure authority and
unconditional owned cleanup. Operations helper files and UI assets must exist
before Docker starts. No deployment, model download, UI change or migration is
part of this slice. Known Windows platform skips still run in Docker/Linux.

## Evidence boundaries

Local unit tests and socket-server failure tests do not replace real PostgreSQL
smokes. CI embeddings/chat still use deterministic fixtures. A small readiness
sample includes its cache and does not prove realistic load or live-model
quality. Compose health and worker heartbeat do not prove throughput. Hosted
Actions, broad browser QA, production deployment and coordinated restore remain
unverified. See operations.md and operations-runbook.md for exact limits.
