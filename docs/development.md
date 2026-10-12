# Development

Use Python 3.12 and the checked-in uv lock. Do not edit `uv.lock` manually, rewrite
applied migrations or add infrastructure without a demonstrated need.

## Local checks

From the repository root in PowerShell:

```powershell
& {
    uv sync --locked --no-install-project
    if ($LASTEXITCODE -ne 0) { throw "Dependency sync failed." }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw "Whitespace check failed." }
    uv run --locked --no-sync ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }
    uv run --locked --no-sync pytest -rs
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
}
```

Unit tests use temporary/mocked persistence where appropriate. Real PostgreSQL
locking, expression indexes, lease races and cancellation require Docker smokes.
Known native Windows capability skips are acceptable; inspect `pytest -rs` rather
than assuming all skipped tests are failures.

## Existing development stack

For initial development only, copy `.env.example` to `.env` and configure local
values. Keep an existing `.env` intact. Never commit or paste actual secrets.

```powershell
docker compose up -d --build --wait --scale extraction-worker=2 api extraction-worker
docker compose ps
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic check
```

The standard API is at `http://localhost:8000`. PostgreSQL is reached by services
inside Compose. `.env.example`'s host port does not publish PostgreSQL by itself.
Use the provided Docker smoke modules for integration acceptance.

## Independent full verification

```powershell
uv run --locked --no-sync python -m scripts.ci_verify
```

This creates a new randomly named `agenthire-ci-*` project. Its Compose override
replaces service env files, uses separate image/volume names and removes the host
API port. Your standard stack can remain running. Temporary credentials disappear
after execution. First failure stops later checks; cleanup still runs.

An occupied generated namespace is rejected before any build/start/cleanup. Do not
manually change the runner to use the standard project name or a shared volume.

## Delivery discipline

Keep route/service/repository boundaries. Provide full changed files, meaningful
tests and focused feature/test commits. Review migrations manually and confirm
real-stack head/drift. Fix a new failure before progressing to another feature.
Keep current state, actual user commit hashes and pending checks in the recovery
document; do not substitute review-copy hashes for the user's Git history.
