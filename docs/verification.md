# Verification

The GitHub workflow has native Linux/Windows jobs and a dependent Ubuntu Docker
job. It runs on pushes/PRs to main and manual dispatch. It uses read-only repository
permission, immutable action SHAs, no stored deployment credentials and no deploy step.
Dependabot proposes weekly action updates; review them before merging.

## Docker acceptance sequence

`python -m scripts.ci_verify` executes these checks in a fresh isolated project:

1. Compose validation and PostgreSQL image availability.
2. Test-image build, full pytest and Ruff inside Linux.
3. API/migration/worker and smoke-image builds.
4. Healthy API/PostgreSQL and two extraction workers after migrations.
5. Current Alembic head and schema drift check.
6. All smoke modules, in order, followed by CI-volume/container/network cleanup.

| Module | Coverage |
| --- | --- |
| docker_smoke | Authentication, membership-scoped organizations and jobs |
| candidate_smoke | Candidate operations and tenant isolation |
| application_smoke | Transition graph, retries, terminal states and race |
| candidate_document_smoke | Private PDFs, deduplication, ownership and deletion |
| document_extraction_smoke | Parser limits, durable leases, recovery and fencing |
| document_chunk_smoke | Atomic versions, source reconstruction and deletion races |
| document_search_smoke | Real GIN/latest indexes, normalization and deadlines |
| job_retrieval_smoke | Candidate grouping, witness stability, profiles and pagination |
| job_matching_smoke | Independent criteria, source readiness and snapshot consistency |
| retrieval_evaluation_smoke | Reference metrics, provenance, tenant exclusion and quality gate |

Each command has a deadline. A timeout becomes exit 124, inability to launch a child
becomes 127, and interruption becomes 130. The first check's failure is preserved
if cleanup also fails. Failed cleanup prevents an otherwise successful result.
The summary includes only check names and exit codes; child tools stream their
normal output. GitHub also receives the summary in its job summary pane.

## Acceptance evidence

Do not infer hosted CI success from unit tests or a dry run. Record the real Docker
output and, once a remote exists and a workflow runs, its actual run URL/status.
The script's success line is:

```text
[success] Isolated Docker verification passed and cleaned up.
```

## Troubleshooting

- Compose older than 2.24.4 cannot apply the override; update Docker Desktop/Compose.
- If `deb.debian.org` fails to resolve during apt, fix Docker's network/resolver and
  retry the failed build. Application unit tests cannot prove network availability.
- A stale schema must be upgraded using the current migration image before drift
  checking. The isolated runner starts from a new database and applies the full chain.
- Expected negative smoke checks, such as an extraction marked failed for a broken
  PDF, are successful assertions when the module ends with `[success]`.
- An interrupted run may need its printed CI project's resources inspected. Never
  use a volume-deleting command on the normal development project to fix CI.

References: [Compose merge/override](https://docs.docker.com/reference/compose-file/merge/),
[GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[setup-uv](https://github.com/astral-sh/setup-uv).
