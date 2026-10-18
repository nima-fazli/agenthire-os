import { $ } from "./dom.mjs";
import { candidatePath, jobPath, orgPath } from "./session.mjs";
import { mutationNotice } from "./paging.mjs";

export function createEditors(ctx) {
  const fields = {
    job: ["title", "description", "status"],
    candidate: ["full_name", "email", "phone", "headline", "location", "summary"],
  };
  const current = kind => ctx.session[kind];
  const prefix = kind => kind === "job" ? "job" : "candidate";

  function show(kind, record) {
    for (const name of fields[kind])
      $(`${prefix(kind)}-edit-${name}`).value = record?.[name] ?? "";
    $(`${kind}-edit-version`).textContent = record ? "ویرایش بر اساس آخرین نسخهٔ خوانده‌شده" : "ابتدا یک مورد انتخاب کنید.";
  }

  for (const kind of ["job", "candidate"]) {
    $(`${kind}-edit-form`).addEventListener("submit", async event => {
      event.preventDefault();
      const record = current(kind), org = ctx.session.organization;
      if (!record || !org) return;
      const data = { expected_updated_at: record.updated_at };
      for (const name of fields[kind]) {
        const text = $(`${kind}-edit-${name}`).value.trim();
        data[name] = kind === "candidate" && name !== "full_name" ? text || null : text;
      }
      await ctx.perform(`edit-${kind}`, signal => ctx.api.request(
        `${orgPath(org.id)}/recruiting/${kind === "job" ? "jobs" : "candidates"}/${record.id}`,
        { method: "PUT", data, signal },
      ), async (updated, owned) => {
        if (updated.id !== record.id || updated.organization_id !== org.id) throw new Error("INVALID_SCOPE");
        const selected = kind === "job" ? await ctx.selectJob(updated) : await ctx.selectCandidate(updated);
        if (!owned()) return;
        const refreshed = kind === "job" ? await ctx.workspace.loadJobs() : await ctx.candidates.load();
        if (owned()) mutationNotice(kind === "job" ? "شغل ویرایش شد" : "پرونده ویرایش شد",
          selected === false || refreshed === false ? false : true);
      }, $(`${kind}-edit-fields`), true);
    });
    $(`${kind}-edit-refresh`).addEventListener("click", async () => {
      const record = current(kind), org = ctx.session.organization;
      if (!record || !org) return;
      await ctx.perform(`refresh-${kind}`, signal => ctx.api.request(
        kind === "job" ? jobPath(org.id, record.id) : candidatePath(org.id, record.id), { signal },
      ), async updated => {
        if (updated.id !== record.id || updated.organization_id !== org.id) throw new Error("INVALID_SCOPE");
        if (kind === "job") await ctx.selectJob(updated);
        else await ctx.selectCandidate(updated);
      }, $(`${kind}-edit-refresh`));
    });
  }
  return {
    showJob: value => show("job", value),
    showCandidate: value => show("candidate", value),
    reset() { show("job", null); show("candidate", null); },
  };
}
