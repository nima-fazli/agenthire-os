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

The isolated CI plan adds operations_smoke as its sixteenth smoke. Execute it
and normal-stack acceptance before the two scoped commits. Production rollout,
backup/restore and wider failure/load exercises remain later work.
