# Operations

## Signals and contracts

| Signal | Meaning | Excludes |
| --- | --- | --- |
| GET /health, 200 | API process can answer HTTP; existing JSON contract | DB, storage, workers, models |
| GET /ready, 200 | DB query succeeds, installed migration heads match packaged heads, storage probe succeeds | Worker throughput, Ollama/model availability, corpus quality |
| GET /ready, 503 | A core requirement is unavailable or initialization has not completed | Public failure details |
| runtime_diagnostics --queues | Local operator-only component states and aggregate extraction/embedding queue rows | Tenant IDs, text, paths, credentials, model calls |
| Existing worker --healthcheck | That worker's existing heartbeat contract | Model correctness and end-to-end capacity |

/ready always sends Cache-Control: no-store and only status ready/not_ready.
It does not expose component states, schema names or global queue statistics.
Compose uses /ready for API health; /health remains independent liveness.
There is no new migration or configuration flag.

## Probe limits

DB work uses a read-only transaction, 1000 ms statement timeout and 500 ms lock
timeout, then closes the session without commit. Expected heads come from the
packaged Alembic graph; readiness neither upgrades nor stamps a database.
DB and storage probes run concurrently with a two-second cooperative deadline.
Concurrent clients share one probe; completed results are cached for one second.
Client cancellation does not cancel another client's probe; shutdown cancels
owned asynchronous work and disposes the API engine.

The storage directory must already exist. The probe rejects filesystem root
and linked path components, creates one uniquely named .readiness-* file,
writes/fsyncs one byte and removes only that file. Existing PDFs are untouched.
It does not create a missing directory or repair permissions. A crash can leave
its tiny probe file behind; the probe does not sweep old files. Reconciliation
continues to follow its existing conservative rules.

A process-wide slot bounds storage work to one running filesystem thread.
Cancellation of the HTTP waiter cannot interrupt kernel filesystem I/O; the
slot remains held until that operation finishes. Cleanup and driver cancellation
can extend the cooperative deadline. This is not a hard process-kill guarantee
or a storage/DB consistency check.

## Private operator commands

Run from the project root after building the smoke image:

    docker compose --profile smoke build smoke
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.runtime_diagnostics
    docker compose --profile smoke run --rm --no-deps smoke python -m scripts.runtime_diagnostics --queues
    docker compose --profile smoke run --rm smoke python -m scripts.operations_smoke
    docker compose ps
    docker compose exec extraction-worker python -m app.workers.document_extraction --healthcheck

The CLI lives in the smoke image, not the lean API runtime image. It writes one
JSON object to stdout, safe structured errors to stderr and exits 0 when core
readiness and any requested queue query succeed; otherwise 1. Ctrl-C exits 130.
It reports semantic/explanation flags and models_checked=false, without invoking
Ollama or downloading anything. Aggregate queries have a two-second cooperative
deadline and the same transaction-local DB limits as readiness.

Queue counts describe persisted queued/running rows, expired running leases and
oldest queued age in seconds using PostgreSQL statement time. They are global
operator statistics, not per-tenant API data, claimable-work counts or proof that
a worker is alive. An empty queue has age zero. Counts may change immediately
after the snapshot. Investigate age trends and existing worker health together.

If the semantic profile is already in use, inspect its existing embedding-worker
health and Ollama/model list separately. Do not turn feature flags on to make
core readiness green. Do not use destructive volume cleanup to repair health.

## Request correlation and logs

Every HTTP request receives a new server-generated 32-character lowercase hex
X-Request-ID, including handled errors, 404 and generic 500 responses. Client
supplied IDs are ignored. The identifier links one response to safe application
error and completion events; it is neither authentication nor distributed tracing.

Completion events contain method, matched route template or unmatched, status,
outcome and elapsed milliseconds. Query strings, raw route parameters, tokens,
bodies, resume text and inbound headers are not captured. The pure ASGI wrapper
forwards body messages without reading or buffering uploads/downloads. Streaming
errors retain the status already sent and record outcome=error; cancellation
propagates and is recorded. A missing final body is incomplete.

Application exception formatting retains type and frame locations, omitting
exception messages, source lines and chains. Uvicorn's raw access logger is
disabled; its server messages are normalized to server_event by the JSON handler.
Other container programs have their own log formats: do not treat all DB/model
logs as sanitized. Docker's json-file driver keeps at most three 10 MB files
per configured service container; rotation is not a backup or central monitor.

For an API error, retain the response ID, method, UTC time and status. A local
operator can match request_id in API logs and inspect readiness/worker health.
Do not publish raw logs, environment dumps, private documents or credentials.
Support procedures must account for logs expiring through rotation.

## Acceptance and limits

operations_smoke checks real HTTP IDs/minimal readiness, private CLI output,
an isolated failed connection, actual migration comparison and missing storage.
Queue arithmetic uses synthetic temporary tables on its own connection; public
queues, alembic_version, running services and documents are not modified.
This smoke does not stop a real service, test a network partition, establish
load capacity, restore a backup or verify live model quality.

The accepted 14-A plan added operations_smoke as its sixteenth smoke. Execute
normal-stack acceptance before scoped commits. Production rollout,
backup/restore and wider failure/load exercises remain later work.

## Stage 14-B1 private checks

See operations-runbook.md for host and private-container commands. Queue limits
are opt-in CLI arguments requiring --queues. Existing report fields remain;
queue_policy is added only when a limit is supplied. Limits inspect both queues,
never mutate rows, do not infer model/worker health and can cause exit 1 while
the core status remains ready. Invalid or unavailable aggregates fail closed.

Host stack_diagnostics reads Compose JSON Lines or legacy JSON arrays, includes
stopped containers and reports only requested service aggregates. Every observed
required replica must be healthy; migration containers must have exited zero.
Missing replicas fail. Optional semantic inventory must be explicitly requested.

operations_probe issues 1..64 GETs with concurrency 1..8 to /health or /ready on
HTTP loopback or the trusted Compose hostname api. It sends no auth or request
body, uses no proxy/redirect and reports no URL, response body or exception text.
The fixed health routes must return bounded Content-Length JSON and a server
request ID; /ready must be minimal and no-store. Other paths/origins are rejected.
Each request has a 0.05..5 second socket-I/O deadline covering headers and body.
OS name resolution/connection scheduling can extend wall time; this is not a hard
process-kill guarantee. Interrupt cancels pending work and waits for running probes.

Latency p50/p95 use nearest-rank over all attempts, including failures; max and
outcome counts are included. --max-p95-ms is an optional explicit acceptance
limit. The sampler includes cold readiness and its cache. It neither measures
inference nor establishes production throughput, peak memory or capacity.

operations_failure_smoke exercises real PostgreSQL statement cancellation,
read-only write denial, rollback resetting local settings and same-connection
reuse, then 20 concurrent readiness GETs. The rejected DDL always rolls back.
It does not stop services, commit schema/data changes or test disaster restore.
The isolated CI adds this seventeenth smoke and checks both extraction workers
explicitly. User accepted and committed 14-B1 as 822c4c2/78987f4.

## Stage 14-B2 bounded measurements

The native preflight observed both expected models installed, none loaded,
Ollama 111.3 MiB / 3 GiB, workers 87.68 MiB and 118 MiB / 768 MiB each. Their individual
CPU samples 71.66% / 99.17% are observations from separate instants, not an idle
baseline or proof of a worker-loop fault. The extraction loop already waits
when no task is processed. Capture a queue time series and resource window.

workload_benchmark defaults to a plan. --execute uses a random synthetic user
and organization, one job/profile and 1..8 synthetic candidates/PDFs/applications.
It transitions each application to screening, submits extraction once, polls
with a 180-second cooperative deadline and at most 240 polls, builds chunks and
checks candidate/document identity in lexical retrieval. Default concurrency
is 2; at most 4 is allowed. No failed or uncertain write is automatically retried.
Request I/O has a 15-second socket deadline, bounded headers/body and only local
HTTP origins. DNS/OS scheduling can extend wall time. Metrics include all
attempts, failures and nearest-rank percentiles. request_to_completion includes
submission, processing and polling; it is not isolated queue-wait time.

After a completely successful workflow, document deletion uses the existing
API/storage protocol. Private metadata cleanup deletes only recorded IDs in
the synthetic organization in one transaction with 5s statement / 1 s lock limits.
Any failed/ambiguous run skips automatic cleanup; its run_id identifies the
synthetic namespace for operator review. Partial cleanup may have removed some
own PDFs before a later error. Never sweep other runs or ordinary documents.
The isolated CI owns/discards its own volumes even when its workload gate fails.

model_benchmark requires --execute for 1..4 sequential samples of each existing
CPU client. It encodes synthetic reference text and grounds generated quotes
against a synthetic DTO. Fixed model/dimension/digest contracts are retained.
No new model is pulled and no API feature flag changes. Results are direct
client/model measurements, not DB/HTTP workflow timings or a broad quality gate.
Embedding retains its existing 5 m keep-alive; chat retains keep_alive=0.
First/repeated samples are reported without asserting controlled cold/warm
conditions. Another model user can contend for the same Ollama slot.

resource_watch maps validated private Docker IDs to whitelisted service labels,
then discards IDs/names/commands. It sums replicas within each sample and records
observed CPU/memory maxima. An unchanged replica count and memory limit are
required; missing/changed stats fail closed. Sampling can miss short peaks.
The watcher has 1..120 samples; each Docker command has a 5-second timeout and a
bounded accepted output. Its interval is added to command time, not an exact
sampling frequency. queue_watch reads global aggregates in existing read-only
transactions, 1..60 samples at intervals 0.25..5 s, disposing its engine on exit.
It does not infer throughput, model availability or a stalled task from counts.

benchmark_run is a host-only supervisor for two fixed commands. It starts one
uniquely named smoke container with --no-deps/--rm, drains bounded stdout/stderr,
validates the successful aggregate report and samples existing service resources
before/during/after execution. Default deadline is 600 s. On interruption,
timeout, malformed output or missing resource data it reports incomplete and
requests stop only for its own generated container; it never stops the normal
stack. A stop request is not proof of rollback or remote termination. The run_id
also identifies that workflow's synthetic namespace if manual review is needed.
Untrusted/raw child output is not published. Docker CLI/read/cleanup time can
extend cooperative deadlines; no hard process-stop or exact-peak claim is made.
