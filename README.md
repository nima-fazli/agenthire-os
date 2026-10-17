# AgentHire OS

Private multi-organization recruiting backend and recruiter workspace, built
with FastAPI, PostgreSQL/pgvector and local Ollama models.

The backend includes scoped jobs/candidates/applications, private PDFs, durable
extraction, immutable chunks, lexical/semantic/hybrid retrieval and exact grounded
quotes. Model scores are retrieval evidence, never a hiring probability.

## Current checkpoint

Backend 0-12, UI 13-A, operations 14-A and 14-B1 are accepted and committed.
Latest user HEAD is 78987f4; 14-B1 feature/test commits are 822c4c2/78987f4.
User Windows passed 1458 tests with 5 known platform skips; Docker passed 1463
without skips; Node 42 and Ruff passed in both environments. All 30 CI checks,
17 smokes and separate cleanup passed. Schema remains 0016_document_embeddings.

14-B2 now adds bounded synthetic recruiting/PDF/worker/retrieval measurements,
serial live-model transport samples, private queue time series and sampled
container memory/CPU. Existing application contracts, models, quotas, feature
flags, UI, migrations and dependencies remain unchanged. New user acceptance
is pending; prior 14-B1 results are not acceptance of this delivery.

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

## Bounded operator measurements

First rebuild the smoke image after installing this slice:

    docker compose --profile smoke build smoke
    uv run --locked --no-sync python -m scripts.resource_watch --samples 15
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.queue_watch --samples 15
    uv run --locked --no-sync python -m scripts.benchmark_run --kind workflow --execute --items 4 --concurrency 2
    uv run --locked --no-sync python -m scripts.benchmark_run --kind models --execute --samples 3

The last two commands explicitly create this run's synthetic workflow records or
invoke the already-installed CPU models. Without --execute they print a plan.
They do not pull a model, enable API flags or restart normal services. The host
supervisor samples existing service containers while its own named smoke
container runs. Reports contain counts/timings/digests, not tokens, document
text, credentials, tenant IDs, container names or raw provider output.
See operations-runbook.md for failure/cleanup boundaries and interpretation.
