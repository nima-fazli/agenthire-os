# Stabilization stage 1

The installation baseline is main 66de4967ab8f6c4b1764506d2e5de4f0549dfe12.
The previous accepted checkpoint is 15-A3, committed as c5e93e7/66de496.
Its Windows/Docker/backup results remain historical evidence in verification.md.

## Changes

- Require every complete lexical query term in a model-selected anchor.
- Reject invented, unrelated and partial-token anchors.
- Return the entire assigned chunk as the exact citation, preserving context
  before and after the model's selection and original Unicode offsets/hashes.
- Version the brief/prompt as v2 and the context policy independently.
- Add a new immutable nine-case reference. Keep the v1 fixture for history.
- Independently reject correctly hashed substrings that omit source context.
- Recognize the actual duplicate-email backend code in the recruiter client.
- Export complete committed source with both CI files and a hash manifest.
- Keep private source configuration, PDFs and personal recovery outside exports.

The database schema, frozen search normalization, embedding encoding, models,
dependency lock and feature flags retain their existing contracts.
The interface change is limited to safe localized error messages.

## Acceptance

Local Linux verification on 2026-10-18 passed: 1725 Python tests with -W error
and no skips, 46 JavaScript tests, Ruff, the source migration head check and
33-check CI planning without execution. A real-Git export of a separate
verification copy included all 363 source files, both CI files and the manifest,
with no private paths. These verification-copy commits are not user commits.

Native Windows/Docker acceptance,
live v2 model acceptance and the user's feature/test commit hashes are pending.
Never relabel the older 15-A3 acceptance as a run of these changes.

Run all Python tests with warnings as errors, Ruff and all three Node suites.
Then inspect the CI plan and run the isolated scripts.ci_verify gate. Its normal
environment separation, owned cleanup and existing backup gates remain required.
The fixture grounding smoke now consumes the v2 reference automatically.

Rebuild affected normal API/smoke images after successful isolated acceptance,
then verify the normal stack using the existing runbook. Do not change model
flags or silently download models. Live v2 inference needs a separate explicit
operator run using the existing measured local-model workflow.

After native acceptance, make the two explicit scoped commits, inspect their
real hashes, and create a source bundle from that clean committed tree.
Update the personal recovery outside Git with those observed results.

## Boundaries

Full assigned-chunk context does not prove proficiency, resume truth or context
outside that chunk. The nine synthetic cases do not establish broad model
quality. Wider evaluation remains stage 4. Workflow completion is stage 2;
roles/session controls, final bilingual design and deployment remain later work.
