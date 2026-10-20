import { $, notice } from "./dom.mjs";
import { ApiError } from "./api.mjs";

export function validatePage(page, offset, limit = 20) {
  if (!page || !Array.isArray(page.items) || page.items.length > limit
      || !Number.isSafeInteger(page.total) || page.total < page.items.length
      || page.limit !== limit || page.offset !== offset)
    throw new ApiError(502, "INVALID_RESPONSE");
  return page;
}

export function createPager(ctx, { name, url, filters = () => ({}), render, clear }) {
  const key = `${name}-page`;
  let offset = 0, total = 0, busy = false, generation = 0;
  const previous = $(`${name}-previous`), next = $(`${name}-next`);
  const info = $(`${name}-page-info`);

  function controls() {
    previous.disabled = busy || offset === 0 || !url();
    next.disabled = busy || offset + 20 >= total || offset + 20 > 10000 || !url();
  }

  async function load({ reset = false, preferred = null } = {}) {
    const base = url();
    if (!base) return null;
    if (reset) offset = 0;
    const current = ++generation, query = filters();
    let requested = offset, following = true;
    total = 0;
    busy = true;
    controls();
    clear("Loading…");
    info.textContent = "Loading from the server…";
    const path = value => `${base}?${new URLSearchParams({
      ...Object.fromEntries(Object.entries(query).filter(([, item]) => item !== "" && item != null)),
      limit: 20, offset: value,
    })}`;
    try {
      const result = await ctx.perform(key, async signal => {
        let page = validatePage(await ctx.api.request(path(requested), { signal }), requested);
        if (requested > 0 && requested >= page.total) {
          requested = page.total ? Math.floor((page.total - 1) / 20) * 20 : 0;
          page = validatePage(await ctx.api.request(path(requested), { signal }), requested);
        }
        return page;
      }, async page => {
        if (current !== generation) return;
        offset = requested;
        total = page.total;
        following = await render(page, preferred);
        if (current !== generation) return;
        info.textContent = total
          ? `${offset + 1} to ${Math.min(offset + page.items.length, total)} of ${total} results`
          : "No results found.";
        if (offset + 20 > 10000 && offset + 20 < total)
          info.textContent += "; narrow your search to continue.";
      });
      if (current === generation && result === false) {
        clear("Loading did not complete. Run the search again.");
        info.textContent = "Loading failed";
      }
      return result === true && following === false ? false : result;
    } finally {
      if (current === generation) { busy = false; controls(); }
    }
  }

  $(`${name}-search-form`).addEventListener("submit", event => {
    event.preventDefault();
    load({ reset: true });
  });
  previous.addEventListener("click", () => { if (!previous.disabled) { offset = Math.max(0, offset - 20); load(); } });
  next.addEventListener("click", () => { if (!next.disabled) { offset += 20; load(); } });

  return {
    load,
    reset() {
      generation++;
      ctx.cancel(key);
      busy = false;
      offset = total = 0;
      $(`${name}-filter`).value = "";
      info.textContent = "";
      clear("Select the relevant workspace scope to get started.");
      controls();
    },
  };
}

export function mutationNotice(label, refreshed) {
  notice(refreshed === false ? `${label}; the list could not be refreshed. Refresh it manually.` : `${label}.`, refreshed === false);
}
