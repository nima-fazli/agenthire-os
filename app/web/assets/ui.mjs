// Presentation helpers. Portraits are used only by the explicitly synthetic fixture.
import { node } from "./dom.mjs";

const portraits = Object.freeze({
  alex: "/workspace/assets/avatar-alex.webp",
  priya: "/workspace/assets/avatar-priya.webp",
  daniel: "/workspace/assets/avatar-daniel.webp",
  maria: "/workspace/assets/avatar-maria.webp",
  james: "/workspace/assets/avatar-james.webp",
  fatima: "/workspace/assets/avatar-fatima.webp",
});

export function icon(name) {
  const value = node("span", "", `icon icon-${name}`);
  value.ariaHidden = "true";
  return value;
}

export function avatar(item, large = false) {
  const name = String(item.full_name ?? "").trim();
  const initials = name.split(/\s+/u).slice(0, 2).map(part => Array.from(part)[0] ?? "").join("").toUpperCase();
  const value = node("span", initials, `avatar${large ? " avatar-large" : ""}`);
  value.ariaHidden = "true";
  const key = item.synthetic_portrait;
  if (typeof key === "string" && Object.hasOwn(portraits, key)) {
    const image = node("img");
    image.src = portraits[key];
    image.alt = "";
    image.width = image.height = large ? 72 : 40;
    image.decoding = "async";
    value.replaceChildren(image);
  }
  return value;
}

export function applicationStatus(value, label) {
  const badge = node("span", label, `badge status-${value}`);
  return badge;
}
