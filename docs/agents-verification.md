# Verification scope — local agents update

Observed on 2026-10-21 against this update's source. Historical release receipts
are not current deployment evidence.

| Check | Observed result |
| --- | --- |
| Full Python suite, `pytest -q -W error` | 2,061 passed; 25 subtests passed; no failures |
| Six Node client suites | 93 passed; no failures or skips |
| Ruff check | Passed |
| New agent Python tests, included above | 46 passed |
| New client transport/card tests, included above | 4 passed |
| Three synthetic PDF fixtures | Visually inspected; actual Poppler extraction and expected review outcomes passed |
| Public recorded demo in Chrome | Five steps, expanded source quote, concise summary and clarification observed |
| Guarded bundle installer | Fresh baseline copy: preflight, apply, payload hashes and repeat-install checked; private sentinel files retained |
| Native Docker/PostgreSQL/Mailpit stack | Not executed here; Docker Engine unavailable. Supplied smoke and CI job must run on a Docker host |
| Windows execution and hardware sizing | Not executed here; guarded updater and PowerShell walkthrough supplied |

The installer package test uses an empty disposable source copy and explicitly
skips a real database dump there. Tests separately cover backup-failure abort and
file rollback. This does not establish that a live database backup/restore works on
the user's machine. The user installation path requires a database backup and
never instructs skipping it.

The domain tests exercise real SQLAlchemy sessions with SQLite foreign keys,
actual API permission boundaries, account verification, immutable finalization,
clarification approval/reply, worker fencing/cancellation, source staleness and
outbox logical keys. The SMTP test uses a real loopback capture server. SQLite
does not establish PostgreSQL `SKIP LOCKED` or multi-process contention behavior.

## Actual local model observations

Verified local **Ollama 0.40.3**, **qwen3:4b**, CPU inference, four configured model
threads. The environment reported an 8 GiB memory limit and eight CPU quota units.
These are test conditions, not a minimum specification for all machines.

| Profile | Full synthetic corpus | Completion | Expected outcome accuracy | Median elapsed time |
| --- | --- | --- | --- | --- |
| Recruiter | 8 cases, one trial each | 8/8 | 24/24 criterion assessments | 75.30 seconds |
| Applicant | 3 cases, one trial each | 3/3 | 3/3 response topics | 9.03 seconds |

The recruiter cases cover clear evidence, missing deployment experience, English
negation, Persian negation, unrelated experience, prompt injection, evidence after
many repeated lines and Unicode offsets. The fixed-query/top-five retrieval
baseline scored 22/24 criterion assessments on that same small corpus. This is a
diagnostic comparison, not a statistically supported general advantage claim.

The applicant cases cover own status, public job details and a private-data
request that must hand off. There was one trial per live case, so variability
across repeated model calls has not been established.

Both reports have an unchanged runtime hash, a validated 64-character model
identity, actual nonzero reported usage and complete-corpus acceptance under the
stated thresholds. This acceptance applies only to those synthetic cases and the
observed configuration. It does not establish semantic entailment, truthful skill
claims, unbiased hiring, production readiness or correctness for arbitrary models.

- [Recruiter live report](evaluations/agent-live-recruiter.json)
- [Applicant live report](evaluations/agent-live-applicant.json)
- [Recruiter replay report](evaluations/agent-replay-recruiter.json)
- [Applicant replay report](evaluations/agent-replay-applicant.json)

Replay reports use two trials per case, pass their deterministic contract and
explicitly have `live_quality_accepted: false`. The runtime hash covers the model
transport, scoped tools, action schemas, worker and evaluator. Native storage,
SMTP, authorization and migration checks are separate from model evaluation.

## Remaining host checks

Run the [walkthrough](agents-testing.md), including `scripts.agents_smoke`, on the
actual Docker stack. The supplied GitHub workflow starts an owned local stack,
exercises the actual HTTP/workers/verification SMTP flow and runs `alembic check`.
Supplying a workflow is not evidence that GitHub Actions has already run it.

The [Persian guide](fa/INSTALL_AND_TEST_FA.md) documents installation, expected
results, optional live-model setup and diagnostics without removing data volumes.
