# AgentHire OS

Private multi-organization recruiting backend and recruiter workspace, built
with FastAPI, PostgreSQL/pgvector and local Ollama models.

The backend includes scoped jobs/candidates/applications, private PDFs, durable
extraction, immutable chunks, lexical/semantic/hybrid retrieval and exact grounded
quotes. Model scores are retrieval evidence, never a hiring probability.

## Current checkpoint

Backend 0-12, UI 13-A and operations 14-A/14-B1/14-B2 are accepted and committed.
14-B3 native acceptance passed and was committed as 955ac94/c7d66c2. Windows passed 1541 tests
with 5 known platform skips; Docker passed 1546 without skips. Node passed 42 and
Ruff passed in both environments. All 31 CI checks, 18 smokes and separate cleanup
passed. Normal images were rebuilt, four synthetic workflows completed with
scoped cleanup, and both normal/CI schemas remain 0016_document_embeddings with
no drift. Both queues were empty before and after worker-cost observations.

14-B3 reduces worker healthcheck startup imports. Shared local-model URL
validation is independent of SQLAlchemy; extraction defers processing imports,
and embedding defers its asynchronous runtime until normal worker startup.
Heartbeat files, configured age margins, queue polling and model contracts retain
their existing behavior. Median healthcheck CPU fell by 65.6/58.5 percent for the
two extraction replicas and 54.7 percent for embedding in the recorded three-call
samples. These observations do not establish production capacity. Live inference
was not repeated in 14-B3; the accepted local-model samples remain from 14-B2.

15-A1's read-only inventory passed on clean main c7d66c2: PostgreSQL tools/server
18.6, pgvector 0.8.6, two PDFs totalling 138041 bytes and an approximately 10 MB
database. 15-A2 native acceptance passed: Windows 1591 tests with 5 known platform
skips, Docker 1596 without skips, Node 42 and Ruff in both environments. All 32 CI
checks, 18 smokes and separate cleanup passed, including coordinated DB/PDF
recovery into a second fresh synthetic stack. Two tenant PDFs, exact fixture
vectors, authenticated downloads, lexical retrieval and tenant isolation were
verified. The normal stack remained healthy with empty queues. 15-A2 is committed
as ffe34dd/0777895. 15-A3 adds private retained DB/PDF/config capture with original
writer resume, fresh isolated restore and explicit verified retention. Its
native acceptance passed on 2026-10-18: Windows 1672 tests with 5 known platform
skips, Docker 1677 without skips, Node 42 and Ruff in both environments. All
33 CI checks, 18 smokes, both recovery gates and separate cleanup passed. One
private normal-data backup was retained and restored into a fresh isolated
target: 20 database rows and 2 PDFs matched, the target API was ready, cleanup
completed and a restore receipt was created. Original source containers resumed
healthy and both queues were empty. Retention ran as a plan without deletion.
See docs/backups.md for private storage and operational boundaries.

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
- [Recovery rehearsal](docs/recovery.md)
- [Retained private backups](docs/backups.md)
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
