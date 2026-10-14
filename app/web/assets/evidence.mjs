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

import { candidatePath, jobPath, uuid } from "./session.mjs";
import { ApiError } from "./api.mjs";

const sourceStates = {
  no_documents: "سندی وجود ندارد",
  not_indexed: "منابع هنوز بخش‌بندی نشده‌اند",
  partial: "بخشی از منابع آماده است",
  indexed: "منابع قابل جست‌وجو هستند",
};

const extractionStates = {
  queued: "در صف استخراج",
  running: "در حال استخراج",
  succeeded: "استخراج موفق",
  failed: "استخراج ناموفق",
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
  let documentOffset = 0;

  const blobs = new Set();

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
      "یک داوطلب و شغل انتخاب کنید؛ سپس شواهد یا توضیح مستند را بخوانید.",
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

    content.append(
      node(
        "p",
        `شاهد ضروری: ${summary.required_with_evidence}/${summary.required_total} · ترجیحی: ${summary.preferred_with_evidence}/${summary.preferred_total}`,
        "summary-note",
      ),
    );

    content.append(
      node(
        "p",
        `${sourceStates[summary.source_status]} · نسخهٔ معیارها ${result.profile_revision}`,
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
      content.append(details("زمان و مدل این پاسخ", meta));
    }

    for (const criterion of result.criteria) {
      const card = node("article", "", "criterion-result");
      const heading = node("h3", criterion.label);
      heading.dir = "auto";

      heading.append(
        badge(
          criterion.importance === "required"
            ? "ضروری"
            : "ترجیحی",
        ),
      );

      card.append(heading);

      card.append(
        node(
          "p",
          explanation
            ? criterion.text
            : criterion.evidence
              ? "شاهد واژگانی مشاهده شد؛ متن اصلی را بررسی کنید."
              : "شاهدی در منابع فعلی یافت نشد؛ این نتیجه به معنی نداشتن مهارت نیست.",
          "small muted",
        ),
      );

      if (criterion.evidence) {
        card.append(
          sourceView(
            criterion.evidence,
            explanation ? criterion.citation : null,
          ),
        );
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
          `در حال بررسی نقل‌قول‌ها؛ ${Math.floor((performance.now() - started) / 1000)} ثانیه انتظار…`;
      }
    };

    progress();
    timer = setInterval(progress, 5000);

    $("explanation-cancel").disabled = false;

    await ctx.perform(
      "explanation",
      signal => ctx.api.request(
        `${evidencePath()}/grounded-explanation`,
        {
          method: "POST",
          signal,
          data: { language: "fa" },
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
      $("explanation-progress").textContent =
        "انتظار این درخواست پایان یافت.";
    }
  });

  $("explanation-cancel").addEventListener("click", () => {
    clearGeneration();

    $("explanation-progress").textContent =
      "انتظار لغو شد؛ ممکن است پردازش قبلی روی سرور هنوز ادامه داشته باشد.";
  });

  function documentBase() {
    return `${candidatePath(ctx.session.organization.id, ctx.session.candidate.id)}/documents`;
  }

  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    blobs.add(url);

    const anchor = node("a");
    anchor.href = url;
    anchor.download = filename;

    document.body.append(anchor);
    anchor.click();
    anchor.remove();

    setTimeout(() => {
      URL.revokeObjectURL(url);
      blobs.delete(url);
    }, 1000);
  }

  async function loadDocuments() {
    if (!ctx.session.candidate) return;

    const base = documentBase();

    return ctx.perform(
      "documents",
      signal => ctx.api.request(
        `${base}?limit=10&offset=${documentOffset}`,
        { signal },
      ),
      items => {
        $("documents-list").replaceChildren();

        $("documents-info").textContent =
          `نمایش ${items.length} سند از جایگاه ${documentOffset + 1}؛ وضعیت استخراج را تازه‌سازی کنید.`;

        $("documents-previous").disabled = documentOffset === 0;
        $("documents-next").disabled = items.length < 10;

        if (!items.length) {
          empty(
            $("documents-list"),
            "هنوز رزومه‌ای برای این داوطلب بارگذاری نشده است.",
          );
        }

        for (const item of items) {
          if (
            item.candidate_id !== ctx.session.candidate.id ||
            item.organization_id !== ctx.session.organization.id
          ) {
            throw new Error("INVALID_SCOPE");
          }

          const path = `${base}/${uuid(item.id)}`;
          const card = node("article", "", "document-card");
          const title = node("h3", item.filename);
          title.dir = "auto";

          const state = node(
            "p",
            `${(item.size_bytes / 1024).toFixed(1)} KiB · وضعیت استخراج بررسی نشده`,
            "small muted",
          );

          const actions = node("div", "", "actions");

          const status = button(
            "وضعیت استخراج",
            () => ctx.perform(
              "document-read",
              signal => ctx.api.request(
                `${path}/extraction`,
                { signal },
              ).catch(error => {
                if (error.code === "EXTRACTION_NOT_FOUND") {
                  return { status: "not_requested" };
                }

                throw error;
              }),
              value => {
                state.textContent =
                  extractionStates[value.status] ??
                  "استخراج هنوز درخواست نشده است";
              },
              status,
            ),
          );

          const extract = button("شروع / تکرار استخراج", () => {
            ctx.cancel("document-read");
            ctx.invalidateEvidence();

            return ctx.perform(
              "document-write",
              signal => ctx.api.request(`${path}/extraction`, {
                method: "POST",
                data: { retry: true },
                signal,
              }),
              value => {
                state.textContent = extractionStates[value.status];
                notice(
                  "درخواست استخراج ثبت شد؛ وضعیت آن را تازه‌سازی کنید.",
                );
              },
              extract,
              true,
            );
          });

          const chunks = button("ساخت بخش‌های جست‌وجو", () => {
            ctx.cancel("document-read");
            ctx.invalidateEvidence();

            return ctx.perform(
              "document-write",
              signal => ctx.api.request(`${path}/chunks`, {
                method: "POST",
                data: {},
                signal,
              }),
              () => {
                state.textContent = "بخش‌های جست‌وجو آماده شد.";
                ctx.profileChanged();
              },
              chunks,
              true,
            );
          });

          const get = button(
            "دانلود PDF",
            () => ctx.perform(
              "download",
              signal => ctx.api.request(`${path}/content`, {
                signal,
                blob: true,
              }),
              value => download(value, item.filename),
              get,
            ),
          );

          actions.append(status, extract, chunks, get);
          card.append(title, state, actions);
          $("documents-list").append(card);
        }
      },
      $("documents-refresh"),
    );
  }

  $("document-form").addEventListener("submit", async event => {
    event.preventDefault();

    if (!ctx.session.candidate) return;

    ctx.invalidateEvidence();

    await ctx.perform(
      "upload",
      signal => {
        const file = validatePdf($("document-file").files[0]);

        return ctx.api.request(
          `${documentBase()}?${new URLSearchParams({ filename: file.name })}`,
          {
            method: "POST",
            body: file,
            signal,
            timeout: 65000,
          },
        );
      },
      async (_value, current) => {
        $("document-form").reset();
        documentOffset = 0;

        const refreshed = await loadDocuments();

        if (current()) {
          notice(
            refreshed === false
              ? "رزومه ثبت شد؛ فهرست اسناد را تازه‌سازی کنید."
              : "رزومه بارگذاری شد.",
            refreshed === false,
          );
        }
      },
      $("document-upload"),
      true,
    );
  });

  $("documents-refresh").addEventListener("click", loadDocuments);

  $("documents-next").addEventListener("click", () => {
    documentOffset += 10;
    loadDocuments();
  });

  $("documents-previous").addEventListener("click", () => {
    documentOffset = Math.max(0, documentOffset - 10);
    loadDocuments();
  });

  async function selectCandidate(item) {
    documentOffset = 0;
    clearResults();

    $("candidate-heading").replaceChildren(
      node("h3", item.full_name),
      node(
        "p",
        item.headline || "عنوان حرفه‌ای ثبت نشده",
        "muted",
      ),
    );

    $("candidate-fields").disabled = false;
    $("evidence-load").disabled =
      $("explanation-run").disabled = !ctx.session.job;

    return loadDocuments();
  }

  function reset() {
    clearResults();
    documentOffset = 0;

    for (const key of [
      "documents",
      "document-read",
      "document-write",
      "download",
      "upload",
    ]) {
      ctx.cancel(key);
    }

    for (const url of blobs) URL.revokeObjectURL(url);
    blobs.clear();

    $("candidate-fields").disabled = true;
    $("document-form").reset();
    $("documents-info").textContent = "";
    $("documents-list").replaceChildren();
    $("documents-previous").disabled =
      $("documents-next").disabled = true;

    empty(
      $("candidate-heading"),
      "برای بررسی، یک داوطلب را از فهرست انتخاب کنید.",
    );
  }

  return { reset, selectCandidate, clearResults };
}
