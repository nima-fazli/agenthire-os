# Roadmap

Observed source, Git and user results take precedence over older recovery notes.
The accepted base is main 1865a7bae5815a083cfd6ad03a00ad202f08ebc6.
Personal recovery stays outside Git.

## Accepted history

| Checkpoint | Observed commits |
| --- | --- |
| Backend 0-12 | Through 6207ce6/708099d |
| Recruiter workspace 13-A | b604ec6/92c23fd |
| Operations 14-A | 31b7730/f8286de |
| Operations 14-B1 | 822c4c2/78987f4 |
| Bounded measurements 14-B2 | 09f232e/e2b42e9 |
| Worker healthcheck imports 14-B3 | 955ac94/c7d66c2 |
| Isolated recovery 15-A2 | ffe34dd/0777895 |
| Retained private backup/restore 15-A3 | c5e93e7/66de496 |
| Completion stage 1 stabilization | 8e4d7fa/3b58176 |
| Completion stage 2 recruiting workflow | ea1c46a/1865a7b |

Stage 1 native acceptance passed Windows Python 1720 with 5 known platform skips,
Docker Python 1725, Node 46, Ruff, all 33 isolated CI checks and owned cleanup.
Its 363-file export was independently hash-verified. Live explanations were off.

Stage 2 native acceptance passed Windows Python 1763 with 5 known platform skips,
Docker Python 1768, Node 59, Ruff, all 33 isolated CI checks and owned cleanup,
normal workload, recruiting HTTP contracts, API health and two healthy extraction
workers. The 381-file export and each file hash were independently verified.
The SHA-256 is 5505ca7d68fe13c00a9cf497ed7547ea4021f54905a9a7d3b3943d4958ff2ddf.
These checks did not establish live model quality or comprehensive browser QA.

## Seven-stage completion plan

Each stage is delivered and accepted as one coherent unit.

| Stage | State and completion condition |
| --- | --- |
| 1 Stabilize | Accepted: citations, regression gates, errors, source distribution and recovery |
| 2 Recruiting workflow | Accepted: pages/search, versioned editing, applications/transitions, confirmed PDF deletion, embeddings and stale-context controls |
| 3 Access and sessions | Source implementation: owner/recruiter/viewer roles, one-use email-bound invitations, current-password confirmations, last-owner protection, revocable sessions, password changes and backed-up migration; native acceptance pending |
| 4 AI quality | Pending: diverse reference data, adversarial/negative cases and reproducible local model evidence |
| 5 Final product design | Pending: English-first/Farsi-second translation, LTR/RTL, responsive layout and comprehensive browser/keyboard QA |
| 6 Release acceptance | Pending: hosted CI, HTTPS, deployment, load evidence and repeatable installation/migration/recovery |
| 7 Hiring portfolio | Pending: usable demo, synthetic data, short video, clear architecture and tradeoff explanation |

Five stages remain until stage 3 is natively accepted; four remain afterward.
Stage 3 intentionally adds migration 0017 over 0016. It keeps pinned dependencies,
models, dimensions, encoding and feature flags. Its native gate is
scripts.access_acceptance, with the 40-file manifest in
scripts/fixtures/access_stage3_manifest.json. See the README for operational
boundaries, invitation handling and pre-migration backup compatibility.

Paid services remain out of scope. Hosting is not selected. Scores do not
represent hiring probability. A tool-using agent with human approval remains
an optional additional stage; it has not been added to this plan. New
infrastructure requires a concrete workflow reason.
