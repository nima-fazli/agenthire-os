# Roadmap

Actual source, Git and observed user results override recovery snapshots.
The accepted base is main 66de4967ab8f6c4b1764506d2e5de4f0549dfe12.
Personal recovery documents stay outside Git.

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

Recorded 15-A3 acceptance: Windows 1672 passed with 5 known platform skips,
Docker 1677 without skips, Node 42, Ruff, 33 CI checks, 18 smokes and owned
cleanup. A retained normal-data restore matched 20 rows and 2 PDFs. Original
containers resumed healthy. Retention was a plan without deletion. These results
do not establish encrypted/offsite protection or a production RPO/RTO.

## Seven remaining stages

Each stage is delivered and accepted as one coherent unit, without A/B slices.

| Stage | Completion condition |
| --- | --- |
| 1 Stabilize | Context-preserving citations and independent regression gates, correct client errors, complete private-data-free source distribution, current recovery |
| 2 Complete recruiting workflow | Applications/transitions, editing, confirmed deletion, embedding controls, server search/pagination and stale-context handling |
| 3 Access and sessions | Needed roles/invites, session lifecycle and tested controls for sensitive operations/requests |
| 4 Prove AI quality | Diverse reference data, adversarial/negative cases and reproducible model-quality evidence |
| 5 Final product design | English-first/Farsi-second translation, LTR/RTL, responsive layout, keyboard/accessibility and real browser QA |
| 6 Release acceptance | Hosted CI, deployment configuration, HTTPS, load evidence and repeatable installation/migration/recovery |
| 7 Hiring portfolio | Usable demo, synthetic demo data, short video, clear README and architecture/tradeoff explanation |

Stage 1 source is delivered for acceptance. Native Windows/Docker/live-model
results and the user's new scoped commits are not yet observed. See stabilization.md.
The migration head, pinned models/encoding and dependency lock remain unchanged.

Paid providers/services remain out of scope. Hosting is not selected. Scores
do not represent hiring probability. A real tool-using agent with human approval
was discussed as an optional additional stage and has not been added to these
seven. Redis, LangGraph, MCP or Temporal require an actual workflow reason.
Full teaching remains deferred until final delivery.
