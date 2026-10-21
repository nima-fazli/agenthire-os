# Bright frontend update

The selected light blue recruiting dashboard is the visual target for this update. The existing application modules and authenticated API own the data and mutations.

The workspace now uses local Inter fonts, Bootstrap outline icons, a horizontal navigation bar, five scoped metric tiles, a candidate table and a tabbed profile. The same profile remains beside the applications list, so opening a candidate keeps the application context visible. Sign-in, job setup, applications, team access, account security, confirmation dialogs and the engineering case study use the same palette. Entry, hover, toast, dialog and tab transitions are short; the reduced-motion media preference disables them.

## Data and feedback

Candidate and job counts are server result totals. Application totals refer to the current application filters. Interview and offer counts refer only to the current application page. Unselected totals use a dash; while refreshing, the last successfully loaded totals can remain visible beside the explicit loading/error state. No synthetic match percentages or unsupported scheduling/analytics controls were added to production.

Notifications are kept in memory, capped at 20 entries, and cleared on organization/job changes and sign-out. Success messages expire after eight seconds while errors remain until dismissed; hover and keyboard focus pause expiry. The notification center supports unread counts, marking read and clearing history. Candidate and notification text uses text nodes. Real records use initials; only the explicit synthetic fixture opts in to the included fictional portraits.

## Run and preview

Run the existing application using the project's documented backend workflow; the workspace remains at `/workspace/`. No Node build or external asset CDN is needed for the production UI.

To export the actual updated frontend as a standalone, synthetic preview:

```powershell
node scripts/design_browser.mjs --export "D:\Projects\AgentHire_Bright_Workspace.html"
Start-Process "D:\Projects\AgentHire_Bright_Workspace.html"
```

Select **Open synthetic workspace**. The export embeds its modules, fonts, icons and images, binds scripts/styles to CSP hashes, and uses `connect-src 'none'`. It exercises navigation, search, candidate details, feedback, confirmation and synthetic application transitions. It is not a substitute for a running API; other fixture mutations may return a safe unsupported-operation error.

## Verification scope

The new verification report accompanies the update package. Historical stage 5–7 manifests and product acceptance hashes are unchanged. They describe their original source checkpoint. In particular, `scripts.portfolio_build` deliberately refuses a changed product source; the old acceptance report must not be relabeled as acceptance of this redesign. Use the standalone export above to review this update before a new release checkpoint is recorded.

Two `.github` workflow files were absent from the supplied archive's working tree and were recovered verbatim from its included Git HEAD. The installer skips them when the same files are already present and refuses to overwrite a different version.

## Asset credits

- Inter variable Latin font: `@fontsource-variable/inter` 5.3.0, SIL Open Font License; license bundled in assets.
- Bootstrap Icons 1.13.2: MIT license; original SVG files and license bundled in assets.
- Six fictional portrait assets were generated for the synthetic demonstration. They are never inferred from real candidates' names or fetched from external services.
