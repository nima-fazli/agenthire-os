# Roadmap

Observed source, Git and user results take precedence over older recovery notes.
The accepted base is main 3b58176505d4b6d85d6d908cd268a03256f6e53c.
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

Stage 1 native acceptance on 2026-10-18 passed Windows Python 1720 with 5
known platform skips, Docker Python 1725, Node 46, Ruff, all 33 isolated CI
checks and cleanup, the normal workload and stack health. Its source export
contained 363 files with an independently checked archive hash. Explanations
were disabled, so live v2 model acceptance was recorded as not run.

## Seven-stage completion plan

Each stage is delivered and accepted as one coherent unit.

| Stage | State and completion condition |
| --- | --- |
| 1 Stabilize | Accepted: context-preserving citations, regression gates, client errors, complete source distribution and recovery |
| 2 Recruiting workflow | Source delivered; native acceptance pending: applications/transitions, versioned editing, confirmed PDF deletion, embedding controls, server pages/search and stale-context handling |
| 3 Access and sessions | Pending: needed roles/invites, session lifecycle and sensitive-operation controls |
| 4 AI quality | Pending: diverse reference data, adversarial/negative cases and reproducible model evidence |
| 5 Final product design | Pending: English-first/Farsi-second translation, LTR/RTL, responsive layout and comprehensive browser/keyboard QA |
| 6 Release acceptance | Pending: hosted CI, HTTPS, deployment, load evidence and repeatable installation/migration/recovery |
| 7 Hiring portfolio | Pending: usable demo, synthetic data, short video, clear architecture and tradeoff explanation |

Six stages remain until stage 2 is natively accepted; five remain afterward.
Stage 2 retains schema 0016, pinned dependencies, models and encoding. See
[recruiting-workflow.md](recruiting-workflow.md) for its contract and gate.

Paid services remain out of scope. Hosting is not selected. Scores do not
represent hiring probability. A tool-using agent with human approval remains
an optional additional stage; it has not been added to this plan. New
infrastructure requires a concrete workflow reason.
