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
