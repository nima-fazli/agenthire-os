# Verification

## Accepted 14-B1 baseline

User main 78987f4 is clean. Feature/test commits 822c4c2/78987f4 follow accepted
14-A 31b7730/f8286de. The final user output recorded:

| Check | Actual result |
| --- | --- |
|Windows Python with -W error|1458 passed, 5 known platform skips|
|Docker Python|1463 passed, no skips|
|Node/Ruff|42 passed/Ruff passed on both platforms|
|Isolated CI|30 checks, 17 smokes and separate cleanup, all exit 0|
|Normal stack|API/PostgreSQL/two extraction workers healthy|
|Schema|0016_document_embeddings; no drift in either stack|
|Readiness sample|20/20 successful; host p95=109ms; not a capacity result|

Do not reuse these results as acceptance of 14-B2.

## Assistant checks for this delivery

Linux Python passed 1530 tests with warnings treated as errors; Node passed 42
tests and Ruff passed. The full collection also enforced the Windows 32767-character
environment-value bound; the maximum PYTEST_CURRENT_TEST value was 5284 characters.
This is not native Windows, Docker, PostgreSQL or live Ollama acceptance.

## Current 14-B2 acceptance

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The isolated plan has 31 checks, 18 smokes and separate owned cleanup. New
workload_smoke performs two concurrent synthetic workflows through real HTTP,
PDF conversion, workers, chunks, lexical retrieval and scoped cleanup. All prior
operations/storage/provenance gates and both indexed worker healthchecks remain.
It does not call a live model. Unit mocks are not acceptance of that smoke.

Rebuild the normal smoke image and run workload_smoke there, then resource_watch,
queue_watch and benchmark_run for workflow/models as documented in the runbook.
The existing normal API/extraction image and schema do not change in this slice.
Models must already exist in the running Ollama service. The supervisor neither
pulls models nor enables semantic/explanation HTTP flags. Capture aggregate
results and actual platform counts before the two scoped commits.

Default workload/model/host-supervisor CLIs print a plan without --execute.
Socket-server tests exercise the real bounded HTTP transport; supervisor tests
cover own-container stop on failure, report validation, missing resources and
output overflow. Short explicit parameter IDs avoid Windows environment limits.

## Evidence boundaries

Real user Docker/PostgreSQL/workload/model acceptance for this slice is pending.
Direct live-model synthetic-client timings are not full API model-workflow or
broad corpus quality evidence. Docker samples are not exact RSS peaks. Shared
normal-stack load can affect results. Hosted CI, final frontend/browser QA,
production deployment and coordinated restore remain separate unverified work.
