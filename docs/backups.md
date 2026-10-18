# Retained private backups

15-A3 adds a bounded local operator workflow. The accepted baseline is clean main
07778952be9ff9a6fd86064a3fa2c7dcd048c824, after feature
ffe34dda4dac44aa92840345ffe122cfb4706e2c. Its native preflight passed: two healthy
extraction replicas, API/PostgreSQL/embedding/Ollama healthy, empty queues,
PostgreSQL dump/restore tools 18.6 and 91805437952 host free bytes.
Native Windows/Docker acceptance passed on 2026-10-18. Windows passed 1672
Python tests with 5 known platform skips; Docker passed 1677 without skips.
Node passed 42 and Ruff passed in both environments. All 33 CI checks, 18
smokes, both recovery gates and separate cleanup passed. The private Windows
store initialized and verified one retained normal-data bundle. Its isolated
restore matched 20 database rows and 2 PDFs, reached API readiness, completed
target cleanup and created a restore receipt. Original source containers resumed
healthy; the final normal stack was healthy and both queues were empty.
Retention was a plan only: executed=false, with no backup deletion.

## Private store

Run on the host project root. The example store is outside the repository:

    uv run --locked --no-sync python -m scripts.backup_run init --store D:\AgentHireBackups\agenthire-os
    uv run --locked --no-sync python -m scripts.backup_run init --store D:\AgentHireBackups\agenthire-os --execute

Without --execute, init/capture/restore/resume print a plan without processes or
file creation. Initialization exclusively creates a new directory. It never
adopts an existing folder or resets an existing store's permissions.
Windows uses a protected DACL allowing only the current account and SYSTEM;
Unix requires an owner-only 0700 directory. Windows child ownership by the
Administrators group is accepted for elevated creation, while access rules
still allow only the account and SYSTEM. Symlinks/junctions and hardlinked
component files are rejected. Another process cannot acquire the store lock;
the operating system releases the lock if its holder dies.

This is access-controlled local storage, not encryption or offsite retention.
The bundle includes private database contents, PDFs and source.env credentials.
Keep its contents outside Git, delivery archives and shared uploads. Operator
reports contain generated backup IDs/counts/states; source.env is never printed.

## Capture and resume

    uv run --locked --no-sync python -m scripts.backup_run capture --store D:\AgentHireBackups\agenthire-os --execute
    uv run --locked --no-sync python -m scripts.backup_run list --store D:\AgentHireBackups\agenthire-os

Capture targets only the existing agenthire-os project. It builds the smoke
transport image, checks the expected Git ancestor/main branch, original healthy
writer IDs/labels/images and API/database credential agreement with the current
source configuration. Dump uses that API's database/user rather than assuming
the PostgreSQL container's original initialization names. Supported identifiers
are 1..63 ASCII letters/digits/underscore/dot/hyphen, starting with a letter or
underscore; connection strings are rejected. Inherited AGENTHIRE_/COMPOSE_ host
overrides are excluded.
It records Git HEAD, which can still precede uncommitted operator-tool changes
during acceptance. The normal API/worker images are not rebuilt or recreated.

A private journal is flushed before stopping the API, both extraction workers
and any originally running embedding worker. Capture requires all known writer
services stopped, settled queues/ready documents and schema
0016_document_embeddings on PostgreSQL 18. It captures the database custom dump,
exact PDF catalog/archive and current .env bytes, with logical database
fingerprints checked before and after the dump. These fingerprints cover every
public table's sorted SHA-256 row hashes and public sequence values. UTC/date/
float formatting is fixed; physical database-size differences are excluded.

The trusted source's known application writers are coordinated. External DB
administrators, direct storage writers and arbitrary custom schemas are outside
this coordination. The original containers are started again in a finally
block using the in-memory IDs, even if the on-disk journal is damaged. Their
labels/images are rechecked and health is awaited. No normal volumes are deleted.
Normal requests are unavailable during this maintenance window.

The journal is removed only after healthy resume and matching journal contents.
After process termination/power loss, use the recorded resume operation:

    uv run --locked --no-sync python -m scripts.backup_run resume --store D:\AgentHireBackups\agenthire-os --execute

It acquires the released OS lock and accepts only the journal's owned original
agenthire-os containers. An active operator lock, replaced container or invalid
journal fails closed. Inspect stack diagnostics when resume reports attention;
do not edit the journal to name unrelated containers or retry capture blindly.

## Verify and isolated restore

Copy an exact generated backup ID from capture/list in place of BACKUP_ID:

    uv run --locked --no-sync python -m scripts.backup_run verify --store D:\AgentHireBackups\agenthire-os --backup BACKUP_ID
    uv run --locked --no-sync python -m scripts.backup_run restore --store D:\AgentHireBackups\agenthire-os --backup BACKUP_ID --execute

Only a complete store-owned bundle is accepted. Restore creates one fresh
agenthire-ci-* project after checking that its containers/volumes/network do
not exist. It restores into an empty PostgreSQL target using --single-transaction,
--exit-on-error, --no-owner and --no-privileges. PDF metadata/bytes and logical DB
fingerprints must agree. Alembic current/check and the unpublished target API's
readiness must pass. The normal .env backup is retained for the operator; it is
never executed or injected into this isolated target, which uses fresh test
credentials, disabled model features and no published API port.

The target is cleaned on success/failure. A restore receipt is written only
after verification and successful target cleanup. Failures expose the generated
owned project name for scoped inspection. Restore never accepts a normal target
name or arbitrary external archive. The retained source bundle is preserved.

## Retention and limits

    uv run --locked --no-sync python -m scripts.backup_run prune --store D:\AgentHireBackups\agenthire-os --keep 3

Prune defaults to a plan. Adding --execute explicitly deletes only the planned
old complete store-owned directories. Keep must be 2..20. Every complete bundle
must verify, interrupted captures must be resolved, and at least one retained
bundle must have a matching successful restore receipt before any deletion.
Receipt history is kept. Partial captures are preserved for scoped inspection;
they are not listed as usable backups and block pruning. No automatic retention
job, uncertain-write retry or partial-folder deletion is installed.

Limits: 256 MiB source database/dump, 128 MiB total PDF bytes, 1000 PDFs,
50 MiB per PDF, 64 KiB source.env, 128 public relations and 200000 public table
rows. Capture requires 2 GiB free on its store volume. A partial directory becomes
a complete backup only after component hashes and archive validation pass.
Checksums are not signatures, and the store does not promise physical power-loss
durability, a production RPO/RTO, encrypted/offsite copies or whole-cluster
roles/tablespaces/model-weight recovery. Actual environment redeployment remains
separate release work. Restore only trusted own database dumps.

## Automated gate

    uv run --locked --no-sync python -m scripts.backup_smoke
    uv run --locked --no-sync python -m scripts.ci_verify

The 33-check CI plan retains 18 existing smokes and the original recovery drill,
then runs the new host retained-backup gate and separate outer cleanup. The new
gate uses only fresh synthetic source/target stacks, proves retained capture,
original-container resume, logical/PDF restore and two-tenant API behavior,
and exercises receipt/retention policy. Its temporary fixture store is removed;
it is not the operator's retained normal-data backup. Native acceptance also
captured and restored one private normal-data bundle and left the normal stack
healthy with empty queues. The retained bundle remains in the private host
store; the generated restore target was removed. No model inference, dependency,
migration, resource quota or final UI change is introduced.

References: [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html),
[SHA-256](https://www.postgresql.org/docs/18/functions-binarystring.html),
[Windows ACLs](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/set-acl?view=powershell-5.1).
