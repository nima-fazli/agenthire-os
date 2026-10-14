import { $, node, field, button, notice } from "./dom.mjs";
import { jobPath } from "./session.mjs";
import { ApiError } from "./api.mjs";

export function profilePayload(rows) {
  if (!Array.isArray(rows) || rows.some(item => !item || typeof item.key !== "string" || typeof item.label !== "string" || typeof item.q !== "string"))
    throw new ApiError(422, "VALIDATION_ERROR");
  const criteria = rows.map(item => ({ key: item.key, label: item.label.trim(), q: item.q.trim(), importance: item.importance }));
  if (!criteria.length || criteria.length > 10 || new Set(criteria.map(item => item.key)).size !== criteria.length
      || criteria.some(item => !/^[a-z][a-z0-9_-]{0,39}$/.test(item.key) || !item.label || Array.from(item.label).length > 100
        || !item.q || Array.from(item.q).length > 256 || !["required", "preferred"].includes(item.importance)))
    throw new ApiError(422, "VALIDATION_ERROR");
  return { criteria };
}
export function createProfiles(ctx) {
  let rows = [], nextKey = 1;
  function addRow(item = null) {
    if (rows.length >= 10) { notice("حداکثر ده معیار می‌توانید تعریف کنید.", true); return; }
    let key = item?.key;
    if (!key) do { key = `criterion_${nextKey++}`; } while (rows.some(row => row.key === key));
    const row = node("div", "", "criterion-row");
    const label = field("عنوان معیار", { value: item?.label, required: true, max: 100 });
    const query = field("واژه‌های مورد جست‌وجو", { value: item?.q, required: true, max: 256 });
    const importance = field("اهمیت", { value: item?.importance ?? "required", options: [["required", "ضروری"], ["preferred", "ترجیحی"]] });
    const record = { key, row, label, query, importance };
    const remove = button("حذف معیار", () => { rows = rows.filter(value => value !== record); row.remove(); }, "button quiet");
    row.append(label.wrapper, query.wrapper, importance.wrapper, remove);
    rows.push(record); $("criteria-list").append(row);
  }
  $("criterion-add").addEventListener("click", () => addRow());
  $("match-profile-form").addEventListener("submit", async event => {
    event.preventDefault();
    const job = ctx.session.job, org = ctx.session.organization;
    if (!job || !org) return;
    ctx.invalidateEvidence();
    await ctx.perform("profile-save", signal => ctx.api.request(`${jobPath(org.id, job.id)}/match-profile`, {
      method: "PUT", signal, data: profilePayload(rows.map(row => ({ key: row.key, label: row.label.input.value,
        q: row.query.input.value, importance: row.importance.input.value }))),
    }), result => { $("match-revision").textContent = `نسخهٔ معیارها: ${result.revision}`; ctx.profileChanged(); }, $("match-save"), true);
  });
  $("search-profile-form").addEventListener("submit", async event => {
    event.preventDefault();
    const job = ctx.session.job, org = ctx.session.organization;
    if (!job || !org) return;
    ctx.invalidateEvidence();
    await ctx.perform("search-save", signal => ctx.api.request(`${jobPath(org.id, job.id)}/search-profile`, {
      method: "PUT", signal, data: { q: $("search-query").value.trim() },
    }), result => { $("search-revision").textContent = `نسخهٔ جست‌وجو: ${result.revision}`; ctx.profileChanged(); }, $("search-save"), true);
  });
  async function load() {
    const job = ctx.session.job, org = ctx.session.organization;
    if (!job || !org) return;
    const base = jobPath(org.id, job.id);
    const missing = code => error => { if (error.code === code) return null; throw error; };
    return ctx.perform("profiles", signal => Promise.all([
      ctx.api.request(`${base}/match-profile`, { signal }).catch(missing("JOB_MATCH_PROFILE_NOT_FOUND")),
      ctx.api.request(`${base}/search-profile`, { signal }).catch(missing("JOB_SEARCH_PROFILE_NOT_FOUND")),
    ]), ([match, search]) => {
      if ((match && match.job_id !== job.id) || (search && search.job_id !== job.id)) throw new Error("INVALID_SCOPE");
      rows = []; $("criteria-list").replaceChildren();
      for (const item of match?.criteria ?? []) addRow(item);
      if (!rows.length) addRow();
      $("match-revision").textContent = match ? `نسخهٔ معیارها: ${match.revision}` : "معیارها هنوز ذخیره نشده‌اند";
      $("search-revision").textContent = search ? `نسخهٔ جست‌وجو: ${search.revision}` : "جست‌وجو هنوز ذخیره نشده است";
      $("search-query").value = search?.q ?? "";
      ctx.profilesReady = true; ctx.sync();
    });
  }
  function reset() {
    ctx.profilesReady = false; rows = []; nextKey = 1;
    $("criteria-list").replaceChildren();
    $("search-query").value = "";
    $("match-revision").textContent = $("search-revision").textContent = "یک شغل انتخاب کنید";
    $("profiles-fields").disabled = true;
  }
  return { load, reset };
}
