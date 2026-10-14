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

import { orgPath, jobPath } from "./session.mjs";

export function createCandidates(ctx) {
  let items = [];
  let offset = 0;
  let total = 0;
  let generation = 0;
  let timer = null;

  function render() {
    const q = $("candidate-filter").value.trim().toLocaleLowerCase();

    const filtered = items.filter(item =>
      `${item.full_name} ${item.headline ?? ""} ${item.location ?? ""}`
        .toLocaleLowerCase()
        .includes(q),
    );

    $("candidate-list").replaceChildren();
    $("candidate-list-count").textContent =
      `${filtered.length} از ${items.length} داوطلب دریافت‌شده`;

    if (!filtered.length) {
      empty($("candidate-list"), "داوطلبی در این فهرست پیدا نشد.");
      return;
    }

    for (const item of filtered) {
      const card = node("article", "", "candidate-card");
      const heading = node("h3", item.full_name);
      const subtitle = node(
        "p",
        item.headline || "عنوان حرفه‌ای ثبت نشده",
        "muted",
      );
      const place = node(
        "p",
        item.location || "موقعیت ثبت نشده",
        "muted",
      );

      heading.dir = subtitle.dir = place.dir = "auto";

      card.append(
        heading,
        subtitle,
        place,
        button("بررسی پرونده", () => ctx.selectCandidate(item)),
      );

      $("candidate-list").append(card);
    }
  }

  function stop() {
    generation += 1;
    clearInterval(timer);
    timer = null;
    ctx.cancel("retrieval");
    $("retrieval-progress").textContent = "";
  }

  $("candidate-filter").addEventListener("input", render);

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
      async result => {
        if (
          result.organization_id !== ctx.session.organization?.id
        ) {
          throw new Error("INVALID_SCOPE");
        }

        $("candidate-form").reset();
        items.push(result);
        render();

        $("candidates-count").textContent = String(items.length);

        const refreshed = await ctx.selectCandidate(result);

        if (ctx.session.candidate?.id === result.id) {
          notice(
            refreshed === false
              ? "داوطلب ثبت شد؛ فهرست اسناد را تازه‌سازی کنید."
              : "داوطلب ثبت شد.",
            refreshed === false,
          );
        }
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
      "انتظار لغو شد؛ می‌توانید درخواست تازه‌ای ارسال کنید.",
    );

    $("retrieval-progress").textContent =
      "ممکن است پردازش مدل قبلی روی سرور هنوز ادامه داشته باشد.";
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
      ? `${base}/candidate-retrieval?limit=20&offset=${offset}`
      : `${base}/semantic-candidate-retrieval`;

    empty($("retrieval-results"), "در حال بازیابی…");
    $("retrieval-info").textContent = "";
    $("retrieval-next").disabled =
      $("retrieval-previous").disabled = true;

    const progress = () => {
      if (current === generation) {
        $("retrieval-progress").textContent =
          `${Math.floor((performance.now() - started) / 1000)} ثانیه انتظار…`;
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
                applicants_only: false,
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
            badge(`ارتباط: ${hit.score.toFixed(4)}`),
          );

          for (const witness of hit.evidence ?? [hit]) {
            card.append(
              details(
                witness.branch === "semantic"
                  ? "منبع معنایی"
                  : "منبع واژگانی",
                sourceView(witness),
              ),
            );
          }

          card.append(
            button(
              "بررسی پرونده",
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
          ? `${result.items.length} نتیجه؛ کل ${total}؛ از جایگاه ${offset + 1}`
          : `${result.items.length} نتیجه از مجموعهٔ محدود ${total}؛ ${result.embedded_chunks} از ${result.eligible_chunks} بخش دارای embedding${result.pool_truncated ? "؛ مجموعه بریده شده است" : ""}`;

        $("retrieval-next").disabled =
          mode !== "lexical" ||
          offset + 20 >= total ||
          offset >= 1000;

        $("retrieval-previous").disabled =
          mode !== "lexical" || offset === 0;

        if (!result.items.length) {
          empty(
            $("retrieval-results"),
            "با این پروفایل نتیجه‌ای یافت نشد.",
          );
        }
      },
      $("retrieval-run"),
    );

    if (current !== generation) return;

    clearInterval(timer);
    timer = null;

    $("retrieval-progress").textContent =
      "انتظار این درخواست پایان یافت.";

    if (completed === false) {
      empty(
        $("retrieval-results"),
        "بازیابی کامل نشد؛ پیام خطا را بررسی کنید.",
      );
    }
  }

  function clearResults() {
    stop();
    offset = total = 0;

    empty(
      $("retrieval-results"),
      "نتایج جست‌وجوی ذخیره‌شدهٔ شغل اینجا نمایش داده می‌شود.",
    );

    $("retrieval-info").textContent =
      "امتیاز ارتباط، احتمال استخدام یا میزان مهارت نیست.";

    $("retrieval-next").disabled =
      $("retrieval-previous").disabled = true;
  }

  function reset() {
    items = [];
    $("candidate-filter").value = "";
    $("candidate-form").reset();
    render();
    clearResults();
  }

  return {
    setItems(values) {
      items = values;
      render();
    },
    reset,
    clearResults,
  };
}
