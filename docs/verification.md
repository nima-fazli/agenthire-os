# Verification

## Accepted 13-A checkpoint — 2026-10-14

Evidence: the user's latest terminal archive and manual acceptance of /workspace/.
The last observed Git HEAD before the completion commits is main 4db6cb6.

| Check | Observed result |
| --- | --- |
| Recruiter UI Python tests | 34 passed |
| Native Windows Python, warnings as errors | 1347 passed, 5 platform skips |
| Native Windows Node | 42 passed, no skips |
| Native Windows Ruff | Passed |
| Docker Python | 1352 passed, no skips |
| Docker Node | 42 passed, no skips |
| Docker Ruff | Passed |
| Isolated ci_verify | All 26 checks and separate cleanup exited 0 |
| Normal stack | API/PostgreSQL/extraction-worker healthy after rebuild |
| Alembic current | 0016_document_embeddings (head) |
| Alembic check | No new upgrade operations detected |
| Normal recruiter_ui_smoke | Passed |
| Manual browser | User checked the page and accepted it |

The five native skips cover Windows symlink privileges and real Linux/PDF tools.
They all ran in Docker. The trailing-comma import-test regression is fixed;
missing exports and malformed bindings still fail. No migration or uv.lock changed.

## Repeatable runner

    uv run --locked --no-sync python -m scripts.ci_verify --dry-run
    uv run --locked --no-sync python -m scripts.ci_verify

The plan has 26 checks, including these 15 smoke modules, then separate cleanup:

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

Preflight rejects missing, empty or linked required UI files. Both Node suites
run in the Docker test image. The isolated stack owns its generated credentials
and volumes; cleanup touches only that project. The first failure stays authoritative,
and failed cleanup prevents success. Development volumes must not be removed to fix CI.

## Limits

CI embedding/chat gates used deterministic fixtures with real DB/HTTP contracts.
This run does not prove current live-model quality, realistic load or production
capacity. DOM stubs and recruiter_ui_smoke are not automated browser tests.
Manual acceptance does not establish comprehensive keyboard/narrow-screen coverage.
Hosted GitHub Actions and production deployment/backup restore remain unobserved.
Record actual new hashes from git log; no post-commit hash is inferred here.
