# Architecture

AgentHire OS is a modular monolith. Routes handle HTTP and dependencies. Services
authorize operations and own commit/rollback. Repositories implement scoped SQL
and never commit. PostgreSQL remains the final constraint and concurrency boundary.

## Domain ownership

| Domain | Ownership and invariant |
| --- | --- |
| User | Global identity; no global organization or role |
| OrganizationMembership | Unique organization/user relationship; current access boundary |
| Job | Belongs to one organization |
| Candidate | Belongs to one organization |
| Application | Unique job/candidate pair; both tenant relationships enforced by composite FKs |
| CandidateDocument | Organization/candidate ownership enforced by a composite FK |
| DocumentExtraction | One durable job/result per document; document deletion cascades |
| DocumentChunkSet | Immutable source/policy version of a successful extraction |
| DocumentChunk | Exact source slice; belongs to one chunk set |
| JobSearchProfile | Current explicit lexical query and revision; belongs to a job |
| JobMatchProfile/criterion | Current ordered independent criteria and revision |

Authentication precedes membership checks. Resource lookups are also scoped to
organization/candidate/job as appropriate. Non-members receive a hidden
`404 ORGANIZATION_NOT_FOUND`. UUID knowledge alone grants no access.

## Runtime

Compose runs PostgreSQL, a one-shot migration service, the API and two extraction
workers. API startup waits for successful migrations. PostgreSQL has no published
host port. The API publishes the development port, normally 8000.

The API and workers share a private document volume; workers mount it read-only.
Workers run with a read-only root, bounded tmpfs, dropped capabilities, process
limits and heartbeat health checks. Database-clock leases and conditional finish
updates reject stale results and prevent deleted jobs from being resurrected.

## Transactions and boundaries

- Application transitions lock the application before checking/updating its state.
- Document/chunk lifecycle lock order is document, then extraction.
- Profile replacement locks the parent job, including first profile creation.
- Search counts/pages and match profile/source/evidence are read in one SQL snapshot.
- Search timeouts are transaction-local and rollback before the connection is reused.
- Unique-constraint recovery rolls back, then rechecks the precise conflict and scope.

Filesystem writes and database commits are not a distributed atomic transaction.
Ambiguous outcomes preserve possibly referenced objects. Uploads acquire a
ROW EXCLUSIVE lock on candidate_documents before creating files and hold it
through the metadata commit. The private reconciliation CLI takes a conflicting
SHARE ROW EXCLUSIVE lock, then reads global references in READ COMMITTED.
Concurrent uploads remain compatible with each other. Maintenance briefly pauses
document writes; a busy guard fails after two seconds rather than deleting blindly.

Migration 0015 audits existing Application ownership while writes are locked.
It refuses mismatches without changing data, then adds validated composite FKs
and the required Job organization/id uniqueness. Historical FKs and data remain.

## Private storage operations

Run the operator CLI from the current smoke image, which shares the API's database
and private volume. It has no public HTTP endpoint and is not scheduled automatically.
Recreate every API writer with the current code before apply. Only these guarded
upload writers may publish files during reconciliation; pause external import,
restore or manual filesystem/metadata writers. The private root is trusted and
must not be changed or mounted elsewhere during a run.

```powershell
docker compose --profile smoke run --rm smoke python -m scripts.reconcile_documents
```

The default is dry-run with a seven-day grace period. Inventory is non-recursive,
bounded to 10,000 entries and 200 managed names; use exact repeated --key arguments
for a larger directory. Apply always requires an explicit list. Review the dry-run
for the same keys first, then append --apply to that command. --min-age-days accepts
1 through 365; age alone never overrides a reference or upload guard.

Only unreferenced UUID.pdf objects and .upload-XXXXXXXX temporary files can be
removed. References from every tenant and both ready/deleting states are retained.
Young files, symlinks, hardlinks, directories and unknown names are retained.
Each unlink rechecks the file identity, size, timestamps and link count. Filesystem
deletion runs synchronously under the DB guard so cancellation cannot abandon a
deleting thread after releasing that guard. Database failure stops further deletion.

The CLI streams a private operator JSON journal, followed by counts. Preserve that
journal: completed filesystem deletions cannot be rolled back by a later DB failure.
Exit 0 means the selected operation finished, 1 indicates failure or a missing
referenced object, 2 invalid arguments, and 130 interruption. A changed object is
kept for a fresh review. Missing referenced files require restore/investigation;
the tool does not delete their metadata or manufacture replacement contents.

This grace period applies to orphan cleanup. Ready resumes have no automatic
age-based retention policy; deletion still uses the authorized document lifecycle.
Hidden deleting rows are protected and can be retried through the existing API.
Production retention and backup expiration require a separate explicit policy.

References: [PostgreSQL locks](https://www.postgresql.org/docs/18/explicit-locking.html),
[foreign keys](https://www.postgresql.org/docs/18/ddl-constraints.html),
[Python filesystem operations](https://docs.python.org/3.12/library/os.html).

## Security

Passwords use Argon2 outside the event loop. JWTs use HS256 with subject/issued/expiry
claims. Validation errors, unexpected exceptions and parser errors avoid exposing
raw input, secrets or database parameters. Private source responses use no-store.
Production/staging reject debug mode and placeholder secrets.

Membership roles/invitations, refresh tokens, revocation, rate limits, malware
scanning, OCR and production observability are not implemented by these foundations.
