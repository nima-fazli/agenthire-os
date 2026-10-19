# AgentHire OS

A private recruiting workspace and API built with FastAPI, PostgreSQL/pgvector
and locally hosted Ollama models. Scoped jobs, candidates and applications link
to private PDFs, extraction, immutable chunks and traceable criterion evidence.
Hiring decisions remain human; retrieval scores are not hiring probabilities.

## Engineering foundation

- Tenant-scoped queries and relational constraints protect related records.
- Extraction and embedding workers use leases, bounded attempts and fencing.
- Versioned provenance retains exact Unicode source offsets and hashes.
- Literal server search and bounded pages use consistent database snapshots.
- Version-checked edits prevent silent overwrites of another recruiter's work.
- Explicit transitions and confirmed PDF deletion remain human actions.
- Revocable bearer sessions and server-enforced roles protect every tenant route.
- Owner actions require the current password and serialize per organization.
- Operational and recovery gates use isolated, owned synthetic resources.

## Current checkpoint

The accepted stage 2 checkpoint is main
1865a7bae5815a083cfd6ad03a00ad202f08ebc6, with feature commit
ea1c46acde2eeaa13c4c0c19b4c0bde9dc01fcc3. Observed native acceptance passed
Windows Python 1763 plus 5 known platform skips, Docker Python 1768, Node 59,
Ruff, 33 isolated CI checks and owned cleanup, the normal workload, recruiting
HTTP smoke and healthy API plus two extraction workers. Its 381-file source
ZIP and every file hash were independently verified. The archive SHA-256 was
5505ca7d68fe13c00a9cf497ed7547ea4021f54905a9a7d3b3943d4958ff2ddf.

Stage 3 source adds access and sessions. Native acceptance of this source remains
pending. The migration advances 0016_document_embeddings to 0017_access_sessions.
Existing organizations give ownership to their earliest active member, or
earliest member if none is active. Other existing members become recruiters.
A new organization grants its creator ownership. Review owners after upgrading.

| Role | Read records/evidence | Edit recruiting data | Manage access |
| --- | --- | --- | --- |
| owner | Yes | Yes | Yes, with current password |
| recruiter | Yes | Yes | No |
| viewer | Yes | No | No |

Viewers can request read-only semantic retrieval and grounded explanations.
The owner panel lists 20 members per page and the latest 20 access events.
Invitations grant recruiter/viewer access, are bound to the recipient email,
expire after 48 hours, and are consumed once. Only the SHA-256 token digest is
stored. Send the code manually; this project does not send invitation emails.
Promotion to owner is an explicit, confirmed role change. The last active
owner cannot be demoted or removed.

Login creates a database session and a signed token with its session ID and
expiry. Every authenticated request checks the active user and unrevoked,
unexpired session. Each user has at most 10 active sessions; a new login
revokes the oldest excess sessions. Logout revokes only its own session.
Revoking other sessions and changing passwords require the current password;
password changes revoke every session, including the current one.
Five failed login/confirmation attempts per normalized email in 15 minutes
return a generic throttle response. Password work has two process-local slots.
This is not an edge-level rate limiter; deployment controls remain a release gate.

Pre-stage-3 tokens require a new login. The UI keeps tokens in memory and clears
private state on logout/expiry. Closing/reloading a page does not revoke its
server session; revoke it from another login or let it expire. A request already
accepted before a revocation may finish. UI role changes appear on refresh;
the server checks current roles on each new request.

Pinned dependencies, local model settings, encoding/dimensions and feature flags
retain their existing contracts. Live model quality, final bilingual design,
comprehensive browser QA and release deployment remain later stages.

## Run and verify

Initial setup is in [development](docs/development.md). The workspace is served
at /workspace/ by the API. Keep the existing checkout and Git history.

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs

The stage 3 driver validates all 40 complete delivered files against its manifest.
Default invocation only prints a plan. Execution runs native checks and isolated
CI, retains a private normal-data backup before building new normal images,
then migrates, checks drift and runs the real-stack access/recruiting HTTP smoke.

    uv run --locked --no-sync python -m scripts.access_acceptance
    uv run --locked --no-sync python -m scripts.access_acceptance --execute --finalize

Use accepted stage 2 main and the existing healthy normal stack. The driver
requires AgentHire_OS_Recovery_Current.md beside the repository. It creates or
uses the private AgentHire_OS_Backups directory beside the repository, preserves
the normal environment and two extraction replicas, and does not reset volumes.
The pre-migration capture deliberately uses the accepted stage 2 smoke image.
Keep that image until capture succeeds. A retry on schema 0017 requires the
verified retained 0016 backup receipt and unchanged environment.

The pre-migration backup is schema 0016: restore it with the accepted stage 2
source in a separate recovery checkout using the existing isolated restore
procedure. Keep the accepted stage 2 source ZIP and Git history. The stage 3
restore tool expects schema 0017; it does not automatically downgrade/migrate an
old backup or overwrite the normal database. See [backups](docs/backups.md).

Only after checks pass does finalization create two scoped local commits,
export committed source and append the native receipt to the personal recovery
file. Interrupted finalization can recognize its exact scoped commits. It does
not push. Historical stage 1/2 acceptance drivers remain pinned to their stages.

## Source and operational data

    uv run --locked --no-sync python -m scripts.source_bundle
    uv run --locked --no-sync python -m scripts.source_bundle --execute

Source exports include CI and per-file hashes; they exclude private configuration,
PDFs, Git history and personal recovery files. A source ZIP does not back up the
database, documents or Git history. See [source distribution](docs/source-distribution.md),
[backups](docs/backups.md) and [recovery](docs/recovery.md).

## Documentation

- [Architecture](docs/architecture.md)
- [Recruiting workflow](docs/recruiting-workflow.md)
- [Recruiter workspace](docs/recruiter-ui.md)
- [Verification history](docs/verification.md)
- [Operations](docs/operations.md)
- [Incident runbook](docs/operations-runbook.md)
- [Retrieval](docs/retrieval.md)
- [Semantic retrieval](docs/semantic.md)
- [Grounded explanations](docs/explanations.md)
- [Roadmap](docs/roadmap.md)
