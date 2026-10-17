# Verification

## Accepted 13-A checkpoint — 2026-10-14

The user's terminal and manual /workspace/ acceptance established this baseline.
Completion commits are b604ec6 and 92c23fd; the latest observed main tree is clean.

| Check | Historical observed result |
| --- | --- |
| Recruiter UI Python tests | 34 passed |
| Native Windows Python, warnings as errors | 1347 passed, 5 platform skips |
| Native Windows Node / Ruff | 42 passed / passed |
| Docker Python / Node / Ruff | 1352 passed / 42 passed / passed |
| Former isolated ci_verify | All 26 checks and separate cleanup exited 0 |
| Normal stack | API/PostgreSQL/extraction-worker healthy after rebuild |
| Alembic current / check | 0016_document_embeddings (head) / no drift |
| Normal recruiter_ui_smoke | Passed |
| Manual browser | User accepted the page |

The five Windows skips cover symlink privileges and real Linux/PDF tools; they
ran in the accepted Docker run. The multiline/trailing-comma import regression
was fixed. No stage 14-A result should be inferred from these historical checks.

## Stage 14-A acceptance

This delivery adds tests for storage probe cleanup, concurrency and cancellation;
migration mismatch, failed DB/storage and coalesced readiness; minimal public
responses; private diagnostics; request ID isolation, safe errors and streaming.
The existing UI assets, Node suites, lock file and migration graph are unchanged.

Run native Ruff, Python with warnings as errors, both Node suites, isolated CI,
normal image builds/startup, Alembic current/check and operations_smoke. Record
new platform-specific counts and actual exit codes. New user Docker/PostgreSQL
acceptance is pending; do not label an assistant-only unit run as real-stack proof.
No frontend redesign or new browser acceptance is part of this backend change.

## Repeatable runner

    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The current plan has 27 checks, including 16 smoke modules, then separate cleanup:

    docker_smoke
    candidate_smoke
    application_smoke
    candidate_document_smoke
    document_extraction_smoke
    document_chunk_smoke
    document_search_smoke
    job_retrieval_smoke
    job_matching_smoke
    retrieval_evaluation_smoke
    storage_integrity_smoke
    document_embeddings_smoke
    semantic_retrieval_smoke
    grounded_explanations_smoke
    recruiter_ui_smoke
    operations_smoke

Preflight rejects missing, empty or linked required UI files. Both Node suites
run in the Docker test image. CI owns its generated credentials and volumes;
cleanup touches only its isolated project. First failure stays authoritative,
and failed cleanup prevents success. Never remove development volumes to fix CI.

## Limits

CI embedding/chat gates use deterministic fixtures with real DB/HTTP contracts.
They do not prove current live-model quality, realistic load or production
capacity. DOM stubs and recruiter_ui_smoke are not automated browser tests.
Readiness does not imply worker or model readiness. Hosted GitHub Actions and
production deployment/backup restore remain unobserved. See operations.md for
cooperative timeout limits and the private operator workflow.
