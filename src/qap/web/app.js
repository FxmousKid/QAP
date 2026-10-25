// QA passes dashboard: a hash router over the content tree.
//   #/                       the top level (tiles)
//   #/authz                  a folder (tiles)
//   #/authz/rbac             a subject: its latest pass in the frame
//   #/authz/rbac?pass=3      a given pass;  &at=p3-1a  opens the page at that message
import { api } from "./api.js";
import { loadIcons, glyph } from "./icons.js";
import { el, toast, closeMenu } from "./dialogs.js";
import { renderFolder, dropTarget, newFolder, href } from "./tiles.js";
import { renderViewer, leaveViewer, frameTheme } from "./viewer.js";

const view = document.getElementById("view");
const crumbs = document.getElementById("crumbs");
const tools = document.getElementById("tools");
const themeButton = document.getElementById("theme");

let tree = null;
let index = new Map(); // path -> node
let lastLoad = 0;

const ctx = {
  tree: () => tree,
  find: (path) => index.get(path),
  refresh: async () => { await load(); render(); },
};

async function load() {
  const data = await api.tree();
  tree = data.tree;
  index = new Map();
  const walk = (n) => { index.set(n.path, n); (n.children || []).forEach(walk); };
  walk(tree);
  lastLoad = Date.now();
}

function route() {
  const raw = location.hash.replace(/^#\/?/, "");
  const q = raw.indexOf("?");
  const path = decodeURIComponent(q < 0 ? raw : raw.slice(0, q)).replace(/^\/+|\/+$/g, "");
  return { path, params: new URLSearchParams(q < 0 ? "" : raw.slice(q + 1)) };
}

function renderCrumbs(node) {
  const parts = node.path ? node.path.split("/") : [];
  const items = [];
  parts.forEach((_, i) => {
    const p = parts.slice(0, i + 1).join("/");
    const n = index.get(p);
    if (!n) return;
    items.push(el("span", { class: "sep", text: "/" }));
    const here = i === parts.length - 1;
    const label = [glyph(n.icon, n.kind === "folder" ? "folder" : "doc"), el("span", { text: n.title })];
    if (here) items.push(el("span", { class: "here", "aria-current": "page", title: n.title }, label));
    else {
      const a = el("a", { href: href(p), title: n.title }, label);
      dropTarget(a, p, ctx);
      items.push(a);
    }
  });
  crumbs.replaceChildren(...items);
}

function render() {
  closeMenu();
  if (!tree) return;
  const { path, params } = route();
  const node = index.get(path);
  if (!node) {
    leaveViewer();
    tools.replaceChildren();
    crumbs.replaceChildren();
    view.replaceChildren(el("section", { class: "folder" },
      el("p", { class: "empty" }, `Nothing at “${path}” (moved or renamed?). `, el("a", { href: "#/", text: "Back to all passes" }))));
    return;
  }
  renderCrumbs(node);
  if (node.kind === "subject") {
    renderViewer(view, tools, node, params);
    return;
  }
  leaveViewer();
  document.title = node.path ? `${node.title} — QA passes` : "QA passes";
  tools.replaceChildren(el("button", { class: "btn", type: "button", text: "+ New folder",
    title: "Create a folder here", onclick: () => newFolder(node.path, ctx) }));
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
