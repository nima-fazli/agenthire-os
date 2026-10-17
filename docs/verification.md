# Verification

## Accepted 14-B2 baseline

User main was clean on e2b42e9, following feature commit 09f232e. The observed
14-B1 commits are 822c4c2/78987f4 and 14-A commits are 31b7730/f8286de.

| Check | Actual 14-B2 result |
| --- | --- |
| Windows Python with -W error | 1525 passed, 5 known platform skips |
| Docker Python | 1530 passed, no skips |
| Node | 42 passed on each platform |
| Ruff | Passed on each platform |
| Isolated CI | 31 checks, 18 smokes, separate cleanup; all exit 0 |
| CI schema | 0016_document_embeddings, no drift |
| Normal stack | API/DB/two extraction workers/embedding/Ollama healthy |
| Synthetic workflow | 4/4 completed at concurrency 2; scoped cleanup completed |
| Local models | 3 sequential live samples each; chat grounding passed |
| End state | Core ready, both queues empty |

The workflow p50/p95 was 785.616/904.829 ms per candidate through chunks.
Embedding p50/p95 was 739.285/4532.536 ms; chat was 12073.837/12533.364 ms.
These small synthetic samples are not production capacity or broad quality proof.
The sampled Ollama memory maximum was 2582349086 bytes, not an exact RSS peak.

## Current 14-B3 acceptance

The user completed the native verification on main with e2b42e9 as the observed
Git baseline. The output reached the final verification marker. Scoped 14-B3
commit hashes have not yet been observed.

| Check | Actual 14-B3 result |
| --- | --- |
| Windows Python with -W error | 1541 passed, 5 known platform skips |
| Docker Python | 1546 passed, no skips |
| Node | 42 passed on each platform |
| Ruff | Passed on each platform |
| Isolated CI | 31 checks, 18 smokes, separate cleanup; all exit 0 |
| Normal images | API/migrate/extraction/embedding/smoke rebuilt |
| Normal and CI schema | 0016_document_embeddings, no drift |
| Normal synthetic smoke | 2/2 completed with scoped cleanup |
| Supervised synthetic workflow | 4/4 at concurrency 2 with scoped cleanup |
| Worker-cost probes | 3 calls per worker, all 9 exit 0 |
| End state | Stack healthy, both queues empty |

The four-item workflow p50/p95 was 760.633/775.844 ms per candidate through
chunks; request-to-completion was 595.743/619.601 ms. Healthcheck median CPU fell
from 2851.659/2843.580/771.468 ms to 980.490/1181.112/349.616 ms for extraction
replicas 1/2 and embedding 1. Median wall times became
1019.626/1320.356/969.522 ms. See the runbook for comparison limits.

Assistant Linux checks passed: 1546 Python tests with -W error, 42 Node tests,
Ruff and the unchanged CI dry-run. The full collection also enforced the Windows
32767-character environment-value bound; its maximum was 5284 characters.
The fresh-process regression tests reject the old heavy healthcheck paths.
These assistant checks are separate from the user's native results above.

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The CI plan remains 31 checks, 18 smokes and separate owned cleanup. Both indexed
extraction worker healthchecks and real PDF/worker/chunk/retrieval gates remain.
For later runtime changes, rebuild affected normal images, verify Alembic
current/check and workload_smoke, then repeat the recorded read-only measurement.

New tests launch fresh Python subprocesses with network access and DB/model
runtime imports rejected. They cover settings construction, fresh/missing/stale/
future/malformed/nonfinite heartbeats and the configured long-task margin.
Normal worker startup must still request its processing runtime. Embedding's
health CLI must also avoid loading asyncio/logging. Native settings parsing and
both existing local_base_url import paths retain their prior contracts.

## Evidence boundaries

14-B3 passed its worker-startup acceptance. Each cost comparison uses three calls
per worker; cold/warm state was not controlled. Sampled container CPU maxima
cannot show a sustained busy loop; PID 1 and child timings are separate measures.
Live inference was not repeated in this stage. Earlier 14-B2 model results remain
the available live-model evidence. Full API live-model workflows, wider corpus
quality, hosted CI, final frontend browser QA, production deployment and
coordinated restore remain separate work.
