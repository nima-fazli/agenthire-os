# Roadmap

As of 2026-10-14: backend through stage 12 is committed. Stage 13-A passed
native checks, isolated Docker, normal-stack schema/HTTP checks and user browser
acceptance. Its completion commits are next; the last observed HEAD is main 4db6cb6.
Actual Git history takes precedence over this pre-commit checkpoint.

| Stage | State | Next work |
| --- | --- | --- |
| 0-12 | Committed backend and local evidence pipeline | Wider corpus/load evaluation |
| 13-A | Workspace and popup feedback accepted | Scoped feature/test completion commits |
| 13-B | Next; previous draft is not installed or accepted | Application/status UI, editing, confirmed deletion, embedding controls and repeatable browser checks |
| 14 | Planned | Readiness, observability and justified authorization/session controls |
| 15 | Planned | Release, migration rollout, backup/restore verification and a free hosting decision |
| Final frontend | Deferred until the user starts it | English-first bilingual design, typography, colors, interaction and responsive browser QA |

Continue 13-B from the actual committed 13-A source. Historical draft results
1363 Python / 52 Node are not the accepted current 13-A results, which are
Windows 1347 + 5 skips, Docker 1352, Node 42 and Ruff passed.

All AI/services remain free/local: qwen3-embedding:0.6b, 1024 dimensions,
and qwen3:0.6b. No paid provider or silent cloud fallback. Source head remains
0016_document_embeddings. Hosted Actions, broader model/corpus/load evaluation
and production recovery/deployment remain open. Agents, Redis, LangGraph, MCP
and Temporal require a concrete workflow need. Full teaching stays deferred.

The final design uses English as the primary language and Persian as secondary,
with LTR/RTL, deliberate colors, locally bundled openly licensed fonts, accessible
popup feedback and responsive forms. It does not start during the current workflow work.
