# Roadmap

Actual source, Git and latest user output take precedence over snapshots.
UI 13-A is committed through b604ec6/92c23fd; 14-A through 31b7730/f8286de;
14-B1 through 822c4c2/78987f4; 14-B2 through 09f232e/e2b42e9.
14-B3 native acceptance passed with e2b42e9 as the observed Git baseline;
its scoped feature/test commit hashes have not yet been observed.

| Stage | State | Remaining work/acceptance |
| --- | --- | --- |
|0-12|Accepted backend and local evidence pipeline|Wider corpus and live-model quality evidence|
|13-A|Accepted and committed workspace|Preserve current UI|
|13-B|Deferred by the user|Application/status UI, editing, confirmed deletion, embedding controls|
|14-A|Accepted and committed|Closed checkpoint|
|14-B1|Accepted and committed|Closed checkpoint; 30 checks/17 smokes/cleanup passed|
|14-B2|Accepted and committed|31 checks/18 smokes/cleanup, four workflows and both live models passed|
|14-B3|Native acceptance passed|Record scoped commits; Windows 1541+5 skips, Docker 1546, schema/workflow and measured CPU improvement verified|
|15|Planned|Release, migration rollout, coordinated tested backup/restore, free hosting decision|
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
