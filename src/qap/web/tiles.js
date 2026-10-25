// The folder view: one tile per folder and per subject, drag and drop onto folders, a ⋯ menu on each tile.
import { api, contentUrl } from "./api.js";
import { glyph, colorOf, defaultIcon } from "./icons.js";
import { el, menu, dialog, iconPicker, moveDialog, toast } from "./dialogs.js";

const DRAG_TYPE = "application/x-qap-path";

export function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

export const href = (path, params = "") => "#/" + path + (params ? "?" + params : "");

function parentOf(path) { return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ""; }

function tile(node, ctx) {
  const isFolder = node.kind === "folder";
  const wrap = el("div", { class: "tile-wrap" + (isFolder ? " is-folder" : ""), "data-path": node.path, "data-kind": node.kind });
  wrap.style.setProperty("--tile-bg", colorOf(node));
  const link = el("a", { class: "tile" + (isFolder ? " is-folder" : ""), href: href(node.path), draggable: "true",
    title: node.title + (isFolder ? "" : node.qa_project ? `  ·  qa-project ${node.qa_project}` : "") },
    el("span", { class: "glyph" }, glyph(node.icon, defaultIcon(node))),
    el("span", { class: "label", text: node.title.replace(/-/g, "\u2011") }), // no line break at a hyphen
    isFolder ? null : el("span", { class: "badge", title: `${node.count} passes`, text: String(node.count) }));
  const under = el("div", { class: "under" });
  if (isFolder) {
    const kids = node.children.slice(0, 6).map((c) => c.icon && !/^[\x00-\x7F]*$/.test(c.icon) ? c.icon : "").join("");
    under.append(`${node.subjects} subject${node.subjects === 1 ? "" : "s"}`);
    if (kids) under.append(el("span", { class: "kids", text: kids }));
  } else {
    under.textContent = `${node.count} pass${node.count === 1 ? "" : "es"} · ${shortDate(node.updated)}`;
  }
  const more = el("button", { class: "more", type: "button", "aria-label": `Actions for ${node.title}`,
    "aria-haspopup": "menu", "aria-expanded": "false", text: "⋯" });
  more.addEventListener("click", (e) => { e.preventDefault(); menu(more, actions(node, ctx)); });
  wrap.addEventListener("contextmenu", (e) => { e.preventDefault(); menu(more, actions(node, ctx), { x: e.clientX, y: e.clientY }); });
  wrap.append(link, under, more);
  dragSource(link, wrap, node);
  if (isFolder) dropTarget(wrap, node.path, ctx);
  return wrap;
}

function actions(node, ctx) {
  const list = [{ label: node.kind === "folder" ? "Open" : "Open latest pass", run: () => { location.hash = href(node.path); } }];
  if (node.kind === "subject" && node.passes.length) {
    const last = node.passes[node.passes.length - 1];
    list.push({ label: "Open latest pass in a new tab", run: () => window.open(contentUrl(node.path, last.file), "_blank") });
  }
  list.push("-",
    { label: "Rename…", run: () => renameItem(node, ctx) },
    { label: "Icon and colour…", run: () => editIcon(node, ctx) },
    { label: "Move to…", run: () => moveItem(node, ctx) });
  if (node.kind === "folder") list.push({ label: "New folder inside…", run: () => newFolder(node.path, ctx) });
  if (node.kind === "folder" && !node.children.length) list.push("-", { label: "Delete this empty folder", run: () => removeFolder(node, ctx) });
  return list;
}

// ---- drag and drop: a tile onto a folder tile, or onto a breadcrumb (to move it up) ----
function dragSource(link, wrap, node) {
  link.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData(DRAG_TYPE, node.path);
    e.dataTransfer.setData("text/plain", node.title);
    e.dataTransfer.effectAllowed = "move";
    wrap.classList.add("dragging");
  });
  link.addEventListener("dragend", () => wrap.classList.remove("dragging"));
}

let dragged = "";
document.addEventListener("dragstart", (e) => { dragged = e.target.closest?.(".tile-wrap")?.dataset.path || ""; });
document.addEventListener("dragend", () => { dragged = ""; });

export function dropTarget(node, destPath, ctx) {
  const ok = () => dragged && dragged !== destPath && !destPath.startsWith(dragged + "/") && parentOf(dragged) !== destPath;
  node.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes(DRAG_TYPE) || !ok()) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    node.setAttribute("data-drop-ok", "");
  });
  node.addEventListener("dragleave", (e) => { if (!node.contains(e.relatedTarget)) node.removeAttribute("data-drop-ok"); });
  node.addEventListener("drop", (e) => {
    node.removeAttribute("data-drop-ok");
    const src = e.dataTransfer.getData(DRAG_TYPE);
    if (!src) return;
    e.preventDefault();
    doMove(src, destPath, ctx);
  });
}

// ---- the operations (each one a call to the server, then a fresh tree) ----
async function doMove(src, dest, ctx) {
  const from = parentOf(src);
  try {
    const res = await api.mv(src, dest);
    await ctx.refresh();
    const where = dest ? ctx.find(dest)?.title || dest : "the top level";
    toast(`Moved to ${where}` + (res.relinked.length ? ` · ${res.relinked.length} old link(s) re-pointed` : ""), {
      action: { label: "Undo", run: async () => {
        try { await api.mv(res.path, from); await ctx.refresh(); toast("Moved back"); }
        catch (x) { toast(x.message, { error: true }); }
      } },
    });
  } catch (x) { toast(x.message, { error: true }); }
}

async function moveItem(node, ctx) {
  const dest = await moveDialog(ctx.tree(), node);
  if (dest !== null && dest !== undefined) doMove(node.path, dest, ctx);
}

async function removeFolder(node, ctx) {
  try { await api.rmdir(node.path); await ctx.refresh(); toast(`Deleted ${node.title}`); }
  catch (x) { toast(x.message, { error: true }); }
}

async function renameItem(node, ctx) {
  const title = await dialog("Rename", (body) => {
    const input = el("input", { type: "text", value: node.title, required: true });
    body.append(el("label", { text: "Title" }, input));
    return () => input.value.trim() || undefined;
  });
  if (!title || title === node.title) return;
  try { await api.rename(node.path, title); await ctx.refresh(); } catch (x) { toast(x.message, { error: true }); }
}

async function editIcon(node, ctx) {
  const state = { kind: node.kind, path: node.path, title: node.title, icon: node.icon, color: node.color };
  const done = await dialog("Icon and colour", (body) => { iconPicker(body, state); return () => state; });
  if (!done) return;
  try { await api.icon(node.path, state.icon || "", state.color || ""); await ctx.refresh(); }
  catch (x) { toast(x.message, { error: true }); }
}

export async function newFolder(parent, ctx) {
  const state = { kind: "folder", path: "", title: "", icon: "", color: "" };
  const result = await dialog("New folder", (body) => {
    const input = el("input", { type: "text", placeholder: "DB migration, Billing, …", required: true });
    let repaint = () => {};
    input.addEventListener("input", () => { state.title = input.value; state.path = input.value; repaint(); });
    body.append(el("label", { text: "Title" }, input));
    repaint = iconPicker(body, state);
    return async () => {
      if (!state.title.trim()) throw new Error("Give the folder a title");
      return api.mkdir(parent, state.title.trim(), state.icon || null, state.color || null);
    };
  }, "Create");
  if (!result) return;
  await ctx.refresh();
  toast(`Created ${state.title.trim()}`);
}

export function renderFolder(view, node, ctx) {
  const folders = node.children.filter((c) => c.kind === "folder");
  const subjects = node.children.filter((c) => c.kind === "subject");
  const head = el("div", { class: "folder-head" },
    el("h1", {}, node.path ? glyph(node.icon, "folder") : null, node.title),
    el("p", { class: "meta", text: `${node.subjects} subject${node.subjects === 1 ? "" : "s"}` +
      (node.updated ? ` · updated ${shortDate(node.updated)}` : "") }));
  const section = el("section", { class: "folder" }, head);
  const group = (title, items) => {
    if (!items.length) return;
    if (folders.length && subjects.length) section.append(el("h3", { class: "group", text: title }));
    section.append(el("div", { class: "tiles" }, items.map((c) => tile(c, ctx))));
  };
  group("Folders", folders);
  group("Subjects", subjects);
  if (!node.children.length) {
    section.append(el("p", { class: "empty", text: node.path
      ? "An empty folder. Drag a tile onto this folder's tile or its name in the bar, or use a tile's ⋯ → Move to…"
      : "No QA pass yet. `qap new-subject` creates one, `qap place` moves passes in." }));
  }
  view.replaceChildren(section);
}
