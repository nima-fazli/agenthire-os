# Completion roadmap

Observed source, Git history, and execution receipts take precedence over older
notes. The latest accepted main base is
`261dd607b740a8d91d0bafabe2cb268c276c1c75`. Personal recovery files stay outside Git.

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

Stage 3 native acceptance passed 1,806 Windows Python tests with five known
platform skips, 1,811 Docker Python tests, 70 native Node tests, Ruff, 33 CI steps
plus cleanup, the normal recruiting/access workflow, migration 0017, and health
checks for the API and two extraction workers. Its reported source ZIP contains
389 files; that ZIP has not been independently inspected in this session.

## Seven-stage completion plan

| Stage | Status and completion condition |
| --- | --- |
| 1 Stabilization | Accepted: citation context, regression/error gates, source distribution, recovery |
| 2 Recruiting workflow | Accepted: server pages/search, versioned editing, applications/transitions, confirmed PDF deletion, embeddings, stale-context controls |
| 3 Access and sessions | Accepted: owner/recruiter/viewer roles, invitations, current-password confirmations, last-owner protection, revocable sessions, backed-up migration |
| 4 AI quality | Corrected source ready for verification: diverse reference, independent scoring, adversarial/negative cases, isolated live evaluation, English product copy, complete Docker test inputs; native acceptance pending |
| 5 Final product design | Remaining: polished English LTR experience, responsive layouts, accessibility, comprehensive real-browser and keyboard QA |
| 6 Release acceptance | Remaining: hosted CI, HTTPS, deployment, load evidence, repeatable installation/migration/recovery |
| 7 Hiring portfolio | Remaining: usable demo, synthetic data, short video, clear architecture and engineering tradeoffs |

Four stages remain including stage 4; three remain after native stage 4 acceptance.

The first stage 4 native attempt passed Ruff, 1,879 Windows Python tests with
five known skips, and 70 Node tests. Docker stopped with 1,881 passed and three
packaging failures. Cleanup succeeded; no stage 4 acceptance or commits were
recorded. Correcting the missing test-image inputs does not itself certify live
model quality. The full native gate must be rerun.

Project copy, documentation, comments, and generated operational receipts use
English. Conversational implementation guidance for the owner is Persian.
Multilingual input/Unicode evaluation remains supported; a bilingual workspace
is not part of the design plan.

No new migration, dependency, paid model, or hosting provider is introduced.
Quality scores do not represent hiring probability or population-wide fairness.
A tool-using agent with human approval remains an optional separate extension;
it has not been added to the seven-stage plan.
