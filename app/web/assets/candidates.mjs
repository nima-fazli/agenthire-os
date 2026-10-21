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

import { orgPath, jobPath, uuid } from "./session.mjs";
import { createPager, mutationNotice } from "./paging.mjs";
import { avatar, icon } from "./ui.mjs";

export function createCandidates(ctx) {
  let offset = 0;
  let total = 0;
  let generation = 0;
  let timer = null;

  const pager = createPager(ctx, {
    name: "candidate", url: () => ctx.session.organization
      ? `${orgPath(ctx.session.organization.id)}/recruiting/candidates` : null,
    filters: () => ({ q: $("candidate-filter").value.trim() }),
    clear: text => {
      empty($("candidate-list"), text);
      $("candidate-list-count").textContent = $("candidates-count").textContent = "—";
    },
    render(page) {
      const content = document.createDocumentFragment();
      for (const item of page.items) {
        uuid(item.id);
        if (item.organization_id !== ctx.session.organization?.id) throw new Error("INVALID_SCOPE");
        const card = node("article", "", "candidate-card");
        if (card.dataset) card.dataset.candidateId = item.id;
        const person = node("div", "", "candidate-person");
        const identity = node("div", "", "candidate-identity");
        const heading = node("h3", item.full_name);
        const subtitle = node("p", item.headline || "No headline provided", "muted");
        const place = node("p", item.location || "No location provided", "muted");
        heading.dir = subtitle.dir = place.dir = "auto";
        identity.append(heading, subtitle);
        person.append(avatar(item), identity);
        const review = button("Review candidate", () => ctx.selectCandidate(item), "button quiet candidate-open");
        review.append(icon("arrow-up-right"));
        card.append(person, place, review);
        content.append(card);
      }
      $("candidate-list").replaceChildren(content);
      if (!page.items.length) empty($("candidate-list"), "No candidates match this search.");
      $("candidate-list-count").textContent = `${page.total} results`;
      $("candidates-count").textContent = String(page.total);
    },
  });

  function stop() {
    generation += 1;
    clearInterval(timer);
    timer = null;
    ctx.cancel("retrieval");
    $("retrieval-progress").textContent = "";
  }

  $("candidate-form").addEventListener("submit", async event => {
    event.preventDefault();

    if (!ctx.session.organization) return;

    const data = {
      full_name: $("candidate-name").value.trim(),
    };

    for (const key of ["email", "headline", "location"]) {
      const value = $(`candidate-${key}`).value.trim();
      if (value) data[key] = value;
    }

    await ctx.perform(
      "candidate-create",
      signal => ctx.api.request(
        `${orgPath(ctx.session.organization.id)}/candidates`,
        { method: "POST", signal, data },
      ),
      async (result, owned) => {
        if (
          result.organization_id !== ctx.session.organization?.id
        ) {
          throw new Error("INVALID_SCOPE");
        }

        $("candidate-form").reset();
        $("candidate-filter").value = "";
        const listed = await pager.load({ reset: true });
        if (!owned()) return;
        const selected = await ctx.selectCandidate(result);
        if (owned()) mutationNotice("Candidate created", listed === false || selected === false ? false : true);
      },
      $("candidate-create"),
      true,
    );
  });

  $("retrieval-form").addEventListener("submit", event => {
    event.preventDefault();
    offset = 0;
    retrieve();
  });

  $("retrieval-mode").addEventListener("change", clearResults);
  $("retrieval-applicants").addEventListener("change", clearResults);

  $("retrieval-next").addEventListener("click", () => {
    offset += 20;
    retrieve();
  });

  $("retrieval-previous").addEventListener("click", () => {
    offset = Math.max(0, offset - 20);
    retrieve();
  });

  $("retrieval-cancel").addEventListener("click", () => {
    stop();
    empty(
      $("retrieval-results"),
      "Waiting cancelled. You can submit a new request.",
    );

    $("retrieval-progress").textContent =
      "The previous model request may still be running on the server.";
  });

  async function retrieve() {
    const org = ctx.session.organization;
    const job = ctx.session.job;

    if (!org || !job || !ctx.profilesReady) return;

    stop();

    const current = generation;
    const started = performance.now();
    const mode = $("retrieval-mode").value;
    const base = jobPath(org.id, job.id);

    const path = mode === "lexical"
      ? `${base}/candidate-retrieval?limit=20&offset=${offset}&applicants_only=${$("retrieval-applicants").checked}`
      : `${base}/semantic-candidate-retrieval`;

    empty($("retrieval-results"), "Retrieving candidates…");
    $("retrieval-info").textContent = "";
    $("retrieval-next").disabled =
      $("retrieval-previous").disabled = true;

    const progress = () => {
      if (current === generation) {
        $("retrieval-progress").textContent =
          `Waiting ${Math.floor((performance.now() - started) / 1000)} seconds…`;
      }
    };

    progress();
    timer = setInterval(progress, 5000);

    const completed = await ctx.perform(
      "retrieval",
      signal => ctx.api.request(path, {
        signal,
        timeout: 125000,
        ...(mode === "lexical"
          ? {}
          : {
              method: "POST",
              data: {
                mode,
                limit: 20,
                min_similarity: 0,
                applicants_only: $("retrieval-applicants").checked,
              },
            }),
      }),
      result => {
        if (
          result.job_id !== job.id ||
          !Array.isArray(result.items)
        ) {
          throw new Error("INVALID_SCOPE");
        }

        const content = document.createDocumentFragment();

        for (const hit of result.items) {
          if (!Number.isFinite(hit.score)) {
            throw new Error("INVALID_RESPONSE");
          }

          const card = node("article", "", "result-card");
          const title = node("h3", hit.candidate_name);
          title.dir = "auto";

          card.append(
            title,
            badge(`Relevance: ${hit.score.toFixed(4)}`),
          );

          for (const witness of hit.evidence ?? [hit]) {
            card.append(
              details(
                witness.branch === "semantic"
                  ? "Semantic source"
                  : "Lexical source",
                sourceView(witness),
              ),
            );
          }

          card.append(
            button(
              "Review candidate",
              () => ctx.selectCandidateId(hit.candidate_id),
            ),
          );

          content.append(card);
        }

        $("retrieval-results").replaceChildren(content);

        total = mode === "lexical"
          ? result.total
          : result.pooled_count;

        $("retrieval-info").textContent = mode === "lexical"
          ? `${result.items.length} results; ${total} total; starting at ${offset + 1}`
          : `${result.items.length} results from a bounded pool of ${total}; ${result.embedded_chunks} of ${result.eligible_chunks} chunks embedded${result.pool_truncated ? "; pool truncated" : ""}`;

        $("retrieval-next").disabled =
          mode !== "lexical" ||
          offset + 20 >= total ||
          offset >= 1000;

        $("retrieval-previous").disabled =
          mode !== "lexical" || offset === 0;

        if (!result.items.length) {
          empty(
            $("retrieval-results"),
            "No results match this job profile.",
          );
        }
      },
      $("retrieval-run"),
    );

    if (current !== generation) return;

    clearInterval(timer);
    timer = null;

    $("retrieval-progress").textContent = completed === true
      ? "Retrieval complete."
      : completed === false
        ? "Retrieval did not complete. Review the error message."
        : "";

    if (completed === false) {
      empty(
        $("retrieval-results"),
        "Retrieval did not complete. Review the error message.",
      );
    }
  }

  function clearResults() {
    stop();
    offset = total = 0;

    empty(
      $("retrieval-results"),
      "Results from the saved job search profile appear here.",
    );

    $("retrieval-info").textContent =
      "Relevance scores are not hiring probabilities or measures of proficiency.";

    $("retrieval-next").disabled =
      $("retrieval-previous").disabled = true;
  }

  function reset() {
    pager.reset();
    $("candidate-filter").value = "";
    $("candidate-form").reset();
    $("retrieval-applicants").checked = false;
    clearResults();
  }

  return {
    load: () => pager.load(),
    reset,
    clearResults,
  };
}
