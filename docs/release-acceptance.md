# Release readiness and hosted acceptance

The accepted stage 5 main is
`c22791a48278450905e3361557d37ca06bd53816`. Its supplied source archive contains
420 files and matches every Git blob. The archive SHA-256 is
`b94fe3cf76a8d137767cbd9594cae3afe8db8b4ba8768b060ef76ebd26e2c996`.

No domain or hosting server is currently provisioned. Stage 6 therefore has a
local readiness gate and a separate, pending hosted acceptance gate. A passing
local report always says `stage_complete: false`. It does not establish HTTPS,
public availability, production capacity, or a hosted CI result.

## Local gate

Keep the existing checkout on `main`, private `.env`, database, documents,
accepted Git history, locked dependencies, model flags, and recovery files.
Use Python 3.12, Node 24, an installed Chrome or Edge, Docker Desktop with Linux
containers, and Docker Compose 2.24.4 or newer. The normal stack must already
have a healthy API, PostgreSQL, and two healthy extraction workers.

```powershell
uv run --locked --no-sync python -m scripts.release_acceptance
uv run --locked --no-sync python -m scripts.release_acceptance --execute
```

The first command validates the delivery manifest and prints a plan. It starts
no subprocess, creates no report, and does not require private configuration.
The second command performs these checks:

1. Require accepted stage 5 as an ancestor of `main`; reject unrelated tracked
   edits and untracked files. Verify the delivered file hashes and fingerprint
   all accepted source files plus the new release files.
2. Check the normal stack, then run whitespace, Ruff, Python with warnings as
   errors, and every Node test suite.
3. Run the existing isolated CI supervisor: fresh containers and volumes,
   migrations, schema drift checks, real HTTP/PDF/worker smoke tests, both
   recovery gates, and owned-resource cleanup.
4. Run the existing 22-check Chromium design fixture and verify its complete
   report, fingerprint, and cleanup. Its transport and identities are synthetic.
5. Rebuild the normal API/smoke images, refresh the English synthetic smoke
   workflow, and measure four synthetic PDF workflows with concurrency two.
   Retain latency distributions and sampled service memory/CPU aggregates.
6. Record Docker engine CPU/memory capacity, check the normal stack again,
   require byte-identical private configuration and unchanged complete source.

The API refresh restarts the API service. Run this local gate when a short local
interruption is acceptable. The workload creates and removes its own synthetic
records. Existing model flags stay unchanged, and no live model-quality run is
claimed. No normal volumes are removed and no normal database is restored.

Reports are written outside Git under
`../AgentHire_OS_Release_Reports/release-<random-id>/`: `browser.json`,
`workload.json`, and `release.json`. The release report records completed checks,
the failing checkpoint if any, Git state, complete-source fingerprint, and
hashes of its child reports. Report writes are exclusive. Keep the console log
with the reports when reviewing a failure.

The browser runner keeps its existing 17-file fingerprint scope. Stage 6 also
fingerprints the complete source independently; a changed historical document
does not reaccept stage 5. Historical acceptance manifests stay frozen. Their
unit tests use explicit current-content fixtures to test validator behavior.

The local command never commits, pushes, deploys, purchases infrastructure, or
marks stage 6 accepted. Commit the reviewed release candidate only after its
native checks pass. Then use `scripts.source_bundle` on the clean committed
tree; a source ZIP is separate from a private database/document backup.

## CI preparation

`Verify` runs Python/Ruff on Linux and Windows, all client suites on Node 24 on
both platforms, and the real Chromium fixture on Linux. The browser JSON is
retained for 14 days. The real-stack job depends on both matrices and runs all
five client suites inside its test image too. All external actions are pinned
to full commit IDs; credentials are not persisted by checkout.

Changing the workflow prepares hosted CI. A successful hosted run still needs
to be observed for the exact published candidate commit, including both Python
jobs, both client jobs, the browser artifact, and the real-stack cleanup result.
A local Docker run is not that evidence.

## Hosted acceptance still required

Before stage 6 can be accepted, select a host and public HTTPS address, then
verify all of the following against one identified release candidate:

- Hosted `Verify` run and all required jobs succeeded for its exact commit.
- A fresh host installation uses private production configuration, strong
  unique secrets, persistent storage, disabled debug, and a controlled public
  ingress. PostgreSQL and Ollama remain private; application access stays
  authenticated. Do not expose the development Compose port to the internet.
- HTTPS has a trusted certificate, correct hostname, and HTTP redirection.
  Check `/health`, `/ready`, `/workspace/`, sign-in, role restrictions, private
  PDFs, and an actual worker-backed synthetic recruiting flow through ingress.
- Measure bounded synthetic workload latency and resources on that host.
  Record its hardware and configuration; do not extrapolate local results to
  a production capacity or promise an unmeasured service-level objective.
- Verify installation, migration, retained backup, isolated restore, and
  restart on the selected host. Keep the original deployment intact during
  restore validation and preserve a rollback path before any schema upgrade.

Infrastructure configuration depends on the selected host. No untested generic
production stack or paid provider is included in this local delivery. Stage 7
portfolio work remains separate from these release acceptance requirements.

## Primary references

- [Node setup action](https://github.com/actions/setup-node/tree/949feb2413d6458794dcd2491c4babbbce0c15c1)
- [Artifact action](https://github.com/actions/upload-artifact/tree/b7c566a772e6b6bfb58ed0dc250532a479d7789f)
- [Ubuntu runner software](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
