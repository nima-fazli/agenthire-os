# Roadmap

Actual source, Git and latest user output take precedence over snapshots.
Backend 0-12 and UI 13-A are committed through b604ec6 / 92c23fd. The latest
14-A terminal passed native/isolated Docker/normal-stack acceptance; its two
commit hashes are still unobserved. Close that checkpoint before installing
14-B1. Never invent hashes or repeat completed stages from an old recovery.

| Stage | State | Remaining acceptance/work |
| --- | --- | --- |
| 0-12 | Committed backend and local evidence pipeline | Wider corpus and live-model evaluation |
| 13-A | Accepted and committed workspace | Preserve current UI |
| 13-B | Deferred by the user | Application/status UI, editing, confirmed deletion, embedding controls |
| 14-A | User verification passed; commits pending | Two scoped commits and recovery update |
| 14-B1 | Current source delivery; new user Docker acceptance pending | Queue/service diagnostics, bounded latency probe, DB timeout/read-only recovery smoke |
| 14-B2 | Planned after this slice | Realistic workload/queue progression, model latency/memory and justified access/session controls |
| 15 | Planned | Release, reviewed migration rollout, coordinated tested backup/restore, free hosting decision |
| Final frontend | Starts on explicit user instruction | English-first bilingual design, LTR/RTL and real browser QA |

14-B1 adds no dependency, model, migration, paid service or UI change. Core
readiness, worker liveness and model availability remain different signals.
Its small GET sampler is not a capacity benchmark. Model scores are evidence
relevance, never hiring probability. Logs/reports must not contain private data.

Agents, Redis, LangGraph, MCP and Temporal need a concrete workflow reason.
Roles/invites, token lifecycle, rate limiting, OCR and malware scanning are not
implicitly implemented. Production retention/backup expiration need an explicit
policy. Full teaching remains deferred until final delivery.
