# Roadmap

Actual source, Git and latest user output take precedence over snapshots.
UI 13-A is committed through b604ec6/92c23fd; 14-A through 31b7730/f8286de;
14-B1 through 822c4c2/78987f4. User main was clean after those commits.

| Stage | State | Remaining work/acceptance |
| --- | --- | --- |
|0-12|Accepted backend and local evidence pipeline|Wider corpus and live-model quality evidence|
|13-A|Accepted and committed workspace|Preserve current UI|
|13-B|Deferred by the user|Application/status UI, editing, confirmed deletion, embedding controls|
|14-A|Accepted and committed|Closed checkpoint|
|14-B1|Accepted and committed|Closed checkpoint; 30 checks/17 smokes/cleanup passed|
|14-B2|Current measurement toolchain delivery|Run the 31-check/18-smoke CI and normal workloads, queue/resource samples and live-model measurements; inspect evidence before tuning controls|
|15|Planned|Release, migration rollout, coordinated tested backup/restore, free hosting decision|
|Final frontend|Starts on explicit user instruction|English-first bilingual design, LTR/RTL and real browser QA|

14-B2 uses synthetic PDFs through real HTTP/extraction/chunk/retrieval, plus a
separate synthetic-client live-model sample. It does not certify capacity or
full inference-through-API performance. Docker memory is sampled working-set
usage, not exact process RSS peak. A quiet queue and one CPU snapshot cannot
establish worker health, a busy loop, throughput or an SLA. Repeated evidence
should justify any later polling, healthcheck, rate or session control change.

No dependency, migration, model, resource quota, production flag or UI changes
are included. Roles/invites, token refresh/revocation, distributed rate limiting,
OCR, malware scanning and backup retention remain explicit future decisions.
Scores are evidence relevance, never hiring probability. Paid services are out
of scope. Redis, agents, LangGraph, MCP or Temporal need a concrete workflow
reason. Full teaching remains deferred until final delivery.
