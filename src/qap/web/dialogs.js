// Small UI pieces: a toast, a context menu, a form dialog, the icon picker and the "move to" list.
import { glyph, iconNames, colorOf, PALETTE, defaultIcon } from "./icons.js";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

// ---- toast: one line at the bottom, with an optional action (Undo) ----
let toastTimer = 0;
export function toast(message, { error = false, action = null, ms = 5000 } = {}) {
  const box = document.getElementById("toast");
  box.replaceChildren(el("span", { text: message }));
  if (action) box.append(el("button", { type: "button", text: action.label, onclick: () => { hide(); action.run(); } }));
  box.classList.toggle("err", error);
  box.classList.add("show");
  clearTimeout(toastTimer);
  const hide = () => box.classList.remove("show");
  toastTimer = setTimeout(hide, ms);
}

// ---- a context menu next to an element (or at the pointer) ----
let openMenu = null;
export function closeMenu() {
  if (!openMenu) return;
  openMenu.anchor?.setAttribute("aria-expanded", "false");
  openMenu.node.remove();
  openMenu = null;
}
export function menu(anchor, items, point = null) {
  closeMenu();
  const node = el("div", { class: "menu", role: "menu" });
  for (const item of items) {
    if (item === "-") { node.append(el("hr")); continue; }
    node.append(el("button", { type: "button", role: "menuitem", text: item.label,
      onclick: () => { closeMenu(); item.run(); } }));
  }
  document.body.append(node);
  const r = point ? { left: point.x, bottom: point.y, top: point.y } : anchor.getBoundingClientRect();
  const w = node.offsetWidth, h = node.offsetHeight;
  node.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
  node.style.top = (r.bottom + h + 8 < innerHeight ? r.bottom + 4 : Math.max(8, r.top - h - 4)) + "px";
  anchor?.setAttribute("aria-expanded", "true");
  openMenu = { node, anchor };
  node.querySelector("button")?.focus();
}
document.addEventListener("pointerdown", (e) => { if (openMenu && !openMenu.node.contains(e.target)) closeMenu(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

// ---- a modal dialog holding a form; resolves with the form's result, or null when cancelled ----
export function dialog(title, build, submitLabel = "Save") {
  return new Promise((resolve) => {
    const err = el("p", { class: "err" });
    const body = el("div");
    const getResult = build(body);
    const form = el("form", { method: "dialog" },
      el("h2", { text: title }), body, err,
      el("div", { class: "row" },
        el("button", { class: "btn", type: "button", text: "Cancel", onclick: () => finish(null) }),
        submitLabel ? el("button", { class: "btn primary", type: "submit", text: submitLabel }) : null));
    const dlg = el("dialog", { class: "dlg" }, form);
    const finish = (value) => { dlg.close(); dlg.remove(); resolve(value); };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const value = await getResult();
        if (value !== undefined) finish(value);
      } catch (x) { err.textContent = x.message; }
    });
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
    body.addEventListener("qap:done", (e) => finish(e.detail));
    document.body.append(dlg);
    dlg.showModal();
    dlg.querySelector("input")?.focus();
  });
}

// ---- the icon picker: a preview tile, the built-in icons, an emoji field and the colours ----
export function iconPicker(node, state) {
  const preview = el("div", { class: "preview" });
  const grid = el("div", { class: "icons" });
  const emoji = el("input", { type: "text", placeholder: "or type / paste an emoji", maxlength: "16",
    value: state.icon && !iconNames().includes(state.icon) ? state.icon : "" });
  const swatches = el("div", { class: "swatches" });
  const paint = () => {
    const tile = el("div", { class: "tile" + (state.kind === "folder" ? " is-folder" : "") },
      el("span", { class: "glyph" }, glyph(state.icon, defaultIcon(state))),
      el("span", { class: "label", text: state.title || "…" }));
    tile.style.background = colorOf(state);
    preview.replaceChildren(tile);
    grid.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.icon === state.icon)));
    swatches.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.color || "") === (state.color || ""))));
  };
  for (const name of iconNames()) {
    const b = el("button", { type: "button", title: name, "data-icon": name,
      onclick: () => { state.icon = name; emoji.value = ""; paint(); } }, glyph(name));
    b.style.background = colorOf({ icon: name });
    grid.append(b);
  }
  emoji.addEventListener("input", () => { state.icon = emoji.value.trim(); paint(); });
  swatches.append(el("button", { type: "button", class: "auto", title: "Automatic colour", "data-color": "",
    onclick: () => { state.color = ""; paint(); } }));
  for (const c of PALETTE) {
    const b = el("button", { type: "button", title: c, "data-color": c, onclick: () => { state.color = c; paint(); } });
    b.style.background = c;
    swatches.append(b);
  }
  node.append(el("div", { class: "picker" }, preview, el("label", { text: "Icon" }), grid, emoji,
    el("label", { text: "Colour" }), swatches));
  paint();
  return paint;
}

// ---- "Move to…": every folder of the tree; the item itself, its descendants and its parent are disabled ----
export function moveDialog(tree, item) {
  return dialog(`Move “${item.title}” to…`, (body) => {
    const list = el("div", { class: "folders-list" });
    const parent = item.path.includes("/") ? item.path.slice(0, item.path.lastIndexOf("/")) : "";
    const walk = (node, depth) => {
      if (node.kind !== "folder") return;
      const inside = node.path === item.path || node.path.startsWith(item.path + "/");
      const b = el("button", { type: "button", disabled: inside || node.path === parent,
        onclick: () => body.dispatchEvent(new CustomEvent("qap:done", { detail: node.path })) },
        glyph(node.path ? node.icon : "folder", "folder"), el("span", { text: node.path ? node.title : "QA passes (top level)" }));
      b.style.paddingLeft = 10 + depth * 18 + "px";
      list.append(b);
      if (!inside) node.children.forEach((c) => walk(c, depth + 1));
    };
    walk(tree, 0);
    body.append(list);
    return () => undefined;
  }, null);
}
