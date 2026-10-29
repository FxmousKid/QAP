// The folder view: one tile per project, folder and subject, drag and drop onto folders and projects, a ⋯ menu on
// each tile. The home shows the projects (big boxes); a project shows its families (top-level folders).
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

function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + "s"}`; }

function tile(node, ctx) {
  const isFolder = node.kind === "folder";
  const isProject = node.kind === "project";
  const shape = isFolder ? " is-folder" : isProject ? " is-project" : "";
  const wrap = el("div", { class: "tile-wrap" + shape, "data-path": node.path, "data-kind": node.kind });
  wrap.style.setProperty("--tile-bg", colorOf(node));
  const link = el("a", { class: "tile" + shape, href: href(node.path), draggable: isProject ? "false" : "true",
    title: node.title + (node.kind === "subject" && node.qa_project ? `  ·  qa-project ${node.qa_project}` : "") },
    el("span", { class: "glyph" }, glyph(node.icon, defaultIcon(node))),
    el("span", { class: "label", text: node.title.replace(/-/g, "\u2011") }), // no line break at a hyphen
    node.kind === "subject" ? el("span", { class: "badge", title: `${node.count} passes`, text: String(node.count) }) : null);
  const under = el("div", { class: "under" });
  if (isProject) {
    // what it holds, as a row of small boxes in their own colours
    under.append(`${plural(node.families, "family", "families")} · ${plural(node.subjects, "subject")}`,
      el("span", { class: "minis" }, node.children.slice(0, 7).map((c) => {
        const mini = el("span", { class: "mini" + (c.kind === "folder" ? " is-folder" : ""), title: c.title },
          glyph(c.icon, defaultIcon(c)));
        mini.style.background = colorOf(c);
        return mini;
      })));
  } else if (isFolder) {
    const kids = node.children.slice(0, 6).map((c) => c.icon && !/^[\x00-\x7F]*$/.test(c.icon) ? c.icon : "").join("");
    under.append(plural(node.subjects, "subject"));
    if (kids) under.append(el("span", { class: "kids", text: kids }));
  } else {
    under.textContent = `${node.count} pass${node.count === 1 ? "" : "es"} · ${shortDate(node.updated)}`;
  }
  const more = el("button", { class: "more", type: "button", "aria-label": `Actions for ${node.title}`,
    "aria-haspopup": "menu", "aria-expanded": "false", text: "⋯" });
  more.addEventListener("click", (e) => { e.preventDefault(); menu(more, actions(node, ctx)); });
  wrap.addEventListener("contextmenu", (e) => { e.preventDefault(); menu(more, actions(node, ctx), { x: e.clientX, y: e.clientY }); });
  wrap.append(link, under, more);
  if (!isProject) dragSource(link, wrap, node);
  if (isFolder || isProject) dropTarget(wrap, node.path, ctx);
  return wrap;
}

function actions(node, ctx) {
  const open = { label: node.kind === "subject" ? "Open latest pass" : "Open", run: () => { location.hash = href(node.path); } };
  if (node.kind === "project") {
    return [open, "-",
      { label: "Rename…", run: () => renameItem(node, ctx) },
      { label: "Icon and colour…", run: () => editIcon(node, ctx) },
      { label: "New family inside…", run: () => newFolder(node.path, ctx) },
      ...(node.children.length ? [] : ["-", { label: "Delete this empty project", run: () => removeFolder(node, ctx) }])];
  }
  const list = [open];
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

// ---- drag and drop: a tile onto a folder or project tile, or onto a breadcrumb (to move it up) ----
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
  const ok = () => {
    if (!dragged || dragged === destPath) return false;
    if (destPath.startsWith("@")) { // a project: anything but one of its own top-level items
      const item = ctx.find(dragged);
      return !(item && !dragged.includes("/") && item.project === destPath.slice(1));
    }
    return !destPath.startsWith(dragged + "/") && parentOf(dragged) !== destPath;
  };
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
  // Undo goes back where it came from: its folder, or its project for a top-level item.
  const item = ctx.find(src);
  const from = !src.includes("/") && item?.project ? "@" + item.project : parentOf(src);
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
  const dest = await moveDialog(ctx.tree(), node, ctx.projects());
  if (dest !== null && dest !== undefined) doMove(node.path, dest, ctx);
}

async function removeFolder(node, ctx) { // a project too: rmdir("@id")
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
  const state = { kind: node.kind, path: node.path, name: node.name, title: node.title, icon: node.icon, color: node.color };
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

export async function newProject(ctx) {
  const first = !ctx.projects().length;
  const state = { kind: "project", path: "", name: "", title: "", icon: "", color: "" };
  const result = await dialog("New project", (body) => {
    const input = el("input", { type: "text", placeholder: "Work, Personal, …", required: true });
    let repaint = () => {};
    input.addEventListener("input", () => {
      state.title = input.value;
      state.name = input.value.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "");
      repaint();
    });
    body.append(el("label", { text: "Title" }, input));
    if (first) body.append(el("p", { class: "hint", text: "The first project holds every folder there is now. " +
      "Create the next one, then drag a family's tile onto it." }));
    repaint = iconPicker(body, state);
    return async () => {
      if (!state.title.trim()) throw new Error("Give the project a title");
      return api.project(state.title.trim(), state.icon || null, state.color || null);
    };
  }, "Create");
  if (!result) return;
  await ctx.refresh();
  toast(first ? `Created ${state.title.trim()}: every family is in it for now` : `Created ${state.title.trim()}`);
}

// Flex stretch only matches tiles in one row. A subject on the next row would stay short, so the
// whole group takes the height of the longest wrapped title. Short titles stay centred in that box.
function fitSubjectTiles(root = document) {
  for (const group of root.querySelectorAll(".tiles.subjects")) {
    const tiles = [...group.querySelectorAll(":scope > .tile-wrap > a.tile")];
    if (!tiles.length) continue;
    for (const box of tiles) box.style.height = "";
    const height = Math.ceil(Math.max(...tiles.map((box) => box.getBoundingClientRect().height)));
    for (const box of tiles) box.style.height = height + "px";
  }
}

let fitQueued = false;
function queueFitSubjectTiles() {
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitSubjectTiles(); });
}
window.addEventListener("resize", queueFitSubjectTiles);

export function renderFolder(view, node, ctx) {
  const isProject = node.kind === "project";
  const projects = node.path ? [] : ctx.projects();
  // At the top, with projects, only what belongs to no project shows next to them (nothing, when there is a default).
  const loose = projects.length ? node.children.filter((c) => !c.project) : node.children;
  const folders = loose.filter((c) => c.kind === "folder");
  const subjects = loose.filter((c) => c.kind === "subject");
  const families = !node.path || isProject; // the top-level folders are the families
  const counts = isProject ? `${plural(node.families, "family", "families")} · ${plural(node.subjects, "subject")}`
    : projects.length ? `${plural(projects.length, "project")} · ${plural(node.subjects, "subject")}`
    : plural(node.subjects, "subject");
  const head = el("div", { class: "folder-head" },
    el("h1", {}, node.path ? glyph(node.icon, defaultIcon(node)) : null, node.title),
    el("p", { class: "meta", text: counts + (node.updated ? ` · updated ${shortDate(node.updated)}` : "") }));
  const section = el("section", { class: "folder" + (projects.length ? " home" : "") }, head);
  const groups = [["Projects", projects], [families ? "Families" : "Folders", folders], ["Subjects", subjects]]
    .filter(([, items]) => items.length);
  for (const [title, items] of groups) {
    if (groups.length > 1) section.append(el("h3", { class: "group", text: title }));
    const kind = title === "Projects" ? " projects" : title === "Subjects" ? " subjects" : "";
    section.append(el("div", { class: "tiles" + kind }, items.map((c) => tile(c, ctx))));
  }
  if (!groups.length) {
    section.append(el("p", { class: "empty", text: isProject
      ? "An empty project. Drag a family's tile onto this project's name in the bar, or create one with + New folder."
      : node.path
        ? "An empty folder. Drag a tile onto this folder's tile or its name in the bar, or use a tile's ⋯ → Move to…"
        : "No QA pass yet. `qap new-subject` creates one, `qap place` moves passes in." }));
  }
  view.replaceChildren(section);
  queueFitSubjectTiles();
}
