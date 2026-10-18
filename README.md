# AgentHire OS

A private recruiting workspace and API built with FastAPI, PostgreSQL/pgvector
and locally hosted Ollama models. Scoped jobs, candidates and applications link
to private PDFs, extraction, immutable chunks and traceable criterion evidence.
Hiring decisions remain human; retrieval scores are not hiring probabilities.

## Engineering foundation

- Modular services own authorization and transaction boundaries.
- Tenant-scoped queries and relational constraints protect related records.
- Extraction and embedding workers use leases, bounded attempts and fencing.
- Versioned provenance retains exact Unicode source offsets and hashes.
- Literal server search and bounded pages use a consistent database snapshot.
- Version-checked edits prevent silent overwrites of another recruiter's work.
- Explicit transitions and confirmed PDF deletion remain human actions.
- Operational and recovery gates run on isolated, owned synthetic resources.

## Current checkpoint

The accepted stage 1 checkpoint is main
3b58176505d4b6d85d6d908cd268a03256f6e53c, with feature commit 8e4d7fa.
Observed native acceptance passed Windows Python 1720 plus 5 known platform
skips, Docker Python 1725, Node 46, Ruff, 33 CI checks and owned cleanup.
The normal stack and workload passed. The 363-file source ZIP was independently
hash-verified. Live v2 inference was not run because explanations were disabled.
See [stabilization](docs/stabilization.md) for the exact evidence boundary.

Stage 2 source completes the recruiting workflow and is delivered for native
acceptance. It includes paged organization/job/candidate/application search,
versioned editing, application transitions, confirmed PDF deletion and local
embedding controls. Full assigned citations up to 4000 Unicode code points now
render consistently with the v2 API. Native stage 2 results remain pending.

Schema remains 0016_document_embeddings. The dependency lock, local models,
embedding dimensions/encoding and feature flags retain their existing contracts.
The final bilingual design, access/session work and release remain later stages.

## Run and verify

Initial setup is documented in [development](docs/development.md). Keep the
existing development checkout and Git history for operational recovery tools.
The recruiter workspace is served at `/workspace/` by the normal API.

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs

The stage 2 acceptance driver validates copied source against its manifest.
Its default is a plan; execution runs native checks, isolated Docker CI and
normal-stack workflow checks. Finalization happens only after those checks pass:

    uv run --locked --no-sync python -m scripts.recruiting_acceptance
    uv run --locked --no-sync python -m scripts.recruiting_acceptance --execute --finalize

Finalization expects the accepted stage 1 main checkpoint, creates two scoped
local commits, exports their committed source and appends the observed receipt
to `AgentHire_OS_Recovery_Current.md` beside the repository. It does not push.
This pinned driver belongs to stage 2; later source changes require their own gate.

## Source and operational data

    uv run --locked --no-sync python -m scripts.source_bundle
    uv run --locked --no-sync python -m scripts.source_bundle --execute

Source exports include CI and a per-file hash manifest. They exclude private
configuration, PDFs, Git history and personal recovery files. A source ZIP is
not a database/document or Git-history backup. See [source distribution](docs/source-distribution.md),
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
