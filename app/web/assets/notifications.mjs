export function createNotifications({ region, status, alert, dismiss }, clock = globalThis) {
  let timer = null, persistent = false, hovered = false, focused = false;

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
    status.ariaLive = error ? "off" : "polite";
    status.textContent = String(text);
    status.className = "notice" + (error ? " error" : "");
    alert.textContent = error ? String(text) : "";
    region.className = "toast" + (error ? " toast-error" : "");
    region.hidden = false;

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

  return { show, clear };
}
