# Roadmap

The completed baseline is user main `0c9778f`. Stages are implementation slices,
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
| 9: CI/documentation | Docker runner and commits verified | Hosted Actions run remains unverified until connected and observed |
| 10: storage/data hardening | Verified | Audited Application tenant FKs, guarded cleanup, eleven smokes and normal stack accepted |
| 11-A: local embeddings | Prepared, user acceptance pending | Free local CPU model, durable source/model versions, pgvector invariants and real-model smoke |
| 11-B: semantic/hybrid retrieval | Next | Isolated latest-ready candidate retrieval and measured quality/latency against lexical reference |
| 12: grounded AI explanation | Conditional | Structured source-backed output, privacy/cost limits and hallucination evaluation |
| 13: recruiter UI | Planned | Tenant-aware source/evidence flows, accessibility and tested API integration |
| 14: reliability/observability | Planned | Readiness, traces/latency, operational monitoring and justified auth controls |
| 15: release/operations | Planned | Reviewed deployment, migration procedure, backup restore and real acceptance |

## Decisions before semantic retrieval

Current constraints are Persian/English, CPU with 8-16 GiB RAM and no paid service.
Stage 11-A selects local Ollama/qwen3-embedding:0.6b, 1024 dimensions and immutable
model digests. Resume text stays on the controlled local machine. Actual corpus
size, acceptable latency, measured bilingual quality and release hosting remain
open. Do not add paid providers, incompatible dimensions or AI suitability probabilities.

Persist model/version/dimension and exact source hash; make embedding jobs durable
and idempotent. Enforce the same latest-ready source scope and deletion lifecycle.
Migration 0016 adds actual versioned vector storage. Semantic search is not yet
implemented by that storage alone. Keep the opt-in path and evaluate hybrid
retrieval against the existing lexical baseline in stage 11-B.

## Product completion and optional extensions

Release requires usable recruiting/source/evidence flows, quality evidence beyond
toy data, automated regression checks, operational recovery and a tested deployment.
Only then deliver the postponed project teaching and complete architecture walkthrough.

Agents, LangGraph, MCP tools, Redis and Temporal remain conditional extensions.
Add them only for a real user workflow with tool permissions, retries/approval and
observable outcomes. Human review remains the owner of hiring decisions. CI setup
does not authorize a remote push, deployment or a production data migration.
