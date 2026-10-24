# Installation and Local Verification

This is the setup guide for the current repository. It covers a fresh checkout,
an existing local installation, optional local models and verification. After
setup, follow the [complete user guide](USER_GUIDE.md) for the product workflow.

## Requirements

| Requirement | Used for |
| --- | --- |
| Docker Desktop or Docker Engine, running | PostgreSQL, API, workers, local email and optional Ollama |
| Docker Compose v2 | Starting the supplied services; full isolated CI checks require 2.24.4 or newer |
| Python 3.12 | The standard-library launcher and host-side development commands |
| Internet during initial setup | Container images, Python packages and optional model downloads |
| uv, optional for using the demo | Native development, lint, test and smoke commands |
| Node.js 24, optional for using the demo | Native browser-module tests; the Docker test image supplies Node itself |

No paid model API, cloud account, domain or external email provider is required.
Live inference consumes the local computer's CPU/memory. The default agent model
download is about 2.5 GB. Its Ollama container has a 6 GiB memory cap, in addition
to the resources needed by the database, API and workers; that cap is not a
guarantee that a particular computer has sufficient memory. Start with Replay
if you want to learn the workflow without loading a model.

## Open the repository root

Clone or download the repository, then open a terminal in the directory containing
`compose.yaml`, `compose.agents.yaml`, `pyproject.toml` and `scripts/`.
Commands below run from that directory. On Windows, PowerShell is supported.

```sh
python --version
docker compose version
```

Use a Python 3.12 interpreter. If Windows resolves `python` to another version,
use `py -3.12` in place of `python` for the launcher commands below.

## Keep the same Compose project

Compose project selection determines which named database, document, model and
Mailpit volumes the commands use. An existing installation started with
`-p your-project` must keep that exact project name.

Inspect existing project names with:

```sh
docker compose ls
```

Either add `-p` with that same name to every Compose command, or set
`COMPOSE_PROJECT_NAME` in the terminal before running the commands and launcher.
For example, replace `your-existing-project` with the actual existing name:

```powershell
$env:COMPOSE_PROJECT_NAME = "your-existing-project"
```

In Bash:

```sh
export COMPOSE_PROJECT_NAME="your-existing-project"
```

For a new checkout, the normal directory-based project name is sufficient.
A new terminal needs the same project selection again if it was set only in
the previous terminal. Changing the project name can select a different empty
database and model cache, even while the old volumes still exist.

## Start the local demo

With Docker running and the correct project selected:

```sh
python -m scripts.local_demo --start --seed
docker compose -f compose.yaml -f compose.agents.yaml ps -a
```

The launcher:

1. Creates `.env` with generated local database/JWT secrets only when that file
   is missing. Existing configuration is retained.
2. Builds and starts the base services and the agent/Mailpit additions.
3. Applies the schema through the one-shot migration service.
4. Adds the fictional **AgentHire Demo Lab**, a Backend Engineer job and three
   synthetic applicant submissions. Existing accounts are not reset.

The first build can take several minutes. The expected long-running core
services are `postgres`, `api`, `extraction-worker`, `agent-worker` and `mailpit`.
They should become Healthy. `migrate` should finish successfully; `Exited (0)`
is normal. Ollama is optional at this stage.

| Destination | Address |
| --- | --- |
| Recruiter workspace | http://localhost:8000/workspace/ |
| Agent Center | http://localhost:8000/agent-center/ |
| Applicant Portal | http://localhost:8000/portal/ |
| Recorded replay | http://localhost:8000/demo/ |
| Local email inbox | http://localhost:8025 |
| API documentation | http://localhost:8000/docs |
| API readiness | http://localhost:8000/ready |

Use `owner@agenthire.example.com` for the demo employer and
`alex@agenthire.example.com`, `maya@agenthire.example.com` or
`sam@agenthire.example.com` for the demo applicants. Their synthetic local
password is `AgentHire-Demo-2026!`.

Start with [Try the seeded demo](USER_GUIDE.md#try-the-seeded-demo). Repeating
the seed command retains already answered questions and prior demo progress.

## Start without demo data

For an installation where you want to create the accounts and company yourself:

```sh
python -m scripts.local_demo --start
```

Omitting `--seed` adds no demo company. It also does not remove any records that
already exist in the selected project. Follow
[Create an organization and job](USER_GUIDE.md#create-an-organization-and-job).

To add the sample data later while the stack is running:

```sh
python -m scripts.local_demo --seed
```

## Enable live agent inference

Run Replay first to establish that the product workflow is available. Then start
the local model service:

```sh
docker compose -f compose.yaml -f compose.agents.yaml --profile live-ai up -d --wait --wait-timeout 300 ollama
docker compose -f compose.yaml -f compose.agents.yaml exec -T ollama ollama list
```

If the configured agent model is absent from that list, download it:

```sh
docker compose -f compose.yaml -f compose.agents.yaml exec -T ollama ollama pull qwen3:4b
```

The default configured model is `qwen3:4b`. If you change
`AGENTHIRE_AGENT_MODEL`, download the selected tag and recreate both `api` and
`agent-worker` with the same configuration. Model compatibility and quality
must be evaluated for that selection; a successful download alone does not
establish either.

In Agent Center choose **Live local AI — Ollama**, then start a new review.
The applicant portal also has an execution-mode selector for new work. A
successful live run shows a model digest and actual reported model tokens.
Old replay runs keep their original mode. CPU inference may take minutes;
missing models, timeouts and invalid output produce explicit errors.

Keep using the same Compose project when checking `ollama list`. A fresh
project's separate model volume may be empty even if another project already
downloaded the model. Resetting only a database does not itself delete a model
volume.

## Enable semantic retrieval and Grounded briefs

These workspace features are separate from Agent Center's execution-mode
selector and are disabled by default.

| Feature | Local model | API flag | Additional worker |
| --- | --- | --- | --- |
| Agent reviews and applicant assistant in Live | `qwen3:4b` by default | Agents enabled by `compose.agents.yaml` | `agent-worker` |
| Semantic/Hybrid candidate retrieval | `qwen3-embedding:0.6b` | `AGENTHIRE_SEMANTIC_ENABLED=true` | `embedding-worker` |
| Grounded brief | `qwen3:0.6b` | `AGENTHIRE_EXPLANATIONS_ENABLED=true` | API calls the local model |

For both workspace features, add or update these lines in the existing `.env`;
retain its other configuration and secrets:

```dotenv
AGENTHIRE_SEMANTIC_ENABLED=true
AGENTHIRE_EXPLANATIONS_ENABLED=true
```

For a temporary PowerShell session instead:

```powershell
$env:AGENTHIRE_SEMANTIC_ENABLED = "true"
$env:AGENTHIRE_EXPLANATIONS_ENABLED = "true"
```

In Bash:

```sh
export AGENTHIRE_SEMANTIC_ENABLED=true
export AGENTHIRE_EXPLANATIONS_ENABLED=true
```

Terminal values override corresponding `.env` values. Keep the effective
settings consistent across restarts. Start Ollama as shown above, check its
model list, and pull the models needed for the enabled features:

```sh
docker compose -f compose.yaml -f compose.agents.yaml exec -T ollama ollama pull qwen3-embedding:0.6b
docker compose -f compose.yaml -f compose.agents.yaml exec -T ollama ollama pull qwen3:0.6b
docker compose -f compose.yaml -f compose.agents.yaml --profile semantic up -d --wait --wait-timeout 300 api embedding-worker
```

If you need only one feature, enable its flag and install its model. The
embedding worker is needed for semantic retrieval, not Grounded brief alone.
For a brief-only configuration, recreate `api` after changing its flag.

Expected result: API and the required workers become Healthy. In Workspace,
extract a PDF, build chunks and explicitly request embeddings before expecting
semantic results. The [user guide](USER_GUIDE.md#manage-resumes-and-processing)
explains those controls and the separate portal extraction path.

## Existing installations and source updates

Keep the existing `.env`, Compose project selection and named volumes. Apply
the intended source update through your normal Git review workflow. After a
runtime-code update, rebuild the affected services using both Compose files.
For the default Replay stack:

```sh
python -m scripts.local_demo --start
```

For a stack using the optional semantic services:

```sh
docker compose -f compose.yaml -f compose.agents.yaml --profile semantic up -d --build --wait --wait-timeout 300 api extraction-worker agent-worker embedding-worker
```

This also uses the migration service dependency. Keep any enabled flags and
model selection consistent with the existing installation. A documentation-only
update does not require rebuilding the API.

The repository's current setup uses its own launcher and Compose files. A
separate historical update-installer archive is not required for a fresh clone.
Historical acceptance and backup tools have their own scope; see
[local-agent operation](local-agents.md#local-operation-and-honest-evaluation)
before using older recovery orchestration on an agent-enabled stack.

## Change the local API port

Update `AGENTHIRE_API_PORT` in `.env`, for example to `8080`, or set it in the
current terminal. Then recreate API with the same project and feature settings:

```sh
docker compose -f compose.yaml -f compose.agents.yaml up -d --wait api
docker compose -f compose.yaml -f compose.agents.yaml port api 8000
```

The container still listens on 8000. With a host port of 8080, the second
command should report `127.0.0.1:8080`. Replace 8000 with your host port in browser
addresses and smoke-test base URLs. The supplied API and Mailpit ports are bound
to the local host; this guide describes a local installation.

## Verification

### Reproducible Linux test environment

From the repository root, with Docker running:

```sh
docker compose -f compose.yaml -f compose.agents.yaml --profile test run --rm --build --no-deps test pytest -q -W error
```

This builds the test target, including its Python/Node dependencies and PDF tools,
then runs pytest with warnings treated as errors. The test service has no
application database or document-volume mounts. The first build needs network
access for dependencies. Native Windows tests can skip Linux-specific PDF and
symlink checks; the Linux container covers those platform requirements.

If a build fails resolving a package-download host, the tests have not started.
Check that network path and retry the cached build once. A persistent download
failure needs network diagnosis rather than a dependency change or volume reset.

### Native development checks

With uv available and Python 3.12 selected:

```sh
uv sync --locked --no-install-project
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pytest -q -W error
node --test tests/recruiter_ui.test.mjs tests/recruiter_notifications.test.mjs tests/recruiter_api_errors.test.mjs tests/recruiter_workflow.test.mjs tests/recruiter_design.test.mjs tests/agents_ui.test.mjs
```

The explicit Node command needs Node 24 on the host. Prefer the Docker test
environment when host-specific configuration or PDF tools differ. Test counts
can grow; the expected result is a successful exit with no failures.

### Running-stack workflow check

After starting and seeding the local stack:

```sh
uv run --locked --no-sync python -m scripts.agents_smoke
```

For a different host port:

```sh
uv run --locked --no-sync python -m scripts.agents_smoke --base-url http://localhost:8080
```

This creates a fictional applicant and exercises real HTTP, local verification
mail, submission, review, approval, clarification, the applicant assistant and
private-data boundaries. It needs the seeded company and running Mailpit/workers.

Full independent stack verification is available through:

```sh
uv run --locked --no-sync python -m scripts.ci_verify
```

That command uses a separate owned CI project and test resources. It is a broader
integration check, not an assertion that hosted CI has already passed. See
[development](development.md) and [release acceptance](release-acceptance.md).

### Separate actual-model evaluation

With Ollama and the configured agent model available in the running stack:

```sh
python -m scripts.evaluate_agents --mode live --kind recruiter --repeat 1
python -m scripts.evaluate_agents --mode live --kind applicant --repeat 1
```

Reports retain model identity, usage, timing, errors and corpus scope. Synthetic
Replay correctness and passing unit tests do not establish general live-model
hiring quality. See [agent verification](agents-verification.md).

## Routine diagnostics and data retention

```sh
docker compose -f compose.yaml -f compose.agents.yaml ps -a
docker compose -f compose.yaml -f compose.agents.yaml logs --tail 80 api agent-worker extraction-worker mailpit
docker compose -f compose.yaml -f compose.agents.yaml exec -T ollama ollama list
```

The last command is relevant only after the optional model service has been
started. Record the safe error code and the affected service before changing
configuration. The [user guide](USER_GUIDE.md#troubleshooting) maps common
symptoms to the corresponding UI action or service.

Database records, uploaded documents, model files and Mailpit data use separate
named volumes. Normal service recreation retains them. `down -v` removes
persistent volumes and is not a troubleshooting step in this guide. Keep
private configuration and real applicant data out of public issue reports and
release archives. See [source distribution](source-distribution.md) for creating
a clean source archive from committed files.
