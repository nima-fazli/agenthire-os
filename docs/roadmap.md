# Roadmap

The completed baseline is user main `62da13a`. Stages are implementation slices,
not estimates or an assertion that the whole product is production-ready.

| Stage | Status | Delivery gate |
| --- | --- | --- |
| 0: domain/security/Docker | Verified | Tenant CRUD, JWT, safe errors and migrations |
| 1: application workflow | Verified | Transition graph, retries and real concurrency |
| 2: private documents | Verified | PDF lifecycle, ownership and duplicate races |
| 3: extraction workers | Verified | Bounded parsing, leases/recovery and deletion fencing |
| 4: chunk versions | Verified | Exact source reconstruction and atomic generation |
| 5: full-text search | Verified | Frozen normalization, usable indexes and deadline reset |
| 6: job candidate retrieval | Verified | Candidate grouping, profiles and best-source pagination |
| 7: independent criteria | Verified | Cross-chunk witnesses, readiness and one snapshot |
| 8: quality evaluation | Verified | Versioned synthetic reference and real-stack gate |
| 9: CI/documentation | Prepared | User isolated Docker run, focused commits, actual hosted run when connected |
| 10: storage/data hardening | Planned | Reconciliation/retention and audited application tenant constraints |
| 11: semantic retrieval | Planned | Selected model/provider, versioned embeddings, isolated retrieval and measured baseline improvement |
| 12: grounded AI explanation | Conditional | Structured source-backed output, privacy/cost limits and hallucination evaluation |
| 13: recruiter UI | Planned | Tenant-aware source/evidence flows, accessibility and tested API integration |
| 14: reliability/observability | Planned | Readiness, traces/latency, operational monitoring and justified auth controls |
| 15: release/operations | Planned | Reviewed deployment, migration procedure, backup restore and real acceptance |

## Decisions before semantic retrieval

Choose supported languages, corpus size, acceptable latency, budget and whether
resume text may leave the controlled environment. Compare a suitable local model
against a permitted hosted provider using the reference evaluator. Provider/model,
embedding dimension and hosting are currently unselected. Do not add guessed
credentials, incompatible vector dimensions or AI suitability probabilities.

Persist model/version/dimension and exact source hash; make embedding jobs durable
and idempotent. Enforce the same latest-ready source scope and deletion lifecycle.
Introduce a new migration for actual vector usage; installing pgvector alone does
not mean semantic search exists. Start with an opt-in path, then evaluate hybrid
retrieval against the existing lexical baseline.

## Product completion and optional extensions

Release requires usable recruiting/source/evidence flows, quality evidence beyond
toy data, automated regression checks, operational recovery and a tested deployment.
Only then deliver the postponed project teaching and complete architecture walkthrough.

Agents, LangGraph, MCP tools, Redis and Temporal remain conditional extensions.
Add them only for a real user workflow with tool permissions, retries/approval and
observable outcomes. Human review remains the owner of hiring decisions. CI setup
does not authorize a remote push, deployment or a production data migration.
