# Recruiter workspace

The public shell is served at `/workspace/`; private records require a tracked
bearer session and server-side organization authorization. HTML, CSS, and native
ES modules are served locally with no-store and a restrictive CSP. There is no
frontend build, CDN, cookie authentication, persistent browser token storage,
service worker, or third-party telemetry.

## Working context

Choose an organization and job from the context menu. The sidebar has five
sections: Candidate review, Job setup, Applications, Members and access, and
Account security. On narrow screens the context menu starts collapsed and
navigation wraps into touch-sized rows. Native links remain useful if the
design enhancement fails; record and request ownership lives in app.mjs.

Section changes show the relevant panel and move keyboard focus to it. They do
not clear selected records or drafts. Opening a candidate from Applications
moves to the candidate dossier after the real controller updates the heading.
Organization/job changes retain the existing cancellation, authorization,
source invalidation, and confirmation-closing contracts. Browser back/forward
is not used as a private record history.

## Recruiting and evidence

Lists use server pagination and literal search. Metrics report the current
filtered result totals. They do not count unseen records locally. Job/candidate
edits submit the exact loaded updated_at value and preserve the draft on a
conflict. Loading a newer version or switching records replaces that draft.

Application transitions are explicit and confirmed. PDF deletion requires the
exact filename. Extraction and embedding actions retain bounded progress and
explicit refresh. Local-model features can be disabled by server configuration;
the interface does not silently switch providers or reinterpret search scores
as hiring probabilities. Source text is rendered as text nodes, including
Unicode offsets, original context, qualifications, and provenance.

## Focus, feedback, and sessions

A skip link reaches main content. Each input has a label; sections and dialogs
have accessible names. Navigation marks exactly one current section. Focus is
visible, dialogs use native modality, and Escape cancels confirmations. The
workspace guide restores focus to a visible connected trigger. Private focus
is moved back to sign-in when the shell becomes hidden.

Status and error notifications keep their existing polite/assertive live
regions. Unknown server text is not echoed. Native disabled controls remain
disabled for permissions and pending requests; disabled is not presented as
proof that a request is running. Keyboard navigation and reduced-motion/forced-
colors styles complement responsive layouts; they do not establish a formal
accessibility certification.

Signing out clears page state and requests revocation. Closing/reloading clears
page credentials but does not itself revoke the old tracked server session.
Cancellation stops waiting UI ownership, not an already accepted write or a
running model thread. Comprehensive real-stack and browser evidence have
separate acceptance gates; see product-design.md.
