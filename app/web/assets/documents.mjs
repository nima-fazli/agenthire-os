import { $, node, button, empty, notice } from "./dom.mjs";
import { candidatePath, uuid } from "./session.mjs";
import { mutationNotice } from "./paging.mjs";

const states = Object.freeze({ queued: "Queued", running: "Running", succeeded: "Succeeded", failed: "Failed" });
const failures = Object.freeze({
  PDF_NO_TEXT: "No selectable text was found. Upload a PDF with selectable text; scanned images need OCR first.",
  PDF_ENCRYPTED: "The PDF is encrypted. Upload an unencrypted copy.",
  PDF_INVALID: "The PDF could not be read. Export it again and upload the new copy.",
  PDF_PAGE_LIMIT: "The PDF exceeds the configured page limit. Upload a shorter document.",
  PDF_TEXT_LIMIT: "The PDF exceeds the configured text limit. Upload a shorter document.",
  PDF_TIMEOUT: "PDF extraction timed out. Try a smaller PDF.",
  PDF_RESOURCE_LIMIT: "PDF extraction exceeded its resource limit. Try a smaller PDF.",
  PDF_TOOLS_UNAVAILABLE: "PDF extraction tools are unavailable on the server.",
  PDF_INTEGRITY_MISMATCH: "The stored PDF could not be verified. Upload a new copy.",
  EMBEDDING_PROVIDER_UNAVAILABLE: "The local retrieval model is unavailable. Check the model service before retrying.",
  EMBEDDING_PROVIDER_TIMEOUT: "The local retrieval model timed out. Check its service before retrying.",
  EMBEDDING_MODEL_NOT_INSTALLED: "The local retrieval model is not installed.",
  EMBEDDING_MODEL_CHANGED: "The retrieval model changed during processing. Retry with the configured model.",
});

function failureDetail(value) {
  if (value.status !== "failed") return "";
  const message = Object.hasOwn(failures, value.failure_code) ? failures[value.failure_code]
    : "Processing failed. Check the server logs for details.";
  return ` · ${message}`;
}

function extractionStatus(value) {
  if (value.status === "not_requested") return "Extraction has not been requested.";
  if (!Object.hasOwn(states, value.status)) throw new Error("INVALID_RESPONSE");
  return `Extraction: ${states[value.status]}${failureDetail(value)}`;
}

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
    empty($("documents-list"), "Loading documents…");
    const completed = await ctx.perform("documents", async signal => {
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
          button("Extraction status", () => action(path,
            signal => ctx.api.request(`${path}/extraction`, { signal }).catch(error => {
              if (error.code === "EXTRACTION_NOT_FOUND") return { status: "not_requested" };
              throw error;
            }), value => { state.textContent = extractionStatus(value); })),
          writeButton("Start / retry extraction", () => action(path,
            signal => ctx.api.request(`${path}/extraction`, { method: "POST", data: { retry: true }, signal }),
            value => { state.textContent = extractionStatus(value); clearEmbedding(); notice("Extraction requested. Refresh its status to follow progress."); }, true)),
          writeButton("Build search chunks", () => action(path,
            signal => ctx.api.request(`${path}/chunks`, { method: "POST", data: {}, signal }),
            () => { state.textContent = "Search chunks are ready."; clearEmbedding(); ctx.profileChanged(); }, true)),
          button("Download PDF", () => action(path,
            signal => ctx.api.request(`${path}/content`, { signal, blob: true }),
            value => download(value, item.filename))),
        );
        const embedding = node("p", "Embedding status has not been checked.", "small muted");
        const refresh = button("Refresh embedding status", () => {
          const job = jobs.get(item.id);
          if (!job) return;
          return action(path, signal => ctx.api.request(`${path}/embedding-jobs/${uuid(job.id)}`, { signal }), showEmbedding);
        });
        refresh.disabled = !jobs.has(item.id);
        function clearEmbedding() {
          jobs.delete(item.id); refresh.disabled = true;
          embedding.textContent = "After chunks are ready, select Start / view embeddings.";
        }
        function showEmbedding(job) {
          uuid(job.id);
          if (!Object.hasOwn(states, job.status) || job.model_tag !== "qwen3-embedding:0.6b"
              || !Number.isSafeInteger(job.chunk_count) || job.chunk_count < 1
              || !Number.isSafeInteger(job.attempts) || job.attempts < 0)
            throw new Error("INVALID_RESPONSE");
          jobs.set(item.id, job);
          embedding.textContent = `Embeddings: ${states[job.status]} · ${job.chunk_count} chunks · attempt ${job.attempts}${failureDetail(job)}`;
          refresh.disabled = false;
        }
        if (jobs.has(item.id)) showEmbedding(jobs.get(item.id));
        actions.append(
          writeButton("Start / view embeddings", () => action(path,
            signal => ctx.api.request(`${path}/embedding-jobs`, {
              method: "POST", data: { retry: jobs.get(item.id)?.status === "failed" }, signal,
            }), value => { showEmbedding(value); notice("Embedding status loaded. Refresh it to follow progress."); }, true)),
          refresh,
          writeButton("Delete PDF", async () => {
            const accepted = await ctx.confirm.ask({ title: "Delete resume",
              message: `The file “${item.filename}” and its extracted text and search data will be deleted.`,
              requiredText: item.filename });
            if (!accepted || base() !== root) return;
            await action(path, signal => ctx.api.request(path, { method: "DELETE", signal }),
              async (_value, owned) => {
                jobs.delete(item.id);
                const refreshed = await load();
                if (owned()) mutationNotice("Resume deleted", refreshed);
              }, true);
          }, "button danger"),
        );
        card.append(title, state, embedding, actions); content.append(card);
      }
      $("documents-list").replaceChildren(content);
      if (!items.length) empty($("documents-list"), "No resumes have been uploaded yet.");
      $("documents-info").textContent = items.length
        ? `${offset + 1} to ${offset + Math.min(10, items.length)}; use each document's controls to check processing status.`
        : "No documents found.";
      $("documents-previous").disabled = offset === 0;
      $("documents-next").disabled = items.length <= 10 || offset >= 10000;
    }, $("documents-refresh"));
    if (completed === false && base() === root) {
      empty($("documents-list"), "Documents could not be loaded. Refresh documents to try again.");
      $("documents-info").textContent = "Loading failed";
      $("documents-previous").disabled = offset === 0;
      $("documents-next").disabled = true;
    }
    return completed;
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
      if (owned()) notice(refreshed === false ? "Resume saved. Refresh the document list." : "Resume uploaded.", refreshed === false);
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
