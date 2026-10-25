// Tile icons: the built-in set (icons.json, shared with the CLI) or any emoji, and the tile colour.

let builtin = {};

export async function loadIcons() {
  try { builtin = await (await fetch("/ui/icons.json")).json(); } catch (e) { builtin = {}; }
  return builtin;
}

export function iconNames() { return Object.keys(builtin); }

// The colours of the dotfiles map; an item with no colour of its own gets one from its path, so it keeps it.
export const PALETTE = ["#5E60CE", "#0F8B8D", "#F46D01", "#2F6FDB", "#8338EC", "#1E9E3A", "#D6304F",
  "#0B66C3", "#A8650C", "#7B2CBF", "#138FA3", "#C15F3C"];

function hash(text) {
  let h = 2166136261;
  for (const c of text) h = Math.imul(h ^ c.codePointAt(0), 16777619);
  return h >>> 0;
}

export function colorOf(node) {
  if (node.color) return node.color;
  if (builtin[node.icon]) return builtin[node.icon].color;
  return PALETTE[hash(node.path || node.title || "") % PALETTE.length];
}

export function defaultIcon(node) { return node.kind === "folder" ? "folder" : "doc"; }

// An element holding the icon: an inline SVG for a built-in name, the text itself for an emoji.
export function glyph(icon, fallback = "doc") {
  const span = document.createElement("span");
  span.className = "gl";
  const name = icon || fallback;
  if (builtin[name]) {
    span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${builtin[name].svg}</svg>`;
  } else if (!/^[\x00-\x7F]*$/.test(name)) {
    span.textContent = name; // an emoji
  }
  return span;
}
