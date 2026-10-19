import { $, node, button, empty, notice } from "./dom.mjs";
import { candidatePath, uuid } from "./session.mjs";
import { mutationNotice } from "./paging.mjs";

const states = Object.freeze({ queued: "در صف", running: "در حال پردازش", succeeded: "موفق", failed: "ناموفق" });

export function createDocuments(ctx, validatePdf) {
  let offset = 0;
  const urls = new Set(), jobs = new Map();
  const base = () => ctx.session.candidate
    ? `${candidatePath(ctx.session.organization.id, ctx.session.candidate.id)}/documents` : null;

  function writeButton(text, work, className) {
    const control = button(text, work, className);
    control.requiresWrite = true;
    control.disabled = !ctx.access.canWrite;
    return control;
  }

  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    urls.add(url);
    const anchor = node("a");
    anchor.href = url; anchor.download = filename;
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => { URL.revokeObjectURL(url); urls.delete(url); }, 1000);
  }

  function action(path, work, done, mutation = false) {
    if (base() !== path.slice(0, path.lastIndexOf("/"))) return null;
    if (mutation) { ctx.cancel("document-read"); ctx.invalidateEvidence(); }
    return ctx.perform(mutation ? "document-write" : "document-read", work, done,
      $("document-tools"), mutation);
  }

  async function load() {
    const root = base();
    if (!root) return null;
    ctx.cancel("document-read");
    $("documents-previous").disabled = $("documents-next").disabled = true;
    empty($("documents-list"), "در حال دریافت اسناد…");
    return ctx.perform("documents", async signal => {
      let items = await ctx.api.request(`${root}?limit=11&offset=${offset}`, { signal });
      if (!Array.isArray(items) || items.length > 11) throw new Error("INVALID_RESPONSE");
      if (!items.length && offset) {
        offset = Math.max(0, offset - 10);
        items = await ctx.api.request(`${root}?limit=11&offset=${offset}`, { signal });
      }
      return items;
    }, items => {
      if (!Array.isArray(items) || items.length > 11) throw new Error("INVALID_RESPONSE");
      const content = document.createDocumentFragment();
      for (const item of items.slice(0, 10)) {
        if (item.organization_id !== ctx.session.organization?.id || item.candidate_id !== ctx.session.candidate?.id)
          throw new Error("INVALID_SCOPE");
        const path = `${root}/${uuid(item.id)}`;
        const card = node("article", "", "document-card"), title = node("h3", item.filename);
        title.dir = "auto";
        const state = node("p", `${(item.size_bytes / 1024).toFixed(1)} KiB`, "small muted");
        const actions = node("div", "", "actions");
        actions.append(
          button("وضعیت استخراج", () => action(path,
            signal => ctx.api.request(`${path}/extraction`, { signal }).catch(error => {
              if (error.code === "EXTRACTION_NOT_FOUND") return { status: "not_requested" };
              throw error;
            }), value => { state.textContent = states[value.status] ?? "استخراج درخواست نشده است."; })),
          writeButton("شروع / تکرار استخراج", () => action(path,
            signal => ctx.api.request(`${path}/extraction`, { method: "POST", data: { retry: true }, signal }),
            value => { state.textContent = states[value.status]; clearEmbedding(); notice("درخواست استخراج ثبت شد؛ وضعیت را تازه‌سازی کنید."); }, true)),
          writeButton("ساخت بخش‌های جست‌وجو", () => action(path,
            signal => ctx.api.request(`${path}/chunks`, { method: "POST", data: {}, signal }),
            () => { state.textContent = "بخش‌های جست‌وجو آماده شد."; clearEmbedding(); ctx.profileChanged(); }, true)),
          button("دانلود PDF", () => action(path,
            signal => ctx.api.request(`${path}/content`, { signal, blob: true }),
            value => download(value, item.filename))),
        );
        const embedding = node("p", "وضعیت بردار معنایی بررسی نشده است.", "small muted");
        const refresh = button("تازه‌سازی وضعیت بردار", () => {
          const job = jobs.get(item.id);
          if (!job) return;
          return action(path, signal => ctx.api.request(`${path}/embedding-jobs/${uuid(job.id)}`, { signal }), showEmbedding);
        });
        refresh.disabled = !jobs.has(item.id);
        function clearEmbedding() {
          jobs.delete(item.id); refresh.disabled = true;
          embedding.textContent = "پس از آماده‌شدن بخش‌ها، وضعیت پردازش معنایی را دوباره بخوانید.";
        }
        function showEmbedding(job) {
          uuid(job.id);
          if (!Object.hasOwn(states, job.status) || job.model_tag !== "qwen3-embedding:0.6b"
              || !Number.isSafeInteger(job.chunk_count) || job.chunk_count < 1
              || !Number.isSafeInteger(job.attempts) || job.attempts < 0)
            throw new Error("INVALID_RESPONSE");
          jobs.set(item.id, job);
          embedding.textContent = `بردار معنایی: ${states[job.status]} · ${job.chunk_count} بخش · تلاش ${job.attempts}`;
          refresh.disabled = false;
        }
        if (jobs.has(item.id)) showEmbedding(jobs.get(item.id));
        actions.append(
          writeButton("شروع / مشاهدهٔ بردار معنایی", () => action(path,
            signal => ctx.api.request(`${path}/embedding-jobs`, {
              method: "POST", data: { retry: jobs.get(item.id)?.status === "failed" }, signal,
            }), value => { showEmbedding(value); notice("وضعیت بردار دریافت شد؛ برای پیگیری، وضعیت را تازه‌سازی کنید."); }, true)),
          refresh,
          writeButton("حذف PDF", async () => {
            const accepted = await ctx.confirm.ask({ title: "حذف رزومه",
              message: `فایل «${item.filename}» و داده‌های استخراج و جست‌وجوی وابسته به آن حذف می‌شوند.`,
              requiredText: item.filename });
            if (!accepted || base() !== root) return;
            await action(path, signal => ctx.api.request(path, { method: "DELETE", signal }),
              async (_value, owned) => {
                jobs.delete(item.id);
                const refreshed = await load();
                if (owned()) mutationNotice("رزومه حذف شد", refreshed);
              }, true);
          }, "button danger"),
        );
        card.append(title, state, embedding, actions); content.append(card);
      }
      $("documents-list").replaceChildren(content);
      if (!items.length) empty($("documents-list"), "هنوز رزومه‌ای بارگذاری نشده است.");
      $("documents-info").textContent = items.length
        ? `${offset + 1} تا ${offset + Math.min(10, items.length)}؛ وضعیت پردازش را با دکمه‌های هر سند بررسی کنید.`
        : "سندی یافت نشد.";
      $("documents-previous").disabled = offset === 0;
      $("documents-next").disabled = items.length <= 10 || offset >= 10000;
    }, $("documents-refresh"));
  }

  $("document-form").addEventListener("submit", async event => {
    event.preventDefault();
    const root = base();
    if (!root) return;
    ctx.invalidateEvidence();
    await ctx.perform("upload", signal => {
      const file = validatePdf($("document-file").files[0]);
      return ctx.api.request(`${root}?${new URLSearchParams({ filename: file.name })}`, {
        method: "POST", body: file, signal, timeout: 65000,
      });
    }, async (_value, owned) => {
      $("document-form").reset(); offset = 0;
      const refreshed = await load();
      if (owned()) notice(refreshed === false ? "رزومه ثبت شد؛ فهرست اسناد را تازه‌سازی کنید." : "رزومه بارگذاری شد.", refreshed === false);
    }, $("document-tools"), true);
  });
  $("documents-refresh").addEventListener("click", load);
  $("documents-next").addEventListener("click", () => { if (!$("documents-next").disabled) { offset += 10; load(); } });
  $("documents-previous").addEventListener("click", () => { if (!$("documents-previous").disabled) { offset = Math.max(0, offset - 10); load(); } });

  return {
    load,
    reset() {
      for (const key of ["documents", "document-read", "document-write", "upload"]) ctx.cancel(key);
      for (const url of urls) URL.revokeObjectURL(url);
      urls.clear(); jobs.clear(); offset = 0;
      $("document-form").reset();
      $("documents-info").textContent = "";
      $("documents-list").replaceChildren();
      $("documents-previous").disabled = $("documents-next").disabled = true;
    },
  };
}
