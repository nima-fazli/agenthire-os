# Recruiting workflow: completion stage 2

Installation base: main 3b58176505d4b6d85d6d908cd268a03256f6e53c.
Stage 2 source is delivered for native acceptance as one complete stage.

## Paged reads

| Endpoint | Search and filters |
| --- | --- |
| GET /organizations/page | Authorized organization name/slug |
| GET /organizations/{org}/recruiting/jobs | Title/description; optional status |
| GET /organizations/{org}/recruiting/candidates | Name/email/headline/location |
| GET /organizations/{org}/recruiting/applications | Candidate name/job title; status/job/candidate IDs |

The page envelope contains items, total, limit and offset. Defaults are 20/0;
limit is 1-100, offset is 0-10000 and search text is at most 120 characters.
Search is literal, case-insensitive substring matching: %, _ and backslash
are escaped. Record search is separate from frozen resume text normalization.
Ordering is newest created_at then id. One SQL statement shares a snapshot
between the total and rows, including out-of-range empty pages. Its CTE retains
IDs/sort keys; long record text is read only for the selected page. PostgreSQL
statements have a two-second timeout. Existing list endpoints remain compatible;
the workspace uses the new bounded endpoints.

## Versioned replacement

PUT /organizations/{org}/recruiting/jobs/{id} and
PUT /organizations/{org}/recruiting/candidates/{id} require expected_updated_at
from the last read and a complete replacement record. Candidate optional values
may be null. The service verifies membership, locks the tenant-scoped row
without waiting and compares its version before writing. RECORD_BUSY is 503;
RECORD_CHANGED is 409. Neither performs a retry. Conflicts leave the UI draft
available for review. Existing PATCH behavior remains compatible.

## Applications and documents

Application creation/transitions use the existing transactional API. Page rows
include the current server-approved choices from its single state machine.
The UI requires a selected target and confirmation; hired/rejected are final.
Application changes invalidate applicant-filtered retrieval results.

PDF deletion is confirmed by typing the exact filename. The server still owns
authorization and deletion integrity; confirmation is a user-intent safeguard.
Changing organization/job/candidate cancels open confirmation. Extraction,
chunking and embedding are explicit requests. Status refreshes are reads;
failed embedding retries require a new click. Chunk/source operations clear
cached embedding display. Backend model identities and flags are preserved.

## Acceptance and evidence

The copy manifest hashes every changed code/test/document file, normalizing
UTF-8 BOM, CRLF and terminal empty lines. It catches missing files and code
pasted into the wrong path before expensive checks. It is not a signature or
secret scanner. The driver defaults to a plan:

    uv run --locked --no-sync python -m scripts.recruiting_acceptance
    uv run --locked --no-sync python -m scripts.recruiting_acceptance --execute --finalize

Execution verifies the accepted main baseline and schema 0016, runs native
Python/Ruff/Node, isolated CI with owned cleanup, then the normal workload and
expanded recruiting HTTP smoke. Source is checked again before finalization.
Two scoped local commits precede a source export; the archive hash and its
changed source contents are checked before the external recovery receipt is
appended. A failed check prevents finalization. No push or branch reset occurs.

Repository tests execute real page SQL on an isolated in-memory SQLite fixture
and compile PostgreSQL SQL. Native Docker HTTP acceptance remains necessary
for the PostgreSQL-specific gate. Node tests exercise controllers and requests
with synthetic transport/DOM fixtures. Comprehensive real-browser and final
bilingual design acceptance remains stage 5. Live model quality remains stage 4.
