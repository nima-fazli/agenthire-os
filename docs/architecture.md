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
| Application | Candidate/job relationship; unique job/candidate pair |
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
Ambiguous outcomes preserve possibly referenced objects. Crash-orphan reconciliation
and operational retention remain explicit future work.

Application ownership is currently checked in services. Its historic separate
candidate/job FKs do not enforce organization equality as a composite DB constraint.
Database hardening must use a new reviewed migration after auditing existing rows.

## Security

Passwords use Argon2 outside the event loop. JWTs use HS256 with subject/issued/expiry
claims. Validation errors, unexpected exceptions and parser errors avoid exposing
raw input, secrets or database parameters. Private source responses use no-store.
Production/staging reject debug mode and placeholder secrets.

Membership roles/invitations, refresh tokens, revocation, rate limits, malware
scanning, OCR and production observability are not implemented by these foundations.
