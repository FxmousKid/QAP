// QA passes dashboard: a hash router over the content tree.
//   #/                       the top level: the projects (a tree without projects: its top-level tiles)
//   #/@work                  a project: its families (top-level folders) and top-level subjects
//   #/authz                  a folder (tiles)
//   #/authz/rbac             a subject: its latest pass in the frame
//   #/authz/rbac?pass=3      a given pass;  &at=p3-1a  opens the page at that message
// Search (top right, left of ‹ on a subject): ⌘K or Ctrl+K anywhere, the framed pass included; / too, except on a
// subject, where / opens the pass list.
import { api } from "./api.js";
import { loadIcons, glyph, defaultIcon } from "./icons.js";
import { el, toast, closeMenu } from "./dialogs.js";
import { renderFolder, dropTarget, newFolder, newProject, href } from "./tiles.js";
import { renderViewer, leaveViewer, frameTheme } from "./viewer.js";
import { searchButton, openSearch, isShortcut, isOpen, invalidate, SHORTCUT } from "./search.js";

const view = document.getElementById("view");
const crumbs = document.getElementById("crumbs");
const tools = document.getElementById("tools");
const themeButton = document.getElementById("theme");

let tree = null;
let projects = []; // project nodes; children: their top-level folders and subjects
let index = new Map(); // path ("@id" for a project) -> node
let lastLoad = 0;

const ctx = {
  tree: () => tree,
  projects: () => projects,
  find: (path) => index.get(path),
  refresh: async () => { invalidate(); await load(); render(); },
};

async function load() {
  const data = await api.tree();
  tree = data.tree;
  index = new Map();
  const walk = (n) => { index.set(n.path, n); (n.children || []).forEach(walk); };
  walk(tree);
  projects = (tree.projects || []).map((p) => ({ ...p, children: tree.children.filter((c) => c.project === p.id) }));
  projects.forEach((p) => index.set(p.path, p));
  lastLoad = Date.now();
}

function route() {
  const raw = location.hash.replace(/^#\/?/, "");
  const q = raw.indexOf("?");
  const path = decodeURIComponent(q < 0 ? raw : raw.slice(0, q)).replace(/^\/+|\/+$/g, "");
  return { path, params: new URLSearchParams(q < 0 ? "" : raw.slice(q + 1)) };
}

// Project / folders / here. A crumb takes drops: a tile dropped on it moves there.
function renderCrumbs(node) {
  const items = [];
  const add = (n, here) => {
    if (!n) return;
    items.push(el("span", { class: "sep", text: "/" }));
    const label = [glyph(n.icon, defaultIcon(n)), el("span", { text: n.title })];
    if (here) { items.push(el("span", { class: "here", "aria-current": "page", title: n.title }, label)); return; }
    const a = el("a", { href: href(n.path), title: n.title }, label);
    dropTarget(a, n.path, ctx);
    items.push(a);
  };
  if (node.kind === "project") add(node, true);
  else {
    const parts = node.path ? node.path.split("/") : [];
    const top = parts.length ? index.get(parts[0]) : null;
    if (top?.project) add(index.get("@" + top.project), false);
    parts.forEach((_, i) => add(index.get(parts.slice(0, i + 1).join("/")), i === parts.length - 1));
  }
  crumbs.replaceChildren(...items);
}

function render() {
  closeMenu();
  if (!tree) return;
  const { path, params } = route();
  const node = index.get(path);
  if (!node) {
    leaveViewer();
    tools.replaceChildren(searchButton());
    crumbs.replaceChildren();
    view.replaceChildren(el("section", { class: "folder" },
      el("p", { class: "empty" }, `Nothing at “${path}” (moved or renamed?). Search for it (${SHORTCUT}), or `,
        el("a", { href: "#/", text: "go back to all passes" }), ".")));
    return;
  }
  renderCrumbs(node);
  if (node.kind === "subject") {
    renderViewer(view, tools, node, params);
    return;
  }
  leaveViewer();
  document.title = node.path ? `${node.title} — QA passes` : "QA passes";
  const home = !node.path;
  const newFolderButton = el("button", { class: "btn", type: "button", text: "+ New folder",
    title: node.kind === "project" ? `Create a family in ${node.title}` : "Create a folder here",
    onclick: () => newFolder(node.path, ctx) });
  const newProjectButton = el("button", { class: "btn", type: "button", text: "+ New project",
    title: "Create a project (work, personal…): a box of families that never mix with another project's",
    onclick: () => newProject(ctx) });
  const create = home && projects.length ? [newProjectButton] : home ? [newFolderButton, newProjectButton] : [newFolderButton];
  tools.replaceChildren(...create, searchButton());
  renderFolder(view, node, ctx);
}

// ---- theme: the pages' own key (qa-theme), so the dashboard and every pass share it ----
function setTheme(theme, fromStorage) {
  document.documentElement.dataset.theme = theme;
  themeButton.textContent = theme === "dark" ? "☀" : "☾";
  if (!fromStorage) {
    try { localStorage.setItem("qa-theme", theme); } catch (e) {}
    frameTheme(theme);
  }
}
themeButton.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
window.addEventListener("storage", (e) => { if (e.key === "qa-theme" && e.newValue) setTheme(e.newValue, true); });

// ---- search keys; a pass in the frame (same origin) finds the search here ----
window.qapDashboard = { openSearch };
document.addEventListener("keydown", (e) => {
  if (isShortcut(e)) { e.preventDefault(); openSearch(); return; }
  if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || isOpen()) return;
  if (document.body.classList.contains("viewing")) return; // a subject: / opens its pass list (viewer.js)
  const t = e.target;
  if (t && (/input|textarea|select/i.test(t.tagName || "") || t.isContentEditable)) return;
  if (document.querySelector("dialog[open]")) return;
  e.preventDefault();
  openSearch();
});

// The brand (top level) takes drops too: drag a tile there to move it to the top.
dropTarget(document.querySelector(".brand"), "", ctx);

window.addEventListener("hashchange", render);
window.addEventListener("focus", async () => {
  if (Date.now() - lastLoad < 4000) return;
  try { await load(); if (!document.body.classList.contains("viewing")) render(); } catch (e) { /* server stopped */ }
});

(async function start() {
  setTheme(document.documentElement.dataset.theme || "light", true);
  await loadIcons();
  try { await load(); } catch (e) {
    view.replaceChildren(el("p", { class: "empty", text: `Cannot read the content: ${e.message}` }));
    return;
  }
  render();
})();
