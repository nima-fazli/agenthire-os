# Roadmap

Actual source, Git and latest user output take precedence over snapshots.
UI 13-A is committed through b604ec6/92c23fd; 14-A through 31b7730/f8286de;
14-B1 through 822c4c2/78987f4; 14-B2 through 09f232e/e2b42e9.
14-B3 was accepted and committed as 955ac94/c7d66c2. The latest observed main
is c7d66c22a43336c2cd8069a082d3e1725fec5939 and was clean at the 15-A1 inventory.
15-A2 native acceptance passed; its 15 scoped files await feature/test commits.

| Stage | State | Remaining work/acceptance |
| --- | --- | --- |
|0-12|Accepted backend and local evidence pipeline|Wider corpus and live-model quality evidence|
|13-A|Accepted and committed workspace|Preserve current UI|
|13-B|Deferred by the user|Application/status UI, editing, confirmed deletion, embedding controls|
|14-A|Accepted and committed|Closed checkpoint|
|14-B1|Accepted and committed|Closed checkpoint; 30 checks/17 smokes/cleanup passed|
|14-B2|Accepted and committed|31 checks/18 smokes/cleanup, four workflows and both live models passed|
|14-B3|Accepted and committed|Windows 1541+5 skips, Docker 1546 and measured healthcheck CPU improvement verified|
|15-A1|Accepted read-only inventory|PostgreSQL tools/server 18.6, vector 0.8.6, two PDF objects and empty queues observed|
|15-A2|Native acceptance passed; commits pending|Windows 1591+5 skips, Docker 1596; all 32 checks/18 smokes and two-stack recovery/cleanup passed|
|15|In progress|Retained private backups, operational restore/retention, release and migration rollout, free hosting decision|
|Final frontend|Starts on explicit user instruction|English-first bilingual design, LTR/RTL and real browser QA|

14-B2 uses synthetic PDFs through real HTTP/extraction/chunk/retrieval, plus a
separate synthetic-client live-model sample. It does not certify capacity or
full inference-through-API performance. Docker memory is sampled working-set
usage, not exact process RSS peak. A quiet queue and one CPU snapshot cannot
establish worker health, a busy loop, throughput or an SLA. Repeated evidence
should justify any later polling, healthcheck, rate or session control change.

14-B3 removes eager worker/runtime imports and the settings-to-SQLAlchemy import
path. A fresh subprocess regression gate rejects DB/model imports in healthchecks
and proves normal CLI startup still selects processing. The measured pre-change
PID 1 averages were 0.8/1.0/1.4 percent; after rebuilding they were 0.6/0.9/1.4.
Median healthcheck CPU changed from 2851.659/2843.580/771.468 ms to
980.490/1181.112/349.616 ms. All nine new probe calls exited zero, normal and CI
schemas showed no drift, four synthetic workflows completed with scoped cleanup,
and the final stack was healthy with empty queues. Three calls per worker do
not establish production capacity or guarantee identical savings elsewhere.

No dependency, migration, model, resource quota, production flag or UI changes
are included. Roles/invites, token refresh/revocation, distributed rate limiting,
OCR, malware scanning and backup retention remain explicit future decisions.
Scores are evidence relevance, never hiring probability. Paid services are out
of scope. Redis, agents, LangGraph, MCP or Temporal need a concrete workflow
reason. Full teaching remains deferred until final delivery.
