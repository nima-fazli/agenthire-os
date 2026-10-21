# Bright frontend design QA

final result: passed

This review evaluates the selected light blue design as the visual direction for the existing working product. The implementation uses the existing API fields and recruiting workflow; it does not reproduce invented data or unsupported features from the mock.

## Evidence and normalization

- Source visual truth: `/workspace/scratch/05297cee7be4/upload/Bright candidate applications dashboard(1).png`, 1672 × 941 pixels.
- Browser-rendered implementation: the current workspace modules exported by `scripts/design_browser.mjs` and opened in the cloud browser preview.
- Desktop CSS viewport: 1363 × 936, device pixel ratio 1. Browser captures contain 1348 × 926 image pixels after the capture surface excludes native scrollbar edges.
- Source was uniformly scaled to 1348 pixels wide for the full-view comparisons. Its natural aspect ratio was preserved and remaining canvas space was padded; the taller implementation capture was not stretched.
- Full-view comparison evidence: `/workspace/scratch/05297cee7be4/agenthire-bright-redesign/qa/desktop-comparison.png` and `qa/applications-comparison.png` in the same review directory. Each combined image contains both source and implementation, opened together for assessment.
- Focused comparison evidence: `qa/profile-comparison.png` and `qa/notifications-comparison.png`. The profile, tabs, notification popover and error toast were reviewed at readable detail size.
- Implementation captures: `/workspace/scratch/agenthire-bright-desktop-top-final.jpg`, `/workspace/scratch/agenthire-bright-applications-final.jpg`, `/workspace/scratch/agenthire-bright-notifications-final.jpg`, `/workspace/scratch/agenthire-bright-auth-final.jpg`, `/workspace/scratch/agenthire-bright-confirmation.jpg`.
- Mobile evidence: `/workspace/scratch/agenthire-bright-mobile-applications-final-full.jpg`, with the actual app inside a 390 × 844 CSS-pixel iframe; document client/scroll widths were both 375 after its native scrollbar. At 320 × 844, client/scroll widths were both 305. The 320-pixel context-dialog capture is `/workspace/scratch/agenthire-bright-mobile-320-context-full.jpg`.
- Enlarged reading-layout evidence: `/workspace/scratch/agenthire-bright-reading-200.jpg`. A half-size CSS viewport rendered at scale 2 approximates the effective layout and physical type size at 200%; its content width was 667 CSS pixels and matched scroll width. This is an explicit reading-layout emulation, not a claim that the browser's native zoom setting was changed.
- Review captures and combined comparison images are session evidence; the update includes this report and the runnable preview for reproducing the views.

## Comparison history

1. **P2 — Heading moved beneath the sticky header after focus-driven navigation.** Initial desktop capture `agenthire-bright-desktop.jpg` exposed the issue. Sign-in and section navigation now use focus without scrolling and reset the page position. Candidate opening from Applications also avoids an automatic desktop jump. The final top-of-page desktop capture shows the heading fully visible.
2. **P2 — Error description inherited a low-contrast danger color on the coral toast.** The earlier `agenthire-bright-notifications.jpg` capture exposed the cascade conflict. The error description now explicitly renders white; the browser confirmed `rgb(255, 255, 255)` over `rgb(255, 107, 100)`. `agenthire-bright-notifications-final.jpg` and the focused combined comparison show the corrected state.
3. **P2 — Applications originally opened the profile in another view.** The selected direction calls for a list beside the profile. The application view now retains the same live dossier beside its list, and opening a candidate keeps Applications active. The dossier is moved rather than cloned, so forms and IDs remain unique. `agenthire-bright-applications-final.jpg` and its combined comparison show the revised layout; the latest mobile capture shows its stacked equivalent.
4. Secondary metadata text was darkened, the candidate search spacing was tightened, and empty member results now use a clear empty-state sentence. Final captures show readable text, aligned controls and no horizontal clipping.

## Required fidelity surfaces

- **Fonts and typography:** locally hosted Inter variable font is active in the browser. Dark semibold headings, readable blue-grey supporting text, compact UI labels and tab text follow the selected direction. Long candidate text wraps inside its column; metadata and source text retain meaningful hierarchy. Exact mock text and invented match percentages were not copied into product fields.
- **Spacing and layout rhythm:** horizontal navigation, generous page margins, five pastel metric tiles, rounded white work surfaces and a two-column list/profile composition preserve the reference's main relationships. Application status controls remain explicit forms because they belong to the existing workflow. The one-application fixture has naturally less row density than the mock's illustrative dataset. On small screens, columns stack and selecting a candidate brings the dossier into view.
- **Colors and tokens:** the forest-green system was replaced by a near-white blue canvas, cobalt primary actions and blue/mint/amber/violet/coral metric surfaces. Selected rows and tab indicators use the blue family. Error feedback uses coral with white text. Confirmation surfaces and popovers have restrained borders, elevation and rounded corners.
- **Image and asset fidelity:** six independent fictional professional portraits were generated in a consistent neutral studio style. All seven visible list/profile images loaded at 240 pixels in the desktop review. Real records retain meaningful initials unless the explicit synthetic fixture supplies an allowlisted portrait key. Icons are original Bootstrap Icons SVG assets, not custom drawings. Fonts, portraits and icons are served locally and embedded in the offline preview.
- **Copy and content:** labels refer to the existing product's jobs, applications, criteria, resumes and source evidence. Counts come from the actual current result/page scope. Unsupported scheduling, global analytics, bulk selection, overall match percentages and fabricated candidate facts from the mock were not added. Historical case-study verification claims remain bound to their original checkpoint.

## Interaction review

The following were exercised in the real browser with explicitly synthetic data:

- Opening the synthetic workspace and selecting Alex Morgan.
- Switching between navigation sections; viewing Jobs, Team and account security without changing credentials or access.
- Opening Resume and moving to Evidence with the arrow key; roving tab focus and selected state update.
- Opening an application candidate and retaining its application list beside the dossier.
- Opening a status-change confirmation, cancelling with Escape and restoring focus; completing a synthetic transition and observing the updated status, metric and success notice.
- Producing a safe request failure, seeing its persistent coral toast and history entry, and marking the notification read.
- Switching to Empty workspace and confirming that the prior candidate and previous error entry are cleared.
- Opening and closing the context dialog at mobile width; checking no document-level horizontal overflow at 390 and 320 pixels.
- Checking the effective enlarged reading layout and opening its context dialog.
- Checking app console errors: no application-origin errors were observed. Browser-extension metadata errors were distinguished from application errors.

Motion uses short entrance, hover, tab, toast, popover and dialog transitions. Reduced-motion CSS disables transitions and animations. Native browser zoom and OS reduced-motion preference toggling were not independently automated.

## Findings and follow-up

No actionable P0/P1/P2 findings remain for this implementation scope. The remaining visual differences are explicit product/API adaptations rather than broken copies of the mock: actual record counts, source-evidence fields and explicit status-change controls.

P3 follow-up: application rows could use a more compact optional presentation in a future iteration, provided their existing controls remain discoverable. This is not required for the selected direction or the current workflow to function.

## Implementation checklist

- [x] Common design system applied across authentication, recruiting, job setup, team, account security, feedback and case-study colors.
- [x] Main interactions and responsive states exercised in browser-rendered output.
- [x] Source and implementation opened together in full and focused visual comparisons.
- [x] Identified blocking visual issues corrected and recaptured.
- [x] Local regression and reversible installer verification included with the update.
- [x] Historical acceptance hashes retained; no hosted or live-model acceptance claimed for this source change.
