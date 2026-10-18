# Private incident runbook

Run host commands in the project root. Keep identifiers, raw logs, credentials
and documents private. Diagnostics report aggregate observations only.

| Observation | Check | Recovery boundary |
| --- | --- | --- |
| /health answers but /ready fails | runtime_diagnostics component states, Alembic current/check | Restore DB/storage connectivity or install reviewed migrations; never stamp to hide mismatch |
| Core ready, queue policy attention | Queue age, expired leases and every worker's health | Check safe worker error events and dependencies; a restart does not erase jobs or guarantee progress |
| Missing/unhealthy extraction replica | stack_diagnostics and both indexed worker healthchecks | Inspect the affected service before a targeted restart; preserve DB and document volumes |
| Semantic service healthy but retrieval unavailable | Explicit semantic flags, model inventory and source coverage | Heartbeat/container health does not prove a model is loaded, compatible or accurate |
| Readiness p95 changes | Repeat the same bounded sample on the same hardware | Compare endpoint results separately from inference and full recruiting workflows |

## Read-only host observations

    uv run --locked --no-sync python -m scripts.stack_diagnostics
    uv run --locked --no-sync python -m scripts.operations_probe --requests 20 --concurrency 4
    docker compose exec --index 1 -T extraction-worker python -m app.workers.document_extraction --healthcheck
    docker compose exec --index 2 -T extraction-worker python -m app.workers.document_extraction --healthcheck

stack_diagnostics uses only compose ps --all and emits counts, not container IDs,
commands, names, mounts or environment. It requires at least two healthy extraction
replicas by default. --semantic additionally checks existing embedding/Ollama
containers; it does not start them, enable features or invoke a model.

## Private queue observations

    docker compose --profile smoke build smoke
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.runtime_diagnostics --queues
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.runtime_diagnostics --queues --max-queue-age-seconds 300 --max-expired-leases 0

Limits are explicit examples, not a measured SLA. A value equal to the limit
passes; a larger value raises attention. Nonzero exit with status=ready can mean
queue_policy=attention: the API core is ready but the operator's queue limit is
exceeded. Age uses persisted created_at and may include time before an explicit
retry. One snapshot cannot establish queue growth or prove worker failure.

## After recovery

Repeat core/worker diagnostics, Alembic check and the relevant smoke. Check a
synthetic end-to-end job when its workflow was affected. Record time, response
request_id, safe error category and measured results. Do not retry an uncertain
write before reading its state. Do not automatically delete files, clear queues,
change feature flags or remove volumes. Coordinated restore needs the later
release backup/restore procedure; the personal recovery file is not a backup.

## Measurement run

After the core stack is healthy with two extraction workers and the smoke image
has been rebuilt, capture idle observations on the host and inside the private
smoke container. Keep ordinary work quiet when comparing runs:

    uv run --locked --no-sync python -m scripts.resource_watch --samples 15 --interval 1
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.queue_watch --samples 15 --interval 1
    uv run --locked --no-sync python -m scripts.benchmark_run --kind workflow --execute --items 4 --concurrency 2
    uv run --locked --no-sync python -m scripts.benchmark_run --kind models --execute --samples 3

The workflow command uses real API/PDF/extraction/chunk/lexical retrieval.
The model command uses installed qwen3-embedding:0.6b and qwen3:0.6b directly
with synthetic reference data; CPU-only contracts are unchanged. Compare runs
with the same input counts/concurrency/hardware. No fixed latency SLA is invented.
Inspect passed/completed/cleanup together. A low percentile with failed attempts
or incomplete resource coverage is not an accepted result.

If a run fails, preserve its aggregate run_id and diagnostic. For a workflow it
maps to organization slug workload-<run_id> and its synthetic account. An uncertain
write is not retried or automatically deleted. Inspect scoped API/DB state before
using normal deletion protocols; do not bulk-delete workload-prefixed tenants.
The host supervisor stops only its own generated smoke container on failure;
normal API, workers, DB and Ollama remain under their existing operator controls.
A failed synthetic run can leave its own metadata/files for review.

Sampled Docker memory excludes/handles cache according to Docker's platform
accounting and can miss the true peak. Repeated high worker CPU with empty
queues warrants separating healthcheck/import cost from polling/SQL cost before
changing intervals. Neither one snapshot nor one small synthetic run establishes
production capacity. Save aggregate reports; never publish raw logs/env or PDFs.

## Worker healthcheck startup (14-B3)

The accepted e2b42e9 baseline had empty queues at both ends of the observation.
Each ten-second PID 1 window averaged 0.8/1.0 percent CPU for the extraction
replicas and 1.4 percent for embedding. Median CPU per extraction healthcheck was
2851.659/2843.580 ms; embedding was 771.468 ms. The corresponding fresh Python
launches consumed 54.349/56.450/80.864 ms. These are individual child timings,
not a measured average for the whole container or proof of continuous saturation.

Settings previously imported local-model URL validation through the SQLAlchemy
vector module. 14-B3 isolates that validator and defers extraction/storage/DB
imports until normal worker startup. Embedding's heartbeat-only CLI also avoids
loading asyncio/logging. Poll intervals, heartbeat timestamps/age margins and
Compose healthcheck commands are unchanged. Extraction still validates its
settings, including a longer configured task timeout.

Native Windows and isolated Docker acceptance passed. The user rebuilt the
api/migrate/extraction/embedding/smoke images, started the existing semantic
profile with two extraction replicas, and verified the normal schema and synthetic
workflow. The same read-only measurement then produced:

| Worker | p50 CPU before (ms) | p50 CPU after (ms) | Reduction |
| --- | --- | --- | --- |
| Extraction 1 | 2851.659 | 980.490 | 65.6% |
| Extraction 2 | 2843.580 | 1181.112 | 58.5% |
| Embedding 1 | 771.468 | 349.616 | 54.7% |

Median wall times changed from 2874.435/3918.522/2697.530 ms to
1019.626/1320.356/969.522 ms in the same worker order. All nine new calls exited
zero. Ten-second PID 1 averages were 0.6/0.9/1.4 percent after the change. Queues
were empty at both observation boundaries and the final stack was healthy.

These are three calls per worker in each run, not controlled cold/warm trials or
a guaranteed reduction for every machine. The resource watcher still recorded a
172.16 percent extraction CPU maximum summed across two replicas; that sample
does not establish continuous load. Compare child CPU and wall time separately.
Fresh-process tests enforce import separation without arbitrary timing limits.

For later changes, rebuild affected normal images before repeating the same
measurement; preserve normal volumes and verify Alembic current/check and
workload_smoke. Live inference does not need to be repeated to measure a
heartbeat probe. Adjust intervals only when later measurements justify doing so.

## Recovery rehearsal (15-A2)

Run scripts.recovery_drill on the host project root; default invocation prints a
plan and --execute creates/restores two fresh synthetic stacks. Full CI includes
this gate. It stops only the generated source writers and restores only into its
fresh target, then checks schema, PDF bytes, deterministic vectors, application
state, retrieval and tenant isolation. See [recovery.md](recovery.md) for limits.

Require status=passed together with cleanup=completed. On cleanup=attention,
retain the reported owned project names and inspect only those namespaces.
Never substitute the normal project name into a drill cleanup or restore.
The temporary bundle is removed; this gate does not provide retained backups,
normal-data restore, offsite retention or a measured RPO/RTO.

## Retained private backups (15-A3)

See [backups.md](backups.md) for private store setup and capture/restore/retention
boundaries. Capture pauses normal API/extraction/embedding writers and resumes
the same originally running IDs; it creates no replacement normal containers.
Accept capture only with status=passed, retained_backup=true and
source_resume=completed. Accept isolated restore only with DB/PDF integrity,
API readiness, cleanup=completed and restore_receipt_created=true.

If capture is interrupted, inspect list/resume_required and use backup_run resume
with the same private store. An active OS lock, foreign/replaced container or
invalid journal must not be bypassed. Restore requires the recorded source to
be resumed first. Keep partial bundles private for scoped inspection; they are
never accepted as complete and block retention. Reports expose only generated
backup/project IDs and aggregate states, not environment contents or raw errors.
Windows store ACL validation is part of native acceptance. Do not infer offsite,
encryption, whole-cluster recovery or RPO/RTO guarantees from a successful gate.
