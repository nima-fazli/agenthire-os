# Product design: completion stage 5

Base: accepted main `160fc05fe506caf47da0dcdbca525a0e5df93de5`.
Stage 5 is a source delivery until its native acceptance receipt is recorded.
Two completion stages remain after design acceptance: release and portfolio.

## Design decisions

The English workspace uses a restrained evergreen, warm-neutral, and white
palette, system typography, clearer spacing, and consistent 44px controls.
Five sections reduce the long-page scanning burden. Candidate review keeps the
list beside the source dossier on large screens and stacks it on smaller ones.
Organization/job selection remains explicit and is collapsible on mobile.

The initial screen states what the product does without invented customers,
quality scores, hiring outcomes, or production security claims. Empty states,
result totals, confirmations, and operational feedback reflect real controller
state. The guide explains the workflow and the optional local-model features.
No model, API, schema, role, session, or private-storage contract changes here.

## Verification and evidence boundaries

- Native Node tests cover navigation state, focus, context clearing, and the
  existing session, source, stale-response, and authorization behavior.
- Fixture regressions execute the complete embedded application through
  synthetic sign-in and navigation, verify its CSP hashes, and require identical
  output for UTF-8 BOM and Windows line endings.
- Keyboard transport regression verifies Enter's carriage-return text, ordered
  key release, and non-text Tab/Escape dispatch. Native guide checks still use
  Chromium keyboard input and require the dialog and focus state to change.
- Python tests verify current delivery hashes, path rejection, browser receipt
  requirements, asset serving, English copy, and Docker source packaging.
- scripts.design_acceptance runs the full existing real-stack CI and recovery
  gates, separately from browser checks.
- scripts/design_browser.mjs uses an installed Chromium browser with a fresh
  temporary profile. It builds the actual HTML/CSS/module graph into an offline
  fixture with a hash-based CSP and connect-src 'none'. Synthetic fetch responses
  are explicitly labeled. It never loads normal private data or an existing
  browser profile. Browser transport mocks are not live backend evidence.
- Browser checks cover five sections, candidate navigation from applications,
  confirmation cancellation, 1440/1024/768/390/320px layouts, touch target heights,
  the guide's keyboard/Escape behavior, empty/error states, context clearing,
  sign-out, and uncaught exceptions. Reports bind to the complete stage 5 source
  fingerprint and successful temporary-profile cleanup.

The owner's run for the preceding source fingerprint passed Ruff, Windows
Python (1,926 passed, 5 skipped), Docker Python (1,931 passed), native Node
(76 passed), and isolated CI/recovery/cleanup. It stopped at synthetic browser
sign-in and did not accept stage 5. The fixture bundler omitted the exported
`$` function; its export handling and encoding normalization are now corrected.
Browser waits also identify their checkpoint and stop on uncaught exceptions.

The assistant verified 80 Node tests and source syntax/structure for the
corrected delivery. Real Chromium and the full native gate still need to pass
for its new fingerprint. The cloud browser could not access the local preview
and rejected local-file navigation. Automated checks are bounded; manual
screen-reader testing, OS high-contrast review, 200% text zoom, visual judgment,
and additional browser engines are not proven by a Chromium receipt.

## Native acceptance

Keep AgentHire_OS_Recovery_Current.md beside the existing repository. Do not
commit the delivery manually; the driver creates its two exact scoped commits
only after all checks pass. Keep the normal environment, volumes, schema, model
settings, and private files. A plan does not invoke Docker or create commits.
First check the corrected fixture without running the lengthy full CI gate:

```powershell
node --test tests/recruiter_design.test.mjs
if ($LASTEXITCODE -ne 0) { throw "Design regression tests failed." }
node scripts/design_browser.mjs --report "..\AgentHire_OS_Design_Reports\stage5-browser-precheck.json"
if ($LASTEXITCODE -ne 0) { throw "Browser precheck failed. Review its report." }
```

Then run the plan and full acceptance. The precheck does not replace any gate:

```powershell
uv run --locked --no-sync python -m scripts.design_acceptance
if ($LASTEXITCODE -ne 0) { throw "Stage 5 source verification failed." }
uv run --locked --no-sync python -m scripts.design_acceptance --execute --finalize
if ($LASTEXITCODE -ne 0) { throw "Stage 5 acceptance failed. Review the output." }
```

Chrome or Edge must be installed. Set AGENTHIRE_BROWSER_BINARY only if automatic
location fails. Browser reports remain in AgentHire_OS_Design_Reports beside the
repository. A failing browser/CI/cleanup gate prevents finalization. Normal
API/smoke images are rebuilt and the API alone is refreshed after test gates;
the existing English HTTP smoke and normal-stack diagnostics must then pass.
No normal database migration or extraction-worker recreation is requested.

Successful finalization records commits, source ZIP/hash, browser report/hash,
and next stage in English outside Git. It appends to both recovery files when
the complete guide exists. There is no push or external deployment.

For manual inspection, export the same synthetic fixture and open the resulting
HTML in a local browser. It cannot connect to the project database or network:

```powershell
node scripts/design_browser.mjs --export "$env:TEMP\agenthire-design-preview.html"
```

Review mobile layouts, long content, focus visibility, reduced motion, and OS
high contrast. Use real-stack synthetic accounts for additional end-to-end
manual review; keep real applicant data out of screenshots and reports.
