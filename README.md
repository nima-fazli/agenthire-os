# AgentHire OS

Tenant-scoped recruiting, private PDFs and local CPU models. Backend stages
through 12 are committed. Stage 13-A workspace and popup feedback passed user
verification on 2026-10-14 and are ready for their scoped completion commits.
The last observed user HEAD before those commits is main 4db6cb6.

/workspace/ supports account access, organizations/jobs, profiles, candidates,
retrieval, source evidence and private PDF processing. The current shell is
Persian. The final English-first bilingual redesign starts when the user requests it.

## Check

    uv sync --locked --no-install-project
    uv run --locked --no-sync ruff check .
    uv run --locked --no-sync pytest -rs -W error
    node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs
    uv run --locked --no-sync python -m scripts.ci_verify

Accepted 13-A results: Windows Python 1347 passed / 5 platform skips; Docker
Python 1352 passed / no skips; Node 42 passed on both platforms; Ruff passed.
The isolated runner passed all 26 checks, including 15 smokes, and separate cleanup.
The normal stack was rebuilt and healthy; Alembic reported 0016_document_embeddings
at head with no drift; recruiter_ui_smoke passed. The user accepted the browser page.
These results do not establish hosted Actions, production deployment, broad model
quality or automated browser coverage. CI model gates use deterministic fixtures.

See [Verification](docs/verification.md), [Recruiter workspace](docs/recruiter-ui.md),
[Roadmap](docs/roadmap.md) and [Recovery checkpoint](docs/recovery.md).
