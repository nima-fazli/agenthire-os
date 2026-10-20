# AI quality: completion stage 4

This gate produces a bounded, reproducible result rather than a population-wide
quality claim. `scripts/fixtures/ai_quality_v1.json` contains 12 synthetic resumes,
eight ranking queries, and 12 grounded-brief cases. No real applicant data is used.

## Reference and independent evaluation

Every ranking query has a preassigned grade for all 12 candidates: 3 for direct
relevance, 2 for strong relevance, 1 for partial relevance, and 0 for unrelated
content. Cases include literal English, paraphrases, Persian, cross-language
retrieval, unrelated occupations, and Unicode punctuation. Names do not enter
relevance judgments. Multilingual samples are test data, not product localization.

Brief cases cover English/Persian sources, negation, later qualifications,
multiword/punctuated anchors, nonzero offsets after emoji, bilingual injection,
no documents, unrelated documents, and oversized UTF-8 input. The evaluator
compares full expected context, slices, offsets, and hashes independently; it
does not call production ground or assigned_context. It also validates response
schemas, scope, profile identity, server prose, and embedding provenance.

The fixture seeds text and metadata directly in PostgreSQL and is explicitly
labeled `source_kind=synthetic_text_seeded_db`. It does not test PDF extraction.
Ordinary real-stack CI and workload gates cover the PDF/worker pipeline separately.

## Preregistered thresholds

Each case runs twice, serially, without automatic retries: 48 ranking observations
and 24 brief observations. Lexical, semantic, and hybrid share the same judgments.

| Measurement | Live acceptance requirement |
| --- | --- |
| Mean semantic/hybrid nDCG@3 | At least 0.75 for each method |
| Semantic/hybrid MRR | At least 0.75 for each method |
| nDCG@3 within each query language | At least 0.55 for each method |
| Difference from lexical nDCG@3 | No regression greater than 0.10 |
| Source, citation, coverage, and scope contracts | No failures |
| Ordinary witnessed brief | Valid generation required; rejection does not pass |
| Adversarial source | Valid citation or 503 OUTPUT_INVALID/OUTPUT_UNGROUNDED |
| Missing evidence | No citation, generation, or token claim |
| Oversized prompt | 422 EXPLANATION_INPUT_TOO_LARGE |
| Different names with identical source text | Cosine gap at most 0.00001 on relevant queries |
| Owned cleanup | Successful removal and no remaining project containers/volumes/networks |

nDCG uses gain 2^grade-1 and log2 discount. Recall@3 and MRR treat grades 2/3 as
relevant; MRR uses the returned ranking. Reports include repeat top-3 agreement,
valid quote yield, safe rejection counts, and reported token usage. Thresholds
are not automatically lowered after viewing results.

Latency reports count, first observation, median, nearest-rank p95, and maximum.
Brief timings include no-inference cases; embedding seed time is excluded.
Only successful API responses expose validated token counts: zero in an error
row does not claim zero model work. Embedding is already warm after seeding;
cold/warm conditions are not controlled. Small samples do not establish capacity.
The identity pair checks a narrow metadata property, not general hiring fairness.

## Isolated live execution

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_run
uv run --locked --no-sync python -m scripts.ai_quality_run --execute
```

The first command prints a plan only. Execution requires a fresh generated
`agenthire-ci-<uuid>` project, test environment, and agenthire_ci database/user
on host postgres. The base, CI, and quality Compose files are combined without
publishing host ports. Only the isolated API enables both feature flags. Live
checks use authenticated private HTTP and real tracked sessions. Normal flags,
data, and model volumes are retained. No extraction/embedding worker is started.

The existing free tags `qwen3-embedding:0.6b` and `qwen3:0.6b` are downloaded into
this project's own temporary volume. Public tags can change; full observed model
digests are recorded and checked before/after evaluation. Compare runs only when
reference hash, model digests, contracts, and settings agree.

The default overall deadline is 3600 seconds; `--deadline` accepts 300-7200.
After successful preflight, errors, timeouts, and interruption still attempt
owned cleanup. Failed cleanup is attention_required and blocks acceptance.
A preexisting occupied project is refused before mutation or cleanup.

Unique aggregate reports remain in `AgentHire_OS_Quality_Reports` beside the
repository, even after a failed evaluation. They contain case IDs, rankings,
checks, timings, token counts, and hashes; no resume text, prompts, vectors,
bearer tokens, or passwords. Fixture CI can pass contract_passed but can never
pass quality_passed. Only the live runner can satisfy native quality acceptance.

## Source acceptance and Docker packaging

```powershell
uv run --locked --no-sync python -m scripts.ai_quality_acceptance
uv run --locked --no-sync python -m scripts.ai_quality_acceptance --execute --finalize
```

The required accepted main base is `261dd607b740a8d91d0bafabe2cb268c276c1c75`;
schema remains 0017. The cumulative manifest includes the initial stage 4 files
and the English/packaging correction. Its bounded allowance is 64 files, with an
explicit hash for every entry except the manifest itself. Unrelated changes or
commits are refused.

The Docker test target copies the exact public repository inputs needed by
manifest and plan checks, including README, docs, Compose files, Dockerfile,
and workflow definitions. It does not copy Git history or private environment
files. A regression test reconstructs those COPY inputs and runs the three
checks that failed in the first native attempt. No failing test is skipped.

After native/CI/live checks and owned cleanup pass, acceptance rebuilds the normal
API/smoke images and verifies the English HTTP workspace. Finalization creates
two local commits, a hash-checked source ZIP, and English recovery receipts.
It updates the complete recovery file when present. There is no push/deployment.
Native acceptance passed on 2026-10-20, with feature commit
`9f99e7ccee33d5732cef70cec7e318c113901784` and main/test commit
`160fc05fe506caf47da0dcdbca525a0e5df93de5`. The supplied console receipt records
quality_status=passed and source SHA-256
`f7daab229e669d61715b452870f2a0a2c2872f5beafb9166f002f79dc0901c8c`.
The saved live report SHA-256 is
`15c0387c6a17deba739d6a8173c3277ed701e70ceb1c5548b6ae5682ab3a7137`.
Its detailed metrics were not independently re-opened during stage 5 design.

The stage 4 manifest and driver remain historical gates. Stage 5 deliberately
changes workspace files, so its delivery uses design_stage5_manifest.json and
design_acceptance.py. The stage 4 loader still rejects changed historical hashes;
regression tests exercise its integrity contract with an explicit test fixture.
No production hash checks or live quality thresholds are bypassed.
