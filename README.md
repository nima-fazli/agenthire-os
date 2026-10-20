# AgentHire OS

A private recruiting workspace built with FastAPI, PostgreSQL/pgvector, and local
Ollama models. Manage jobs, candidates, applications, and private PDFs, then
review criterion evidence with exact source text, Unicode offsets, and hashes.
Recruiters retain responsibility for hiring decisions.

## Capabilities

- Organization-scoped records and database-enforced tenant relationships.
- Owner, recruiter, and viewer roles with revocable server-side sessions.
- One-use, email-bound invitations and current-password confirmations.
- Searchable lists, version-checked edits, and explicit application transitions.
- Private PDF storage, leased extraction workers, and immutable source chunks.
- Optional local semantic retrieval, hybrid ranking, and grounded evidence briefs.
- Source-bound citations, independent quality evaluation, and retained recovery tools.

The workspace, product messages, documentation, and generated operator receipts
use English. The workspace uses left-to-right layout and Gregorian dates.
Resume content remains Unicode-capable and is displayed without translation.
Grounded briefs default to English; the explicit legacy API language option is
preserved for compatibility. Multilingual test fixtures are evaluation data.

## Current checkpoint

The latest accepted main commit is
`261dd607b740a8d91d0bafabe2cb268c276c1c75` (completion stage 3).
The database head is `0017_access_sessions`.

Stage 4 adds broader AI quality evaluation and English workspace copy. Its
first native attempt passed Ruff, 1,879 Windows Python tests with five known
platform skips, and 70 Node tests. Docker then reported three failures because
its test image omitted source files required by acceptance checks. The test
image now includes those inputs and has a regression test reproducing the
three reported checks. Native Docker and live-model acceptance remain pending.

## Development

See [development](docs/development.md) for initial setup. The workspace is served
by the API at `/workspace/`. Keep the existing checkout and Git history.

```powershell
uv sync --locked --no-install-project
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pytest -rs -W error
node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs
```

Stage 4 acceptance verifies its cumulative source manifest, native checks,
isolated CI, live local models, cleanup, and the normal English workspace.
Without `--execute`, it prints a plan only.

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_acceptance
uv run --locked --no-sync python -m scripts.ai_quality_acceptance --execute --finalize
```

Execution requires the accepted stage 3 main history, schema 0017, a healthy
normal stack, and `AgentHire_OS_Recovery_Current.md` beside the repository.
After all gates pass, it rebuilds the normal API/smoke images, checks the English
HTTP shell, creates two scoped local commits, exports source, and appends a
receipt. It also updates `AgentHire_OS_Recovery_Complete.md` when that file exists.
It does not push or deploy to an external host.

## AI quality and operations

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_run
uv run --locked --no-sync python -m scripts.ai_quality_run --execute
uv run --locked --no-sync python -m scripts.source_bundle --execute
```

The quality runner owns a fresh isolated Compose project, publishes no host
ports, downloads the existing free local model tags into its own volume, and
removes only its resources. Normal model volumes and feature flags are retained.
The quality report remains outside Git even when evaluation fails.

A source ZIP excludes private configuration, PDFs, database contents, and Git
history. It is not a data backup. The retained stage 3 pre-migration backup uses
schema 0016 and must be restored with the accepted stage 2 source in an isolated
recovery checkout. Current backup/restore tooling expects schema 0017.

## Documentation

- [Architecture](docs/architecture.md)
- [Recruiting workflow](docs/recruiting-workflow.md)
- [Recruiter workspace](docs/recruiter-ui.md)
- [Semantic retrieval](docs/semantic.md)
- [Grounded briefs](docs/explanations.md)
- [AI quality](docs/ai-quality.md)
- [Operations](docs/operations.md)
- [Backups](docs/backups.md)
- [Recovery](docs/recovery.md)
- [Roadmap](docs/roadmap.md)
