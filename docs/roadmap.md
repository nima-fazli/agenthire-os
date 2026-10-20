# Completion roadmap

Observed source, Git history, and execution receipts take precedence over older
notes. The latest accepted main base is
`c22791a48278450905e3361557d37ca06bd53816` (completion stage 5). Personal recovery files stay outside Git.

## Accepted history

| Checkpoint | Recorded commits |
| --- | --- |
| Backend stages 0-12 | Through 6207ce6 / 708099d |
| Recruiter workspace 13-A | b604ec6 / 92c23fd |
| Operations 14-A | 31b7730 / f8286de |
| Operations 14-B1 | 822c4c2 / 78987f4 |
| Bounded measurements 14-B2 | 09f232e / e2b42e9 |
| Worker health imports 14-B3 | 955ac94 / c7d66c2 |
| Isolated recovery 15-A2 | ffe34dd / 0777895 |
| Retained backup/restore 15-A3 | c5e93e7 / 66de496 |
| Completion stage 1 | 8e4d7fa / 3b58176 |
| Completion stage 2 | ea1c46a / 1865a7b |
| Completion stage 3 | f680e83 / 261dd60 |
| Completion stage 4 | 9f99e7c / 160fc05 |
| Completion stage 5 | 5dcf425 / c22791a |

Stage 3 native acceptance passed 1,806 Windows Python tests with five known
platform skips, 1,811 Docker Python tests, 70 native Node tests, Ruff, 33 CI steps
plus cleanup, the normal recruiting/access workflow, migration 0017, and health
checks for the API and two extraction workers. Its reported source ZIP contains
389 files; the supplied archive and all manifest hashes have been verified.

## Seven-stage completion plan

| Stage | Status and completion condition |
| --- | --- |
| 1 Stabilization | Accepted: citation context, regression/error gates, source distribution, recovery |
| 2 Recruiting workflow | Accepted: server pages/search, versioned editing, applications/transitions, confirmed PDF deletion, embeddings, stale-context controls |
| 3 Access and sessions | Accepted: owner/recruiter/viewer roles, invitations, current-password confirmations, last-owner protection, revocable sessions, backed-up migration |
| 4 AI quality | Accepted: independent quality protocol, isolated live evaluation, restore correction, English copy, normal stack checks and cleanup |
| 5 Final product design | Accepted: focused English sections, responsive layouts, accessible navigation, native regression, real Chromium checks and isolated CI/recovery |
| 6 Release acceptance | In progress: local readiness/reporting and complete client CI prepared; native execution and hosted CI/HTTPS/deployment/workload/install/recovery evidence pending |
| 7 Hiring portfolio | Remaining: usable demo, synthetic data, short video, clear architecture and engineering tradeoffs |

Two stages remain. No domain or hosting server is provisioned. Local release
readiness does not complete stage 6; see release-acceptance.md.

Stage 4 native acceptance is recorded in the supplied 2026-10-20 console log:
34 isolated CI checks and cleanup passed, both recovery gates passed, live
quality passed, the normal English workspace was refreshed, and main was clean.
The 412-file source archive SHA-256 is
`f7daab229e669d61715b452870f2a0a2c2872f5beafb9166f002f79dc0901c8c`.
Stage 5 native acceptance passed 1,926 Windows Python tests with five known
platform skips, 1,931 Docker Python tests, 80 native Node tests, Ruff, all 35
isolated CI steps including cleanup, both recovery gates, 22 Chromium checks,
and normal English workspace/health checks. Its 420-file source archive matches
every Git blob; SHA-256:
`b94fe3cf76a8d137767cbd9594cae3afe8db8b4ba8768b060ef76ebd26e2c996`.
The historical Docker client gate ran 42 tests; stage 6 expands it to all five
suites. Stage 5 did not rerun live-model quality; its CI model smoke used fixtures.

Project copy, documentation, comments, and generated operational receipts use
English. Conversational implementation guidance for the owner is Persian.
Multilingual input/Unicode evaluation remains supported; a bilingual workspace
is not part of the design plan.

No new migration, dependency, paid model, or hosting provider is introduced.
Quality scores do not represent hiring probability or population-wide fairness.
A tool-using agent with human approval remains an optional separate extension;
it has not been added to the seven-stage plan.
