import { $, clear, el, reportView } from "./agent-ui.mjs";
let recording,
  step = 0;
function render() {
  clear($("demo-events"));
  clear($("demo-report"));
  $("demo-progress").textContent =
    `${step} of ${recording.events.length} tool steps shown`;
  $("demo-next").disabled = step === recording.events.length;
  for (const event of recording.events.slice(0, step)) {
    const details = el("details", undefined, "agent-trace");
    details.append(
      el("summary", event.tool),
      el("pre", JSON.stringify(event, null, 2)),
    );
    $("demo-events").append(details);
  }
  if (step === recording.events.length) {
    $("demo-report").append(
      el("h3", "Review awaiting human approval"),
      reportView(recording.report),
    );
  }
}
$("demo-next").addEventListener("click", () => {
  if (recording && step < recording.events.length) {
    step++;
    render();
  }
});
$("demo-reset").addEventListener("click", () => {
  step = 0;
  if (recording) render();
});
try {
  const response = await fetch("/workspace/assets/demo-run.json", {
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!response.ok) throw new Error();
  recording = await response.json();
  $("demo-resume").textContent = recording.resume;
  render();
} catch {
  $("demo-progress").textContent =
    "The recorded demo could not be loaded. Refresh the page.";
}
