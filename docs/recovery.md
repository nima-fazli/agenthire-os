# Isolated recovery rehearsal

15-A2 implements a logical database/PDF snapshot and restores it into a second
fresh synthetic stack. It is a release verification gate, not a retained backup
of the normal application's data. Native Windows/Docker acceptance passed on
2026-10-18; scoped 15-A2 commits are pending.

## Observed baseline

The accepted clean 15-A1 main baseline was c7d66c22a43336c2cd8069a082d3e1725fec5939, after
955ac944c835c426ddfb92374e73bc22e121e6b9. The accepted 15-A1 read-only inventory
reported Docker 29.8.0, Compose 5.5.1, PostgreSQL/pg_dump/pg_restore 18.6 and
pgvector 0.8.6. Schema head is 0016_document_embeddings.

The normal database occupied 9918143 bytes. Two ready document rows and two PDF
objects both totalled 138041 bytes. There were no deleting rows, temporary files,
symlinks or unknown entries. Both queues were empty. This agreement of counts and
sizes did not verify PDF contents or create a backup. Host project-volume free
space was 91805736960 bytes; document-volume free space was 971221499904 bytes.

## Accepted 15-A2 rehearsal

The native run passed 1591 Windows Python tests with 5 known platform skips,
1596 Docker Python tests without skips, 42 Node tests in each environment and
Ruff in each environment. All 32 CI checks, 18 smokes and separate cleanup passed.
The source and restored target used fresh isolated synthetic stacks.

The drill reported status=passed, cleanup=completed, database_restored=true,
artifact_integrity_verified=true and document_integrity_verified=true. The source
API and both extraction workers were stopped. Two organizations, two PDF
downloads, two lexical retrievals and two exact embedding fixtures were verified,
together with tenant
isolation. Its full elapsed time was 97461.269 ms; this includes the rehearsal
lifecycle and does not establish a production RTO. Temporary artifacts were
removed, retained_backup=false and models_checked=false. The normal stack was
not targeted and its final services were healthy with both queues empty.

The Windows directory scan now reads full os.stat metadata without following
symlinks. A regression reproduces DirEntry.stat's zero-link metadata, while real
hardlinks are rejected during both the scan and opened-handle checks.

## Run from the host project root

    uv run --locked --no-sync python -m scripts.recovery_drill
    uv run --locked --no-sync python -m scripts.recovery_drill --execute

The first command prints a plan without creating files or launching commands.
The second explicitly creates two generated agenthire-ci-* namespaces. It checks
that both namespaces have no containers, volumes or networks before acquiring
cleanup ownership. An occupied namespace aborts without build/start/cleanup.
Inherited AGENTHIRE_/COMPOSE_ settings are replaced by separate generated test
credentials and env files. The normal .env, project and volumes are not reused.

The full scripts.ci_verify plan now has 32 checks: its existing 18 smokes plus a
host recovery-drill gate, with separate outer cleanup. The drill performs its
own cleanup of both fresh projects, including on failure. It never accepts an
operator-supplied source/target project or an arbitrary archive to restore.

## Capture and restore boundaries

1. Build a fresh source using the existing CI override and two extraction workers.
2. Create two synthetic tenants through the API, with real PDFs, extraction,
   chunks, screening applications and lexical retrieval. Persist deterministic
   1024-dimensional embedding fixtures through the real DB pipeline; no model
   inference or API feature-flag change is involved.
3. Stop this source's API/workers and require their running inventory to be empty.
   Require settled queues, ready documents and the expected PostgreSQL/schema.
4. Capture a PostgreSQL custom archive and a flat PDF ZIP while the owned source
   writers remain stopped. Match every PDF's bytes against persisted size/SHA-256.
   Reject missing/unreferenced files, links, temporary files and unfinished work.
5. Seal both component hashes in a manifest and rename the completed bundle.
   Recheck hashes before starting restore. Partial output is never accepted.
6. Start only PostgreSQL in the fresh destination; require no public tables.
   Restore using --single-transaction, --exit-on-error, --no-owner and
   --no-privileges. No --clean, DROP, volume reuse or normal-stack restore exists.
7. Validate the PDF archive and its exact agreement with restored metadata before
   creating files exclusively in an empty destination. Check hashes again.
8. Verify Alembic current/check, start the restored API/workers and check login,
   private PDF download, chunks, exact deterministic vector values, application
   state, lexical retrieval, unauthorized access and cross-tenant rejection.
9. Remove only the two generated stacks/volumes and temporary artifacts. Build
   cache follows the existing CI behavior. A cleanup failure fails the gate.

This coordination covers the owned synthetic stack's known application writers.
It does not coordinate external administrators or arbitrary external writers.
Binary archives move through Python file handles, not PowerShell text redirection.

## Limits and interpretation

PDF catalogs allow at most 1000 objects, 50 MiB per object and 128 MiB in total.
The ZIP is stored without compression and accepts only objects.json plus exact
objects/<32-lowercase-hex>.pdf members. Duplicate keys/members, traversal, links,
encryption, unsupported compression and metadata mismatches are rejected before
restored files are written. Component acceptance is capped at 256 MiB. This is
an operator drill for its small generated fixture, not an untrusted upload API.

Success requires status=passed and cleanup=completed. Reports expose aggregate
counts, fixed diagnostic/phase labels and generated project names, never source
text, document identifiers, credentials, tokens or raw subprocess errors. If
cleanup=attention, preserve the two owned project names for scoped inspection;
do not apply cleanup commands to agenthire-os or delete unrelated resources.

The temporary bundle is deleted after the drill: retained_backup=false. These
checks do not establish recovery-time/recovery-point objectives, a power-loss
durability guarantee, offsite retention or real-data disaster recovery. PostgreSQL
cluster roles/tablespaces, .env/secrets and model weights are outside this bundle.
Checksums detect changes within this run; they are not a signature or encryption.
Retained private backups, configuration/secret recovery, retention and operational
restore procedures remain later release work. Restore only trusted own dumps.

PostgreSQL references: [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
and [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).
