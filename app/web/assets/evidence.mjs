import {
  $,
  node,
  button,
  empty,
  badge,
  sourceView,
  details,
  notice,
} from "./dom.mjs";

import { jobPath, uuid } from "./session.mjs";
import { ApiError } from "./api.mjs";
import { createDocuments } from "./documents.mjs";
import { avatar, icon } from "./ui.mjs";

const sourceStates = {
  no_documents: "No documents",
  not_indexed: "Sources have not been indexed yet",
  partial: "Some sources are ready",
  indexed: "Sources are searchable",
};

export function validatePdf(file) {
  if (
    !file ||
    typeof file.name !== "string" ||
    Array.from(file.name).length > 200 ||
    !/\.pdf$/i.test(file.name) ||
    !file.name.slice(0, -4).trim() ||
    !Number.isSafeInteger(file.size) ||
    file.size < 1 ||
    file.size > 10 * 1024 * 1024 ||
    /[\/\\\p{C}]/u.test(file.name)
  ) {
    throw new ApiError(422, "VALIDATION_ERROR");
  }

  return file;
}

export function createEvidence(ctx) {
  let generation = 0;
  let timer = null;
  const documents = createDocuments(ctx, validatePdf);

  function clearGeneration() {
    generation += 1;
    clearInterval(timer);
    timer = null;

    ctx.cancel("explanation");

    $("explanation-cancel").disabled = true;
    $("explanation-run").disabled =
      !ctx.session.job || !ctx.session.candidate;

    $("explanation-progress").textContent = "";
  }

  function clearResults() {
    ctx.cancel("evidence");
    clearGeneration();

    empty(
      $("evidence-results"),
      "Select a candidate and a job, then load evidence or request a grounded brief.",
    );
  }

  function render(result, explanation = false) {
    if (
      result.job_id !== ctx.session.job?.id ||
      result.candidate_id !== ctx.session.candidate?.id
    ) {
      throw new Error("INVALID_SCOPE");
    }

    const content = document.createDocumentFragment();
    const summary = result.summary;

    if (!explanation) content.append(
      node(
        "p",
        `Required evidence: ${summary.required_with_evidence}/${summary.required_total} · Preferred: ${summary.preferred_with_evidence}/${summary.preferred_total}`,
        "summary-note",
      ),
    );

    content.append(
      node(
        "p",
        `${sourceStates[summary.source_status]} · Criteria version ${result.profile_revision}`,
        "small muted",
      ),
    );

    if (explanation) {
      content.append(
        node("p", result.summary_text, "summary-note"),
        node("p", result.scope_note, "small muted"),
      );

      const meta = node(
        "pre",
        JSON.stringify(
          {
            model_tag: result.model_tag,
            model_digest: result.model_digest,
            generator_used: result.generator_used,
            validated_at: result.validated_at,
            elapsed_ms: result.elapsed_ms,
            input_tokens: result.input_tokens,
            output_tokens: result.output_tokens,
          },
          null,
          2,
        ),
        "provenance",
      );

      meta.dir = "ltr";
      content.append(details("Response timing and model provenance", meta));
    }

    for (const criterion of result.criteria) {
      const card = node("article", "", "criterion-result");
      const heading = node("h3", criterion.label);
      heading.dir = "auto";

      heading.append(
        badge(
          criterion.importance === "required"
            ? "Required"
            : "Preferred",
        ),
      );

      card.append(heading);

      card.append(
        node(
          "p",
          criterion.evidence
            ? "Mention found in source text. Review its context below."
            : "No evidence was found in the current sources. This does not establish a lack of skill.",
          "small muted",
        ),
      );

      if (criterion.evidence) {
        if (explanation && !criterion.citation) throw new Error("INVALID_CITATION");
        // Validate the complete source before displaying even a collapsed brief.
        card.append(details(
          "View source evidence",
          sourceView(criterion.evidence, explanation ? criterion.citation : null),
        ));
      }

      content.append(card);
    }

    $("evidence-results").replaceChildren(content);
  }

  function evidencePath() {
    return `${jobPath(ctx.session.organization.id, ctx.session.job.id)}/candidates/${uuid(ctx.session.candidate.id)}`;
  }

  $("evidence-load").addEventListener("click", async () => {
    if (!ctx.session.job || !ctx.session.candidate) return;

    clearResults();

    await ctx.perform(
      "evidence",
      signal => ctx.api.request(
        `${evidencePath()}/match-evidence`,
        { signal },
      ),
      result => render(result),
      $("evidence-load"),
    );
  });

  $("explanation-run").addEventListener("click", async () => {
    if (!ctx.session.job || !ctx.session.candidate) return;

    clearResults();

    const current = ++generation;
    const started = performance.now();

    const progress = () => {
      if (current === generation) {
        $("explanation-progress").textContent =
          `Validating quotes; waiting ${Math.floor((performance.now() - started) / 1000)} seconds…`;
      }
    };

    progress();
    timer = setInterval(progress, 5000);

    $("explanation-cancel").disabled = false;

    const completed = await ctx.perform(
      "explanation",
      signal => ctx.api.request(
        `${evidencePath()}/grounded-explanation`,
        {
          method: "POST",
          signal,
          data: { language: "en" },
          timeout: 185000,
        },
      ),
      result => render(result, true),
      $("explanation-run"),
    );

    if (current === generation) {
      clearInterval(timer);
      timer = null;
      $("explanation-cancel").disabled = true;
      $("explanation-progress").textContent = completed === true
        ? "Grounded brief is ready."
        : completed === false
          ? "Brief generation did not complete. Review the error message."
          : "";
    }
  });

  $("explanation-cancel").addEventListener("click", () => {
    clearGeneration();

    $("explanation-progress").textContent =
      "Waiting cancelled. The previous request may still be running on the server.";
  });

  async function selectCandidate(item) {
    clearResults();
    const identity = node("div", "", "dossier-identity");
    const title = node("h3", item.full_name);
    title.dir = "auto";
    const headline = node("p", item.headline || "No headline provided", "muted");
    headline.dir = "auto";
    identity.append(title, headline);
    if (item.location) {
      const location = node("p", "", "dossier-location");
      location.append(icon("geo-alt"), node("span", item.location));
      identity.append(location);
    }
    const heading = $("candidate-heading");
    if (heading.dataset) heading.dataset.candidateId = item.id;
    heading.replaceChildren(avatar(item, true), identity);
    const overview = $("candidate-overview");
    const summary = node("p", item.summary || "No professional summary has been added yet.", "candidate-summary");
    summary.dir = "auto";
    overview.replaceChildren(node("h3", "About this candidate"), summary);
    const facts = node("dl", "", "candidate-facts");
    for (const [label, value] of [["Email", item.email], ["Location", item.location], ["Phone", item.phone]]) {
      if (!value) continue;
      const detail = node("dd", value);
      detail.dir = "auto";
      facts.append(node("dt", label), detail);
    }
    overview.append(facts);
    const sourceNote = node("div", "", "candidate-source-note");
    sourceNote.append(icon("file-earmark-text"), node("h3", "The full story is in the source"),
      node("p", "Open Resume to manage documents, or Evidence to review criteria against original sources.", "muted small"));
    overview.append(sourceNote);

    $("candidate-fields").disabled = false;
    $("evidence-load").disabled =
      $("explanation-run").disabled = !ctx.session.job;

    return documents.load();
  }

  function reset() {
    clearResults();
    documents.reset();
    $("candidate-fields").disabled = true;

    empty(
      $("candidate-heading"),
      "Select a candidate from the list to review their record.",
    );
    if ($("candidate-heading").dataset) delete $("candidate-heading").dataset.candidateId;
    empty($("candidate-overview"), "Choose a candidate to see their overview.");
  }

  return { reset, selectCandidate, clearResults };
}
