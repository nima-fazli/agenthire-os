import { $, node, button, field, empty, notice } from "./dom.mjs";
import { orgPath, uuid } from "./session.mjs";
import { ApiError } from "./api.mjs";
import { mutationNotice } from "./paging.mjs";

const labels = Object.freeze({ owner: "مالک", recruiter: "استخدام‌کننده", viewer: "فقط مشاهده" });
const actions = Object.freeze({
  invitation_created: "دعوت ساخته شد", invitation_revoked: "دعوت لغو شد",
  invitation_accepted: "دعوت پذیرفته شد", role_changed: "نقش تغییر کرد", member_removed: "عضو حذف شد",
});

export function createAccess(ctx, expired) {
  let role = null, offset = 0, more = false, timer = null;
  const ownerPassword = () => take("access-password");
  function take(id) {
    const input = $(id), value = input.value;
    input.value = "";
    if (!value) notice("برای تأیید این عملیات، رمز فعلی را وارد کنید.", true);
    return value;
  }

  async function manage(path, method, data, message) {
    const org = ctx.session.organization, password = ownerPassword();
    if (!org || role !== "owner" || !password) return;
    const accepted = await ctx.confirm.ask({ title: "تأیید تغییر دسترسی", message });
    if (!accepted || ctx.session.organization?.id !== org.id) return;
    await ctx.perform("access-write", signal => ctx.api.request(path, {
      method, signal, data: { ...data, current_password: password },
    }), async (result, owned) => {
      if (result?.removed_self) {
        await ctx.selectOrganization(null);
        await ctx.workspace.loadOrganizations();
        return;
      }
      const refreshed = await load();
      if (owned()) mutationNotice("تغییر دسترسی ثبت شد", refreshed);
    }, $("access-owner-fields"), true);
  }

  function render(value) {
    role = value.role; more = value.has_more;
    if (role !== "owner") $("access-password").value = $("invitation-secret").value = "";
    $("access-role").textContent = "نقش شما: " + labels[role];
    $("access-owner").hidden = role !== "owner";
    $("access-page-info").textContent = role === "owner"
      ? "اعضای " + (offset + 1) + " تا " + (offset + value.members.length) + "؛ هر صفحه حداکثر ۲۰ عضو"
      : "می‌توانید اطلاعات مجاز سازمان را بخوانید.";
    const members = document.createDocumentFragment();
    for (const item of value.members) {
      uuid(item.id); uuid(item.user_id);
      if (!Object.hasOwn(labels, item.role)) throw new ApiError(502, "INVALID_RESPONSE");
      const card = node("article", "", "result-card");
      const name = node("h3", item.email); name.dir = "auto";
      card.append(name, node("p", labels[item.role] + (item.is_active ? "" : " · حساب غیرفعال"), "small muted"));
      const choice = field("نقش جدید", { value: item.role, options: Object.entries(labels) });
      const save = button("تغییر نقش", () => manage(
        orgPath(ctx.session.organization.id) + "/access/members/" + item.id, "PUT",
        { role: choice.input.value, expected_role: item.role },
        item.email + ": " + labels[item.role] + " ← " + labels[choice.input.value],
      ));
      save.disabled = true;
      choice.input.addEventListener("change", () => { save.disabled = choice.input.value === item.role; });
      const remove = button("حذف عضو", () => manage(
        orgPath(ctx.session.organization.id) + "/access/members/" + item.id, "DELETE",
        { expected_role: item.role }, "دسترسی " + item.email + " به این سازمان حذف می‌شود.",
      ), "button danger");
      card.append(choice.wrapper, save, remove); members.append(card);
    }
    $("access-members").replaceChildren(members);
    const invites = document.createDocumentFragment();
    for (const item of value.invitations) {
      uuid(item.id);
      const card = node("article", "", "result-card");
      card.append(node("p", item.email + " · " + labels[item.role]),
        node("p", "انقضا: " + new Date(item.expires_at).toLocaleString("fa-IR"), "small muted"),
        button("لغو دعوت", () => manage(
          orgPath(ctx.session.organization.id) + "/access/invitations/" + item.id, "DELETE", {},
          "دعوت " + item.email + " لغو می‌شود.",
        ), "button danger"));
      invites.append(card);
    }
    $("access-invitations").replaceChildren(invites);
    const events = document.createDocumentFragment();
    for (const item of value.events) {
      if (!Object.hasOwn(actions, item.action)) throw new ApiError(502, "INVALID_RESPONSE");
      events.append(node("p", new Date(item.created_at).toLocaleString("fa-IR") + " · " + actions[item.action]
        + " · " + item.subject_id, "small muted"));
    }
    $("access-events").replaceChildren(events);
  }

  async function load() {
    const org = ctx.session.organization;
    if (!org) return null;
    return ctx.perform("access-read", signal => ctx.api.request(
      orgPath(org.id) + "/access?offset=" + offset, { signal },
    ).catch(error => {
      if (error.code === "ORGANIZATION_NOT_FOUND") return null;
      throw error;
    }), async value => {
      if (value === null) {
        await ctx.selectOrganization(null);
        notice("دسترسی به سازمان پایان یافته است؛ فهرست سازمان‌ها را تازه‌سازی کنید.", true);
        return;
      }
      if (value.organization_id !== org.id || !Object.hasOwn(labels, value.role)
          || value.can_write !== (value.role !== "viewer") || value.can_manage !== (value.role === "owner")
          || !Array.isArray(value.members) || value.members.length > 20
          || !Array.isArray(value.invitations) || value.invitations.length > 20
          || !Array.isArray(value.events) || value.events.length > 20
          || value.offset !== offset || typeof value.has_more !== "boolean")
        throw new ApiError(502, "INVALID_RESPONSE");
      render(value);
    }, $("access-refresh"));
  }

  $("access-refresh").addEventListener("click", load);
  $("access-previous").addEventListener("click", () => { if (offset) { offset -= 20; load(); } });
  $("access-next").addEventListener("click", () => { if (more && offset < 10000) { offset += 20; load(); } });
  $("invitation-form").addEventListener("submit", async event => {
    event.preventDefault();
    const org = ctx.session.organization, password = ownerPassword();
    if (!org || role !== "owner" || !password) return;
    const email = $("invitation-email").value.trim(), invitationRole = $("invitation-role").value;
    if (!await ctx.confirm.ask({ title: "تأیید ساخت دعوت", message: email + " · " + labels[invitationRole] })) return;
    if (ctx.session.organization?.id !== org.id) return;
    await ctx.perform("access-write", signal => ctx.api.request(orgPath(org.id) + "/access/invitations", {
      method: "POST", signal, data: { email, role: invitationRole, current_password: password },
    }), async (result, owned) => {
      if (result.organization_id !== org.id || !/^[A-Za-z0-9_-]{43}$/.test(result.token))
        throw new ApiError(502, "INVALID_RESPONSE");
      $("invitation-secret").value = result.token;
      $("invitation-email").value = "";
      const refreshed = await load();
      if (owned()) mutationNotice("دعوت ساخته شد؛ کد را فقط برای صاحب همان ایمیل بفرستید", refreshed);
    }, $("access-owner-fields"), true);
  });

  $("invitation-accept-form").addEventListener("submit", async event => {
    event.preventDefault();
    const token = $("invitation-token").value.trim();
    $("invitation-token").value = "";
    await ctx.perform("invitation-accept", signal => ctx.api.request("/access/invitations/accept", {
      method: "POST", signal, data: { token },
    }), async (_result, owned) => {
      $("organization-filter").value = "";
      const refreshed = await ctx.workspace.loadOrganizations();
      if (owned()) mutationNotice("دعوت پذیرفته شد؛ سازمان در فهرست شما در دسترس است", refreshed);
    }, $("invitation-accept-fields"), true);
  });

  async function sessionMutation(path, method, message) {
    const password = take("account-password");
    if (!password) return;
    if (!await ctx.confirm.ask({ title: "تأیید ابطال نشست", message })) return;
    await ctx.perform("account-write", signal => ctx.api.request(path, {
      method, signal, data: { current_password: password },
    }), async (_value, owned) => {
      const refreshed = await loadSessions();
      if (owned()) mutationNotice("نشست‌های انتخاب‌شده باطل شدند", refreshed);
    }, $("account-fields"), true);
  }
  async function loadSessions() {
    empty($("sessions-list"), "در حال خواندن نشست‌ها…");
    return ctx.perform("account-read", signal => ctx.api.request("/auth/sessions", { signal }), rows => {
      if (!Array.isArray(rows) || rows.length > 10) throw new ApiError(502, "INVALID_RESPONSE");
      const content = document.createDocumentFragment();
      for (const item of rows) {
        uuid(item.id);
        if (typeof item.current !== "boolean" || !Number.isFinite(Date.parse(item.expires_at)))
          throw new ApiError(502, "INVALID_RESPONSE");
        const card = node("article", "", "result-card");
        card.append(node("h3", item.current ? "نشست همین صفحه" : "نشست دیگر"),
          node("p", "شروع: " + new Date(item.created_at).toLocaleString("fa-IR")
            + " · انقضا: " + new Date(item.expires_at).toLocaleString("fa-IR"), "small muted"));
        if (!item.current) card.append(button("باطل‌کردن نشست", () => sessionMutation(
          "/auth/sessions/" + item.id, "DELETE", "نشست انتخاب‌شده باطل می‌شود.",
        ), "button danger"));
        content.append(card);
      }
      $("sessions-list").replaceChildren(content);
    }, $("sessions-refresh"));
  }
  $("sessions-refresh").addEventListener("click", loadSessions);
  $("sessions-revoke-others").addEventListener("click", () => sessionMutation(
    "/auth/sessions/revoke-others", "POST", "همهٔ نشست‌ها به‌جز همین صفحه باطل می‌شوند.",
  ));
  $("password-form").addEventListener("submit", async event => {
    event.preventDefault();
    const current = take("account-password"), next = $("account-new-password").value;
    const confirmation = $("account-confirm-password").value;
    $("account-new-password").value = $("account-confirm-password").value = "";
    if (!current) return;
    if (next !== confirmation) { notice("تکرار رمز جدید با آن یکسان نیست.", true); return; }
    if (!await ctx.confirm.ask({ title: "تأیید تغییر رمز", message: "رمز تغییر می‌کند و همهٔ نشست‌ها، شامل همین صفحه، باطل می‌شوند." })) return;
    await ctx.perform("account-write", signal => ctx.api.request("/auth/password", {
      method: "PUT", signal, data: { current_password: current, new_password: next },
    }), () => expired("رمز تغییر کرد؛ با رمز جدید وارد شوید."), $("account-fields"), true);
  });

  return {
    get canWrite() { return role === "owner" || role === "recruiter"; },
    load,
    sync() {
      $("access-owner-fields").disabled = role !== "owner" || ctx.isPending("access-write") || ctx.isPending("access-read");
      $("access-refresh").disabled = !ctx.session.organization || ctx.isPending("access-read");
      $("access-previous").disabled = !offset || ctx.isPending("access-read");
      $("access-next").disabled = !more || offset >= 10000 || ctx.isPending("access-read");
      $("account-fields").disabled = !ctx.session.token || ctx.isPending("account-write");
      $("sessions-refresh").disabled = !ctx.session.token || ctx.isPending("account-read");
      $("invitation-accept-fields").disabled = !ctx.session.token || ctx.isPending("invitation-accept");
    },
    resetOrganization() {
      role = null; offset = 0; more = false;
      $("access-password").value = $("invitation-secret").value = $("invitation-email").value = "";
      $("access-role").textContent = "ابتدا سازمان را انتخاب کنید.";
      $("access-owner").hidden = true;
      for (const id of ["access-members", "access-invitations", "access-events"]) $(id).replaceChildren();
      $("access-page-info").textContent = "";
    },
    clearSession() {
      clearTimeout(timer); timer = null;
      for (const id of ["account-password", "account-new-password", "account-confirm-password", "invitation-token"]) $(id).value = "";
      $("sessions-list").replaceChildren();
      $("session-expiry").textContent = "";
    },
    startSession(result) {
      uuid(result.session_id);
      const expires = Date.parse(result.expires_at);
      if (!Number.isFinite(expires) || expires <= Date.now()) throw new ApiError(502, "INVALID_RESPONSE");
      clearTimeout(timer);
      $("session-expiry").textContent = "انقضای نشست: " + new Date(expires).toLocaleString("fa-IR");
      const check = () => {
        if (Date.now() >= expires) expired("نشست پایان یافته است؛ دوباره وارد شوید.");
        else timer = setTimeout(check, Math.min(60000, expires - Date.now()));
      };
      timer = setTimeout(check, Math.min(60000, expires - Date.now()));
    },
  };
}
