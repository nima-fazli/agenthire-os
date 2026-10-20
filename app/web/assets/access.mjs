import { $, node, button, field, empty, notice } from "./dom.mjs";
import { orgPath, uuid } from "./session.mjs";
import { ApiError } from "./api.mjs";
import { mutationNotice } from "./paging.mjs";

const labels = Object.freeze({ owner: "Owner", recruiter: "Recruiter", viewer: "Viewer" });
const actions = Object.freeze({
  invitation_created: "Invitation created", invitation_revoked: "Invitation revoked",
  invitation_accepted: "Invitation accepted", role_changed: "Role changed", member_removed: "Member removed",
});

export function createAccess(ctx, expired) {
  let role = null, offset = 0, more = false, timer = null;
  const ownerPassword = () => take("access-password");
  function take(id) {
    const input = $(id), value = input.value;
    input.value = "";
    if (!value) notice("Enter your current password to confirm this action.", true);
    return value;
  }

  async function manage(path, method, data, message) {
    const org = ctx.session.organization, password = ownerPassword();
    if (!org || role !== "owner" || !password) return;
    const accepted = await ctx.confirm.ask({ title: "Confirm access change", message });
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
      if (owned()) mutationNotice("Access updated", refreshed);
    }, $("access-owner-fields"), true);
  }

  function render(value) {
    role = value.role; more = value.has_more;
    if (role !== "owner") $("access-password").value = $("invitation-secret").value = "";
    $("access-role").textContent = "Your role: " + labels[role];
    $("access-owner").hidden = role !== "owner";
    $("access-page-info").textContent = role === "owner"
      ? "Members " + (offset + 1) + " to " + (offset + value.members.length) + "; up to 20 members per page"
      : "You can read the organization records available to your role.";
    const members = document.createDocumentFragment();
    for (const item of value.members) {
      uuid(item.id); uuid(item.user_id);
      if (!Object.hasOwn(labels, item.role)) throw new ApiError(502, "INVALID_RESPONSE");
      const card = node("article", "", "result-card");
      const name = node("h3", item.email); name.dir = "auto";
      card.append(name, node("p", labels[item.role] + (item.is_active ? "" : " · Inactive account"), "small muted"));
      const choice = field("New role", { value: item.role, options: Object.entries(labels) });
      const save = button("Change role", () => manage(
        orgPath(ctx.session.organization.id) + "/access/members/" + item.id, "PUT",
        { role: choice.input.value, expected_role: item.role },
        item.email + ": " + labels[item.role] + " ← " + labels[choice.input.value],
      ));
      save.disabled = true;
      choice.input.addEventListener("change", () => { save.disabled = choice.input.value === item.role; });
      const remove = button("Remove member", () => manage(
        orgPath(ctx.session.organization.id) + "/access/members/" + item.id, "DELETE",
        { expected_role: item.role }, "Access for " + item.email + " to this organization will be removed.",
      ), "button danger");
      card.append(choice.wrapper, save, remove); members.append(card);
    }
    $("access-members").replaceChildren(members);
    const invites = document.createDocumentFragment();
    for (const item of value.invitations) {
      uuid(item.id);
      const card = node("article", "", "result-card");
      card.append(node("p", item.email + " · " + labels[item.role]),
        node("p", "Expires: " + new Date(item.expires_at).toLocaleString("en-US"), "small muted"),
        button("Revoke invitation", () => manage(
          orgPath(ctx.session.organization.id) + "/access/invitations/" + item.id, "DELETE", {},
          "Invitation for " + item.email + " will be revoked.",
        ), "button danger"));
      invites.append(card);
    }
    $("access-invitations").replaceChildren(invites);
    const events = document.createDocumentFragment();
    for (const item of value.events) {
      if (!Object.hasOwn(actions, item.action)) throw new ApiError(502, "INVALID_RESPONSE");
      events.append(node("p", new Date(item.created_at).toLocaleString("en-US") + " · " + actions[item.action]
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
        notice("Organization access has ended. Refresh the organization list.", true);
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
    if (!await ctx.confirm.ask({ title: "Confirm invitation", message: email + " · " + labels[invitationRole] })) return;
    if (ctx.session.organization?.id !== org.id) return;
    await ctx.perform("access-write", signal => ctx.api.request(orgPath(org.id) + "/access/invitations", {
      method: "POST", signal, data: { email, role: invitationRole, current_password: password },
    }), async (result, owned) => {
      if (result.organization_id !== org.id || !/^[A-Za-z0-9_-]{43}$/.test(result.token))
        throw new ApiError(502, "INVALID_RESPONSE");
      $("invitation-secret").value = result.token;
      $("invitation-email").value = "";
      const refreshed = await load();
      if (owned()) mutationNotice("Invitation created; share the code only with the recipient", refreshed);
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
      if (owned()) mutationNotice("Invitation accepted; the organization is now available in your list", refreshed);
    }, $("invitation-accept-fields"), true);
  });

  async function sessionMutation(path, method, message) {
    const password = take("account-password");
    if (!password) return;
    if (!await ctx.confirm.ask({ title: "Confirm session revocation", message })) return;
    await ctx.perform("account-write", signal => ctx.api.request(path, {
      method, signal, data: { current_password: password },
    }), async (_value, owned) => {
      const refreshed = await loadSessions();
      if (owned()) mutationNotice("Selected sessions revoked", refreshed);
    }, $("account-fields"), true);
  }
  async function loadSessions() {
    empty($("sessions-list"), "Loading sessions…");
    return ctx.perform("account-read", signal => ctx.api.request("/auth/sessions", { signal }), rows => {
      if (!Array.isArray(rows) || rows.length > 10) throw new ApiError(502, "INVALID_RESPONSE");
      const content = document.createDocumentFragment();
      for (const item of rows) {
        uuid(item.id);
        if (typeof item.current !== "boolean" || !Number.isFinite(Date.parse(item.expires_at)))
          throw new ApiError(502, "INVALID_RESPONSE");
        const card = node("article", "", "result-card");
        card.append(node("h3", item.current ? "Current session" : "Other session"),
          node("p", "Started: " + new Date(item.created_at).toLocaleString("en-US")
            + " · Expires: " + new Date(item.expires_at).toLocaleString("en-US"), "small muted"));
        if (!item.current) card.append(button("Revoke session", () => sessionMutation(
          "/auth/sessions/" + item.id, "DELETE", "The selected session will be revoked.",
        ), "button danger"));
        content.append(card);
      }
      $("sessions-list").replaceChildren(content);
    }, $("sessions-refresh"));
  }
  $("sessions-refresh").addEventListener("click", loadSessions);
  $("sessions-revoke-others").addEventListener("click", () => sessionMutation(
    "/auth/sessions/revoke-others", "POST", "All sessions except this one will be revoked.",
  ));
  $("password-form").addEventListener("submit", async event => {
    event.preventDefault();
    const current = take("account-password"), next = $("account-new-password").value;
    const confirmation = $("account-confirm-password").value;
    $("account-new-password").value = $("account-confirm-password").value = "";
    if (!current) return;
    if (next !== confirmation) { notice("The new passwords do not match.", true); return; }
    if (!await ctx.confirm.ask({ title: "Confirm password change", message: "Your password will change and all sessions, including this one, will be revoked." })) return;
    await ctx.perform("account-write", signal => ctx.api.request("/auth/password", {
      method: "PUT", signal, data: { current_password: current, new_password: next },
    }), () => expired("Password changed. Sign in with your new password."), $("account-fields"), true);
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
      $("access-role").textContent = "Select an organization first.";
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
      $("session-expiry").textContent = "Session expires: " + new Date(expires).toLocaleString("en-US");
      const check = () => {
        if (Date.now() >= expires) expired("Your session has expired. Sign in again.");
        else timer = setTimeout(check, Math.min(60000, expires - Date.now()));
      };
      timer = setTimeout(check, Math.min(60000, expires - Date.now()));
    },
  };
}
