# Recruiter workspace

/workspace/ uses local HTML/CSS/native ES modules and the existing Persian shell.
Token/data stay in memory; reload/logout requires login. There is no browser
storage, cookie, service worker, CDN, npm build step or model cloud fallback.

The workspace covers account access, organizations/jobs, saved profiles, candidates,
lexical/semantic retrieval, exact grounded quotes, private PDFs, extraction and chunking.
Application/status screens, editing, confirmed deletion and embedding controls belong
to 13-B and are not part of the accepted current source.

Feedback is fixed above the scrolled workspace. Success expires after eight
seconds and pauses on hover/focus. Errors remain until dismissed/replaced and
use an assertive alert. All messages use textContent and local error allowlists.
Creation messages are shown after dependent refreshes so selection feedback does
not replace them. PDF/candidate refresh failures distinguish an accepted write
from a failed following read. Accepted writes are never automatically retried.

Context changes cancel request ownership; late responses cannot replace a new
selection. Cancellation does not undo an accepted write or stop a model thread.
Refresh before repeating an uncertain mutation. Transport/body limits and exact
source identity/hash/Unicode quote checks remain intact.

13-A was accepted on 2026-10-14: Windows Python 1347 + 5 skips, Docker Python
1352 without skips, Node 42 on both platforms, Ruff, all isolated checks/cleanup,
normal-stack head/drift and recruiter_ui_smoke passed. The user checked the browser
page and accepted it. The native suites use DOM stubs, and the HTTP smoke is not
browser automation; comprehensive viewport/keyboard coverage is still unrecorded.

The final English-first bilingual redesign is deferred until the user starts it.
Persian remains secondary in the final design; i18n is not complete in this source.
