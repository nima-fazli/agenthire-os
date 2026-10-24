# Test the local agent workflow

Start from the repository root. Follow [Installation](INSTALLATION.md) for a
fresh checkout or an existing stack; retain the existing Compose project,
configuration and data volumes. A fresh demo can use
`python -m scripts.local_demo --start --seed`. For the complete product workflow,
including job setup, criteria and document search, read the [User Guide](USER_GUIDE.md).

## Replay walkthrough

1. Visit `http://localhost:8000/demo/`. Advance through five tools. Expect a
   deterministic replay banner, Python/PostgreSQL evidence and an unclear Docker
   finding. No model runs and the page cannot approve anything.
2. Open `/agent-center/`, sign in as `owner@agenthire.example.com` with the synthetic
   password `AgentHire-Demo-2026!`, then select **AgentHire Demo Lab**. Expect three
   incoming applications and three replay runs; poll until `waiting_approval`.
3. Inspect Alex. Expect positive Python/PostgreSQL quotes, unclear Docker and an
   employer approval action. Maya has unclear PostgreSQL because her resume negates
   that experience. Sam has no supported criteria. These are conservative evidence
   findings, not hiring scores.
4. Approve Alex's question. Expect `completed`, a local email in
   `http://localhost:8025`, and an approved question in Alex's portal. Before
   approval, that question must not be exposed to the applicant.
5. In `/portal/`, sign in as Alex with the same demo password. Submit:
   `I built Docker images for the Python services, maintained Dockerfiles and deployed containers in a test environment.`
   Expect the answer to be saved once and a fresh review to be queued. Its Docker
   finding should cite the answer. The original resume stays unchanged.
6. Ask **What is my application status?** using replay. Expect an answer from the
   applicant's own public status. Asking for other applicants or internal company
   reports must produce handoff, not private records.

The seeder is additive and idempotent. Re-running it does not reset an already
answered application. For a clean first walkthrough use a new applicant account;
do not delete the project's existing database or document volumes.

## New individual application

Create an account in the portal, using a fictional email such as
`new-applicant-01@example.com` and a password of at least 15 characters. No company
is required. Send a verification code, find that address in Mailpit and enter the
six-digit code in the portal. Choose the published demo job, enter a name and
upload one of `docs/demo-resumes/*.pdf` or paste its matching text file.

Submit in replay mode. Expect a receipt, an extraction job for a PDF, a new company
application and a review waiting for staff approval. The applicant sees only their
own application. Duplicate submission retries must not create a second application
for the same user/job pair. Submitted resume uploads are immutable.

## Actual model run

```sh
docker compose -f compose.yaml -f compose.agents.yaml --profile live-ai up -d --wait ollama
docker compose -f compose.yaml -f compose.agents.yaml exec ollama ollama pull qwen3:4b
```

After the download, select **Live local AI** and start a new review. Expect a new
live run, real nonzero reported tokens and an observed model digest. Existing
replay runs do not change mode. CPU inference can take minutes. A missing model,
timeout, malformed response, exhausted budget or source change must produce an
explicit failure; the system must not manufacture a replay success.

## Automated checks

```sh
uv sync --locked --no-install-project
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pytest -q -W error
node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs tests/recruiter_design.test.mjs tests/agents_ui.test.mjs
uv run --locked --no-sync python -m scripts.agent_evaluation --mode replay
uv run --locked --no-sync python -m scripts.agents_smoke
```

The last command requires the running seeded local stack and Mailpit. It creates
one fictional applicant and exercises real HTTP, OTP SMTP, submit/review/approval,
answer, applicant assistant and denied access to company reports. Use `--base-url`
if the original API port differs. SQLite tests do not validate native PostgreSQL
locking behavior; the repository also supplies the Docker CI smoke job.

For quality reports from the model installed in the local Compose stack:

```sh
python -m scripts.evaluate_agents --mode live --kind recruiter --repeat 1
python -m scripts.evaluate_agents --mode live --kind applicant --repeat 1
```

Each command retains its JSON under `reports/` before cleaning up its owned test
container. A failed model evaluation retains a report and exits unsuccessfully.
Use the complete corpus to assess the configured model; a subset is diagnostic.

## Failure and isolation checks

| Check | Expected result |
| --- | --- |
| Viewer tries publication/review/approval | Denied; read-only views remain available |
| Applicant requests another applicant or private report | 403/404, no private data |
| Criteria or source changes before approval | Stale approval rejected |
| Repeat identical submit or answer request | Original result; no duplicate logical email/action |
| Cancel during inference | Late result cannot revive the run |
| Stop and restart a worker mid-run | Resume from committed checkpoint after lease expiry; interrupted inference may repeat |
| Ollama unavailable / model absent | Explicit live failure; no replay fallback |
| SMTP unavailable | Delivery retries, then failed status; staff can retry scoped failed mail |
| Session expires while polling | Sign-out clears private UI; stale responses cannot reinsert it |
| Poll while typing a clarification | Unchanged cards retain the unsent answer |

## Diagnostics

```sh
docker compose -f compose.yaml -f compose.agents.yaml ps
docker compose -f compose.yaml -f compose.agents.yaml logs --tail 80 api agent-worker extraction-worker mailpit
```

Record the step, expected result, actual result and relevant error code. Use
fictional resumes when sharing logs. Do not share bearer tokens, OTPs, passwords,
private environment files or real applicant documents. Do not use `down -v` to
troubleshoot; it removes persistent volumes.
