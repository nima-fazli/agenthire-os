# Recruiter workspace

`/workspace/` is an English, left-to-right workspace using local HTML/CSS and native ES modules. Token and application
state stay in memory. Reload/logout requires login. There is no browser
storage, cookie, service worker, CDN or npm build step.

The workspace covers organizations/jobs, candidates, saved search/match
profiles, applications and transitions, private PDFs, extraction/chunking,
embedding controls, lexical/semantic/hybrid retrieval and grounded evidence.

Organization, job, candidate and application lists now use bounded server
pages. Search applies to the whole authorized collection. Current selections
stay pinned when pages or filters change. Count labels refer to the current
search. Empty, loading and failed states are explicit.

Editing uses full replacement with the exact server `updated_at` version.
Blank optional candidate fields clear their old values. Conflicts preserve the
local draft until the user reads the new version or changes selection. Form
copy explains that those actions replace unsaved input.

Application choices come from the existing server state machine. A recruiter
selects a target and confirms it. Final states offer no further transitions.
PDF deletion requires its exact filename in a native confirmation dialog.
Context changes close the dialog and invalidate old request ownership.

Document controls request extraction/chunking/embedding explicitly. Embedding
status is refreshed with a read; retry is an explicit action. The client neither
downloads models nor changes feature flags. A disabled service has a safe English
error, with no automatic retry or search fallback.

Feedback remains visible while the workspace scrolls. Success expires after
eight seconds and pauses on hover/focus; errors persist and use an assertive
alert. Server response text is not echoed. Text rendering uses safe DOM APIs.
Exact source identity, hashes and Unicode code-point offsets remain checked;
complete assigned quotes support the v2 maximum of 4000 code points.

Late responses cannot replace a different selection. Cancellation does not
undo an accepted write or stop a server model thread; refresh before repeating
an uncertain mutation. See [recruiting-workflow.md](recruiting-workflow.md).

Completion stages 1-3 have native acceptance receipts. Stage 4 acceptance is
pending after the English copy and Docker packaging correction. Node controller tests use a DOM fixture; the expanded
HTTP smoke exercises real authenticated APIs and SQL. Neither is a complete
browser automation suite. Final English design and broad viewport/keyboard browser QA remain stage 5.
The shell declares lang=en and dir=ltr; dates use en-US. Grounded briefs are
requested explicitly in English. Source text retains its original language and
uses automatic direction only within source/user-data elements.
