export function $(id) {
  const value = document.getElementById(id);
  if (!value) throw new Error("UI_ELEMENT_MISSING");
  return value;
}

export function node(tag, text = "", className = "") {
  const value = document.createElement(tag);
  value.textContent = String(text ?? "");
  if (className) value.className = className;
  return value;
}

export function empty(target, text) {
  target.replaceChildren(node("p", text, "small muted"));
}

let notifications = null;

export function setupNotices(value) {
  notifications = value;
}

export function notice(text, error = false) {
  if (notifications) {
    notifications.show(text, error);
    return;
  }

  const target = $("notice");
  target.textContent = text;
  target.className = "notice" + (error ? " error" : "");
}

export function button(text, action, className = "button secondary") {
  const value = node("button", text, className);
  value.type = "button";
  value.addEventListener("click", action);
  return value;
}

export function badge(text) {
  return node("span", text, "badge");
}

export function details(title, content) {
  const value = node("details", "", "disclosure");
  value.append(node("summary", title), content);
  return value;
}

export function field(label, { value = "", required = false, max, options } = {}) {
  const wrapper = node("label", "", "field");
  wrapper.append(node("span", label));

  const input = node(options ? "select" : "input");

  if (options) {
    for (const [key, title] of options) {
      const option = node("option", title);
      option.value = key;
      input.append(option);
    }
  } else {
    input.type = "text";
  }

  input.value = value ?? "";
  input.required = required;
  input.dir = "auto";

  if (max) input.maxLength = max;

  wrapper.append(input);
  return { wrapper, input };
}

const idPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const hashPattern = /^[0-9a-f]{64}$/;
const sourceFields = [
  "document_id",
  "chunk_set_id",
  "chunk_position",
  "chunk_sha256",
  "source_text_sha256",
  "source_document_sha256",
];

export function sourceParts(hit, citation = null) {
  if (
    !hit ||
    typeof hit.text !== "string" ||
    !idPattern.test(hit.document_id) ||
    !idPattern.test(hit.chunk_set_id) ||
    !Number.isSafeInteger(hit.chunk_position) ||
    hit.chunk_position < 0 ||
    !Number.isSafeInteger(hit.start_offset) ||
    hit.start_offset < 0 ||
    sourceFields.slice(3).some(key => !hashPattern.test(hit[key] ?? ""))
  ) {
    throw new Error("INVALID_SOURCE");
  }

  const chars = Array.from(hit.text);

  if (
    !chars.length ||
    chars.length > 4000 ||
    (
      hit.end_offset !== undefined &&
      hit.end_offset !== hit.start_offset + chars.length
    )
  ) {
    throw new Error("INVALID_SOURCE");
  }

  if (!citation) return [hit.text, "", ""];

  const start = citation.start_offset - hit.start_offset;
  const end = citation.end_offset - hit.start_offset;

  if (
    sourceFields.some(key => hit[key] !== citation[key]) ||
    !Number.isSafeInteger(citation.start_offset) ||
    !Number.isSafeInteger(citation.end_offset) ||
    start < 0 ||
    end <= start ||
    end > chars.length ||
    end - start > 4000 ||
    typeof citation.quote !== "string" ||
    chars.slice(start, end).join("") !== citation.quote
  ) {
    throw new Error("INVALID_CITATION");
  }

  return [
    chars.slice(0, start).join(""),
    citation.quote,
    chars.slice(end).join(""),
  ];
}

export function sourceView(hit, citation = null) {
  const parts = sourceParts(hit, citation);
  const value = node("div");

  const title = node("p", hit.filename ?? "منبع رزومه", "small muted");
  title.dir = "auto";

  const text = node("p", "", "source-text");
  text.dir = "auto";
  text.append(document.createTextNode(parts[0]));

  if (parts[1]) text.append(node("mark", parts[1]));

  text.append(document.createTextNode(parts[2]));

  const meta = node(
    "pre",
    JSON.stringify(
      {
        document_id: hit.document_id,
        chunk_set_id: hit.chunk_set_id,
        chunk_position: hit.chunk_position,
        start_offset: hit.start_offset,
        end_offset: hit.end_offset ?? hit.start_offset + Array.from(hit.text).length,
        chunk_sha256: hit.chunk_sha256,
        source_text_sha256: hit.source_text_sha256,
        source_document_sha256: hit.source_document_sha256,
        ...(citation
          ? {
              quote_start: citation.start_offset,
              quote_end: citation.end_offset,
              quote_sha256: citation.quote_sha256,
            }
          : {}),
      },
      null,
      2,
    ),
    "provenance",
  );

  meta.dir = "ltr";

  value.append(
    title,
    text,
    details("مشخصات منبع و محدودهٔ متن", meta),
  );

  return value;
}
