# Roadmap

As of 2026-10-14, stage 13-A is committed in b604ec6 and 92c23fd after the
accepted 4db6cb6 test checkpoint. The user's latest main tree was clean.
The latest instruction postpones frontend work; stage 14-A is the next backend
delivery. Actual Git history and new verification output take precedence.

| Stage | State | Next work |
| --- | --- | --- |
| 0-12 | Committed backend and local evidence pipeline | Wider corpus/load evaluation |
| 13-A | Accepted and committed recruiter workspace | Preserve current UI |
| 13-B | Deferred by the user's current instruction | Application/status UI, editing, confirmed deletion, embedding controls and repeatable browser checks |
| 14-A | Backend operations delivery; new user acceptance pending | Readiness, private diagnostics, request correlation and bounded logs |
| 14-B | Planned after 14-A acceptance | Failure/load exercises and justified authorization/session controls based on observed needs |
| 15 | Planned | Release, migration rollout, coordinated backup/restore verification and a free hosting decision |
| Final frontend | Starts only on the user's instruction | English-first bilingual design, typography, colors, interaction and responsive browser QA |

14-A does not add a migration, model download or paid service. Source schema
head remains 0016_document_embeddings. /ready checks core DB/schema/storage;
model availability and worker health have separate operator checks.

All AI/services remain free/local: qwen3-embedding:0.6b, 1024 dimensions,
and qwen3:0.6b. No silent cloud fallback. Hosted Actions, broader live-model
quality, realistic load and production deployment/restore remain open.
Agents, Redis, LangGraph, MCP and Temporal need a concrete workflow reason.
Full teaching stays deferred until final delivery.

The final design uses English as primary and Persian as secondary, with
LTR/RTL, deliberate colors, locally bundled openly licensed fonts, accessible
popup feedback and responsive forms. Historical 13-B draft results are not
installed or accepted and must not be reported as the current baseline.
