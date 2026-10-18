# Stabilization stage 1: accepted

The installation base was main 66de4967ab8f6c4b1764506d2e5de4f0549dfe12.
The accepted feature commit is 8e4d7fa2e37dff381f6225f05e3d6466eb44e453;
the test/main checkpoint is 3b58176505d4b6d85d6d908cd268a03256f6e53c.
Older 15-A3 recovery evidence remains historical in verification.md.

## Changes

- Require every complete lexical query term in a model-selected anchor.
- Reject invented, unrelated and partial-token anchors.
- Retain the entire assigned chunk, exact Unicode offsets and source hashes.
- Version the brief/prompt as v2 and context policy independently.
- Keep the immutable v1 fixture; add nine v2 reference cases.
- Independently reject correctly hashed substrings that omit context.
- Recognize the actual duplicate-email backend code in the client.
- Export complete committed source with both CI files and a hash manifest.
- Exclude private configuration, PDFs and personal recovery from source export.

Schema 0016, dependencies, frozen search normalization, embedding encoding,
model identities and feature flags retained their existing contracts.

## Observed native acceptance on 2026-10-18

| Check | Result |
| --- | --- |
| Windows Python, warnings as errors | 1720 passed; 5 known platform skips |
| Docker Python | 1725 passed; no skips |
| Native Node | 46 passed |
| Native/Docker Ruff | Passed |
| Isolated Docker CI | 33 checks plus owned cleanup passed |
| Grounding v2 fixture | Nine cases passed |
| Normal API/workload/stack | Passed; two extraction workers healthy |
| Source export | 363 source files; clean committed tree |
| Personal recovery | Native acceptance receipt appended outside Git |
| Live v2 model | Not run: explanation feature was disabled |

The source ZIP SHA-256 was independently checked as
`e32e41750db67901f2357fed32057b254b2b57a9696c814ec1928df97664b21d`.
The uploaded archive and every manifest file were subsequently matched to that
checkpoint. Fixture model results are separate from real-model quality.

## Boundaries

Full assigned-chunk context does not prove proficiency, resume truth or context
outside that chunk. Nine synthetic cases do not establish broad model quality.
Wider evaluation remains stage 4. The recruiting workflow is stage 2; access,
sessions, final bilingual design, release and portfolio remain later stages.
