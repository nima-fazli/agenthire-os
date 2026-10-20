# AgentHire OS

A private recruiting workspace built with FastAPI, PostgreSQL/pgvector, and local
Ollama models. Manage jobs, candidates, applications, and private PDFs, then
review criterion evidence against original source text, Unicode offsets, and
hashes. Recruiters retain responsibility for hiring decisions.

## Capabilities

- Organization-scoped records with database-enforced tenant relationships.
- Owner, recruiter, and viewer roles with revocable server-side sessions.
- One-use, email-bound invitations and current-password confirmations.
- Server-paged lists, version-checked edits, and explicit application transitions.
- Private PDFs, leased extraction workers, and immutable source chunks.
- Optional local semantic retrieval, hybrid ranking, and grounded evidence briefs.
- Independent AI quality checks and retained backup/isolated restore tools.
- Five focused workspace sections, responsive layouts, and keyboard navigation.

The product, documentation, comments, and new operational receipts use English.
The workspace is left-to-right. Resume content remains Unicode-capable and is
not translated. Credentials remain in page memory only.

## Checkpoint and release readiness

The accepted stage 5 main is `c22791a48278450905e3361557d37ca06bd53816`.
Native design acceptance passed regression, isolated CI, both recovery gates,
22 Chromium checks, normal workspace refresh, and cleanup. Stage 4 separately
accepted live local-model quality. Schema remains `0017_access_sessions`.
A source ZIP is not a database or document backup.

Stage 6 currently prepares local release verification and hosted CI. No domain
or hosting server is provisioned. Local results cannot establish hosted HTTPS,
deployment, or production capacity. See [release acceptance](docs/release-acceptance.md).

## Development and verification

The API serves the workspace at `/workspace/`. Keep the existing checkout,
private environment, Git history, database, and locked dependencies.

```powershell
uv sync --locked --no-install-project
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pytest -rs -W error
node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs tests/recruiter_design.test.mjs
uv run --locked --no-sync python -m scripts.release_acceptance
uv run --locked --no-sync python -m scripts.release_acceptance --execute
```

Native design acceptance also requires an installed Chrome or Edge and Node 24.
The browser runner uses an isolated temporary profile and synthetic transport;
it does not open an existing browser profile or connect to the normal database.
Set `AGENTHIRE_BROWSER_BINARY` to an installed Chromium executable if automatic
location fails. No npm install or frontend build is required.

Earlier acceptance drivers remain bound to their historical delivery hashes.
Use the stage 6 local driver for this source. It verifies the complete source,
native regression, isolated real-stack CI/recovery, browser checks, normal
English HTTP smoke, bounded workload/resources, and health before/after.
It writes outside-Git reports and never commits, pushes, deploys, or marks the
hosted release accepted. The API refresh briefly restarts the local API.

## AI quality and operations

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_run
uv run --locked --no-sync python -m scripts.ai_quality_run --execute
uv run --locked --no-sync python -m scripts.source_bundle --execute
```

Quality execution owns a generated isolated Compose project and removes only
its resources. Normal model flags remain false by default. Design work does not
change model tags, inference settings, migrations, or dependency pins.
The pre-stage-3 schema 0016 backup requires accepted stage 2 source for an
isolated restore; current tools expect schema 0017.

## Documentation

- [Architecture](docs/architecture.md)
- [Recruiting workflow](docs/recruiting-workflow.md)
- [Workspace behavior](docs/recruiter-ui.md)
- [Product design and acceptance](docs/product-design.md)
- [Release readiness and hosted acceptance](docs/release-acceptance.md)
- [Semantic retrieval](docs/semantic.md)
- [Grounded briefs](docs/explanations.md)
- [AI quality](docs/ai-quality.md)
- [Operations](docs/operations.md)
- [Backups](docs/backups.md)
- [Recovery](docs/recovery.md)
- [Roadmap](docs/roadmap.md)
