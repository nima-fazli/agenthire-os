# AgentHire OS — portfolio review

AgentHire OS is a private recruiting workspace built with FastAPI,
PostgreSQL/pgvector, vanilla browser modules and local document workers.
Recruiters review source-backed evidence and retain responsibility for decisions.

## Deliverables

- An English case-study page covering the workflow, architecture and tradeoffs.
- An interactive preview built from the actual product UI and synthetic transport.
- A public verification ledger with local evidence and explicit pending checks.
- A content manifest binding the generated files to their presentation source.

Video is not part of this portfolio's completion criteria.
This scope supersedes the video item in the historical completion roadmap.

## Product checkpoint and evidence

The locally verified product checkpoint is
`e331343bdd0384e2e246db4c0770636a1532f064`.
Its 425-file canonical source fingerprint is
`02edce9c435fe62a8569b3821e2a466379d985b175eddc781e08cffeeeeacbdd`.

The owner acceptance run recorded 1,943 Windows Python passes with five platform
skips, 1,948 Docker Python passes, 80 client passes, 35 isolated CI checks and
22 Chromium checks. Both recovery gates and the bounded four-PDF workload passed.
The builder validates the retained acceptance/checkpoint reports and their
browser/workload reports before publishing this summary. Test counts are
recorded from the owner's acceptance console output.

Hosted CI, public HTTPS deployment, hosted workload and host installation,
migration and recovery acceptance remain pending. CI model checks use fixtures;
this local release run did not repeat live-model quality evaluation.

## Build from the owner's verified checkout

Keep the retained reports beside the existing checkout. Use Python 3.12,
Node 24 and the existing locked environment. From the repository root:

```powershell
uv run --locked --no-sync python -m unittest tests.test_portfolio_build -v
uv run --locked --no-sync python -m scripts.portfolio_build
uv run --locked --no-sync python -m scripts.portfolio_build --execute
```

The default output is a content-addressed directory under
`../AgentHire_OS_Portfolio/`. Open the reported `index` path in Chrome or Edge.
Identical builds reuse identical files; a modified generated artifact is rejected.
Generated pages, reports and temporary files stay outside the source repository.

The builder reads the verified 425-file product and these four portfolio additions:
`docs/portfolio/index.html`, `docs/portfolio/README.md`,
`scripts/portfolio_build.py` and `tests/test_portfolio_build.py`.
It rejects unrelated changes. Historical release acceptance remains bound to
its original checkpoint; use the portfolio builder for this presentation stage.

## Five-minute reviewer walkthrough

1. Read the case-study page and its local-verification scope.
2. Select **Explore the workspace**, then **Open synthetic workspace**.
3. Review the six fictional candidate cards and open Alex Morgan's dossier.
4. Open Applications and select **Open candidate** to follow its context.
5. Inspect Setup, Access and Account without submitting data-changing actions.
6. Use the guide and keyboard navigation. Review the layout at a narrow width.
7. Switch to **Empty workspace** and confirm the previous dossier is cleared.
8. Sign out and inspect the verification ledger from the case-study page.

The preview demonstrates navigation, context, empty states and safe feedback.
Its simulated transport does not persist edits, process PDFs, manage invitations
or invoke models. Real backend behavior is evidenced by the separate local
Docker acceptance. Review the configured local `/workspace/` with an authorized
account when a live backend demonstration is needed.

For a reviewer without the owner's receipts, the existing UI-only export remains
available with Node 24:

```powershell
node scripts/design_browser.mjs --export "$env:TEMP\agenthire-workspace-preview.html"
```

## Presentation review

Before sharing, check the built index and preview at desktop and mobile widths,
keyboard focus, readable text at 200% zoom, all local links and the evidence scope.
Share only the generated static presentation directory. Private reports,
credentials, resumes, database data and the local environment stay separate.
