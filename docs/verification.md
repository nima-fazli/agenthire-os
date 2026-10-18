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

## Accepted 14-B3 baseline

The user completed the native verification on main with e2b42e9 as the observed
Git baseline. Acceptance was followed by feature 955ac94 and tests c7d66c2;
main was clean. Full observed test commit is c7d66c22a43336c2cd8069a082d3e1725fec5939.

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

14-B3 used 31 CI checks, 18 smokes and separate owned cleanup. Both indexed
extraction worker healthchecks and real PDF/worker/chunk/retrieval gates remain.
For later runtime changes, rebuild affected normal images, verify Alembic
current/check and workload_smoke, then repeat the recorded read-only measurement.

New tests launch fresh Python subprocesses with network access and DB/model
runtime imports rejected. They cover settings construction, fresh/missing/stale/
future/malformed/nonfinite heartbeats and the configured long-task margin.
Normal worker startup must still request its processing runtime. Embedding's
health CLI must also avoid loading asyncio/logging. Native settings parsing and
both existing local_base_url import paths retain their prior contracts.

## Accepted and committed 15-A2

15-A1's real read-only inventory passed: PostgreSQL/server tools 18.6, vector
0.8.6, schema 0016_document_embeddings, 9918143 database bytes and two PDFs/
metadata rows totalling 138041 bytes. Queues and Git were clean. Counts/sizes
alone did not establish document integrity or create a backup.

Assistant Linux checks passed: 1596 Python tests with -W error, 42 Node tests,
Ruff, the 32-check CI dry-run and the no-side-effect recovery plan. Windows test
environment-value bounds were enforced; maximum length remained 5284 characters.
These checks include archive corruption/path/link rejection and simulated
namespace, writer, target, process and cleanup failures. They do not execute
PostgreSQL dump/restore or native Docker on the user's machine.

The first native Windows 15-A2 run passed file hashes and Ruff, then stopped at
pytest: 1573 passed, 5 known platform skips, 4 failures and 11 setup errors.
All failures came from checking st_nlink on DirEntry.stat(), which reports zero
on Windows. The corrected scan uses os.stat(entry.path, follow_symlinks=False)
and retains both path and opened-handle hardlink rejection. New tests reproduce
the Windows metadata behavior and reject real hardlinks at both checks. The
corrected native run then passed on 2026-10-18:

| Check | Actual 15-A2 result |
| --- | --- |
| Windows Python with -W error | 1591 passed, 5 known platform skips |
| Docker Python | 1596 passed, no skips |
| Node | 42 passed on each platform |
| Ruff | Passed on each platform |
| Isolated CI | 32 checks, 18 smokes and separate cleanup; all exit 0 |
| CI schema | 0016_document_embeddings, no drift |
| Synthetic workload | 2/2 at concurrency 2, scoped cleanup completed |
| Recovery | DB restored; archive and PDF integrity verified |
| Restored fixture | 2 organizations, 2 PDF downloads, 2 lexical retrievals, 2 exact vectors |
| Tenant isolation | Verified after restore |
| Recovery cleanup | Both owned projects and temporary artifacts cleaned |
| Normal stack | Healthy services, 2 extraction replicas, both queues empty |

The drill reported status=passed, phase=completed, cleanup=completed,
source_writers_stopped=true and normal_stack_touched=false. Its full elapsed
time was 97461.269 ms, including the rehearsal lifecycle, not a production RTO.
The fixture did not invoke models and the temporary bundle was not retained.
Acceptance was followed by feature ffe34dda4dac44aa92840345ffe122cfb4706e2c
and tests 07778952be9ff9a6fd86064a3fa2c7dcd048c824; main was clean. No normal
images were rebuilt for this slice; final stack and queue observations passed.

Run the normal checks above, inspect the recovery plan, then scripts.ci_verify.
Its new host recovery-drill gate creates two separate fresh synthetic stacks.
The 15-A2 plan was 32 checks, 18 smokes, one recovery gate and separate outer
cleanup. The drill verifies two tenant PDF/API workflows and deterministic
vector values through actual PostgreSQL dump/restore and owned cleanup.

    uv run --locked --no-sync python -m scripts.recovery_drill
    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify
    uv run --locked --no-sync python -m scripts.stack_diagnostics --semantic

Accept only when the drill reports status=passed, cleanup=completed,
document_integrity_verified=true, embedding_vectors_verified>=2 and
normal_stack_touched=false, and the outer CI summary passes/cleans up. Then
verify the normal stack and queues. These native acceptance conditions passed
in the recorded run. No normal image rebuild or model benchmark is required
for this slice. Repeat affected checks when later code changes justify doing so.

## Accepted 15-A3 verification

The native preflight passed on clean main 07778952be9ff9a6fd86064a3fa2c7dcd048c824:
all requested services healthy, two extraction replicas, empty queues,
PostgreSQL tools 18.6 and 91805437952 host free bytes. No backup was created by
that preflight. New code covers the private store, component/DB fingerprints,
original-container pause/resume journal, isolated restore receipts and explicit
retention. Native Windows/Docker acceptance passed on 2026-10-18.

Assistant Linux checks passed: 1677 Python tests with -W error, 42 Node tests,
Ruff, both operator plans and the 33-check CI dry-run. The Windows test-value
bound remained 5284 characters. The 143 focused backup/CI tests cover corruption,
locking, ownership, interrupted capture, original-writer resume, changed runtime
configuration, restored data disagreement and source/target cleanup failures.
These assistant checks simulate Docker/SQL operations. The native results below
separately exercised Windows ACLs and actual retained database/PDF restore.

The first native attempt passed all file hashes and Ruff, then stopped at host
pytest: 1670 passed, 5 known platform skips and 2 failures. A test compared two
independently generated ZIPs byte-for-byte even though ZIP metadata records the
creation time. Only tests/test_backup_run.py changed: the restore matrix now
forces different ZIP timestamps without sleeps, verifies equal member contents,
and expects the exact retained archive bytes. Transport equality and all
integrity gates remain. With the old expectation, the forced timestamp case
reproduced the failure; after correction all local checks passed.

The corrected native run matched all 19 delivery hashes and completed:

| Check | Actual 15-A3 result |
| --- | --- |
| Windows Python with -W error | 1672 passed, 5 known platform skips; 193.22 seconds |
| Docker Python | 1677 passed, no skips; 53.50 seconds |
| Node | 42 passed on each platform |
| Ruff | Passed on each platform |
| Isolated CI | 33 checks, 18 smokes, two host recovery gates and separate cleanup; all exit 0 |
| CI schema | 0016_document_embeddings, no drift |
| Synthetic workload | 2/2 at concurrency 2; scoped cleanup completed |
| Original recovery drill | Two-tenant PDF/vector/API checks and cleanup passed |
| Retained-backup synthetic gate | Capture, original-container resume, isolated restore, receipt and both cleanups passed |
| Private Windows store | Initialized; component verification passed |
| Normal-data capture | Retained backup, integrity verified, source_resume=completed |
| Retained normal-data restore | 20 database rows and 2 PDFs matched; target API ready |
| Restore completion | Target cleanup completed; restore receipt created; source bundle retained |
| Retention | Plan passed; executed=false; no deletion |
| Final normal stack | API/DB/two extraction workers/embedding/Ollama healthy; both queues empty |

The normal capture intentionally paused its original application writers and
resumed the same containers. Isolated restore reported normal_stack_touched=false.
The normal source bundle remains in the separate private host store. Its source
.env was retained privately and was not injected into the generated target.
The original temporary recovery drill took 107688.692 ms including its full
lifecycle; this is not a production RTO or a timing for retained normal-data
restore. Models were not invoked.

After reviewing these results, only documentation was updated for the checkpoint;
runtime code and tests remain the native-verified versions. Scoped feature/test
commits are the next recording step. Keep private backup contents out of Git.

## Evidence boundaries

14-B3 passed its worker-startup acceptance. Each cost comparison uses three calls
per worker; cold/warm state was not controlled. Sampled container CPU maxima
cannot show a sustained busy loop; PID 1 and child timings are separate measures.
Live inference was not repeated in this stage. Earlier 14-B2 model results remain
the available live-model evidence. Full API live-model workflows, wider corpus
quality, hosted CI, final frontend browser QA and production deployment remain
separate work. 15-A2 passed its native synthetic recovery rehearsal; 15-A3 also
passed retained normal-data capture and isolated restore. Actual redeployment of
the normal environment, encrypted/offsite copies and measured RPO/RTO remain
separate release work. Native retention deletion was not executed. See
recovery.md and backups.md for exact guarantees and exclusions.
