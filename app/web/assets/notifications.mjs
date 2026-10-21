export function createNotifications({ region, status, alert, dismiss, title, symbol,
  history, count, toggle, markRead, clearHistoryButton }, clock = globalThis) {
  let timer = null, persistent = false, hovered = false, focused = false;
  let entries = [];

  function renderHistory() {
    if (!history) return;
    const doc = history.ownerDocument;
    const unread = entries.filter(entry => !entry.read).length;
    count.textContent = String(unread);
    count.hidden = unread === 0;
    toggle.setAttribute("aria-label", unread ? `Notifications, ${unread} unread` : "Notifications");
    markRead.disabled = unread === 0;
    clearHistoryButton.disabled = entries.length === 0;
    history.replaceChildren();
    if (!entries.length) {
      const empty = doc.createElement("p");
      empty.className = "notification-empty";
      empty.textContent = "You're all caught up.";
      const hint = doc.createElement("span");
      hint.textContent = "Updates from your work will appear here.";
      empty.append(hint);
      history.append(empty);
      return;
    }
    for (const entry of entries) {
      const row = doc.createElement("article");
      row.className = `notification-entry${entry.error ? " notification-entry-error" : ""}${entry.read ? " is-read" : ""}`;
      const icon = doc.createElement("span");
      icon.className = `icon icon-${entry.error ? "exclamation-circle" : "check-circle"}`;
      icon.ariaHidden = "true";
      const content = doc.createElement("div");
      const heading = doc.createElement("strong");
      heading.textContent = entry.error ? "Something needs attention" : "Workspace update";
      const text = doc.createElement("p");
      text.textContent = entry.text;
      const time = doc.createElement("time");
      time.dateTime = entry.time.toISOString();
      time.textContent = entry.time.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
      content.append(heading, text, time);
      row.append(icon, content);
      history.append(row);
    }
  }

  function resetHistory() {
    entries = [];
    renderHistory();
    clear();
  }

  function stop() {
    clock.clearTimeout(timer);
    timer = null;
  }

  function clear() {
    stop();
    hovered = focused = false;
    region.hidden = true;
    status.textContent = alert.textContent = "";
  }

  function schedule() {
    stop();
    if (!persistent && !hovered && !focused && !region.hidden) {
      timer = clock.setTimeout(clear, 8000);
    }
  }

  function show(text, error = false) {
    stop();

    if (!text) {
      clear();
      return;
    }

    persistent = error;
    if (title) title.textContent = error ? "Something needs attention" : "Workspace updated";
    if (symbol) symbol.className = `icon icon-${error ? "exclamation-circle" : "check-circle"} toast-icon`;
    status.ariaLive = error ? "off" : "polite";
    status.textContent = String(text);
    status.className = "notice" + (error ? " error" : "");
    alert.textContent = error ? String(text) : "";
    region.className = "toast" + (error ? " toast-error" : "");
    region.hidden = false;
    if (history) {
      entries.unshift({ text: String(text), error, read: false, time: new Date() });
      entries = entries.slice(0, 20);
      renderHistory();
    }

    schedule();
  }

  dismiss.addEventListener("click", clear);

  region.addEventListener("pointerenter", () => {
    hovered = true;
    stop();
  });

  region.addEventListener("pointerleave", () => {
    hovered = false;
    schedule();
  });

  region.addEventListener("focusin", () => {
    focused = true;
    stop();
  });

  region.addEventListener("focusout", event => {
    focused = region.contains(event.relatedTarget);
    schedule();
  });

  markRead?.addEventListener("click", () => {
    entries.forEach(entry => { entry.read = true; });
    renderHistory();
  });
  clearHistoryButton?.addEventListener("click", resetHistory);
  renderHistory();
  return { show, clear, resetHistory };
}
