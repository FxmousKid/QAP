// Plugins in the dashboard. Every enabled plugin whose manifest has a "web" part gets its web/main.js imported;
// its onload(app) receives the API below, and everything it adds is removed again when it is turned off.
//   #/~plugins                  the Plugins page: every plugin, on / off, its settings tab, its commands
//   #/~plugins/<id>/<view>      a view a plugin registered with app.registerView
// The top bar gets the plugins' status items and a ⧉ menu: the plugins' commands, then "Plugins…".
// Ctrl/⌘ + Shift + P opens that menu.
import { el, toast, menu, dialog } from "./dialogs.js";

const loaded = new Map();    // plugin id -> {module, cleanups}
const views = new Map();     // "<id>/<view>" -> {title, render}
const commands = new Map();  // "<id>:<command>" -> {name, run}
const listeners = new Map(); // event -> Set of functions
let ctx = null;
let infos = [];
let items = null;            // the top-bar container for status items and the menu button

// JSON in, JSON out. Never throws for {ok: false}: the caller reads .ok and .error (plugin results carry .text).
export async function request(path, body) {
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) };
  try {
    const res = await fetch(path, init);
    return await res.json();
  } catch (e) {
    return { ok: false, error: `the server did not answer (${e.message})` };
  }
}

export function emit(event, detail) {
  for (const fn of listeners.get(event) || []) {
    try { fn(detail); } catch (e) { console.error(`plugin listener for ${event}:`, e); }
  }
}

// ---- what a plugin's onload(app) receives ----
function apiFor(info, cleanups) {
  const id = info.id;
  const undo = (fn) => cleanups.push(fn);
  return {
    id, info, el, toast, dialog, menu,
    request: (path, body) => request(`/api/plugins/${id}/${path}`, body),  // the plugin's own routes
    run: (command, args = {}) => request(`/api/plugins/${id}/run/${command}`, args),  // its Python commands
    refresh: () => ctx.refresh(),                                          // reload the tree and redraw
    viewHref: (view) => `#/~plugins/${id}/${view}`,
    addStatusItem({ text = "", title = "", onclick = null } = {}) {
      const node = el("button", { class: "iconbtn plugin-item", type: "button", title, text, "data-plugin": id });
      if (onclick) node.addEventListener("click", onclick);
      items.insertBefore(node, items.lastElementChild);
      undo(() => node.remove());
      return node;
    },
    addCommand({ id: cid, name, run }) {
      const key = `${id}:${cid}`;
      commands.set(key, { name, run });
      undo(() => commands.delete(key));
    },
    registerView(view, { title, render }) {
      views.set(`${id}/${view}`, { title, render, plugin: info.name });
      undo(() => views.delete(`${id}/${view}`));
    },
    on(event, fn) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(fn);
      undo(() => listeners.get(event)?.delete(fn));
    },
    registerInterval(fn, ms) {
      const timer = setInterval(fn, ms);
      undo(() => clearInterval(timer));
    },
    register: undo,
  };
}

async function loadOne(info) {
  if (loaded.has(info.id) || !info.loaded || !info.web?.main) return;
  const cleanups = [];
  if (info.web.style) {
    const link = el("link", { rel: "stylesheet", href: info.web.style, "data-plugin": info.id });
    document.head.append(link);
    cleanups.push(() => link.remove());
  }
  try {
    const module = await import(info.web.main);
    loaded.set(info.id, { module, cleanups });
    await module.onload?.(apiFor(info, cleanups));
  } catch (e) {
    console.error(`plugin ${info.id}:`, e);
    toast(`Plugin ${info.name}: ${e.message}`, { error: true });
  }
}

function unloadOne(id) {
  const entry = loaded.get(id);
  if (!entry) return;
  loaded.delete(id);
  try { entry.module.onunload?.(); } catch (e) { console.error(e); }
  for (const fn of entry.cleanups.reverse()) { try { fn(); } catch (e) { console.error(e); } }
}

async function sync() {
  const data = await request("/api/plugins");
  if (!data.ok) return;
  infos = data.plugins;
  for (const id of [...loaded.keys()]) if (!infos.find((p) => p.id === id && p.loaded)) unloadOne(id);
  for (const info of infos) await loadOne(info);
}

// ---- the top bar: status items, then the ⧉ menu ----
function openMenu(anchor) {
  const list = [...commands.values()].map((c) => ({ label: c.name, run: c.run }));
  if (list.length) list.push("-");
  list.push({ label: "Plugins…", run: () => { location.hash = "#/~plugins"; } });
  menu(anchor, list);
}

export async function startPlugins(context) {
  ctx = context;
  const link = el("link", { rel: "stylesheet", href: "/ui/plugins.css" });
  document.head.append(link);
  const button = el("button", { class: "iconbtn plugin-menu", type: "button", title: "Plugins and their commands (Ctrl/⌘ ⇧ P)",
    "aria-label": "Plugins", "aria-haspopup": "menu", text: "⧉" });
  button.addEventListener("click", () => openMenu(button));
  items = el("div", { class: "plugin-items" }, button);
  document.getElementById("theme").before(items);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "p") { e.preventDefault(); openMenu(button); }
  });
  await sync();
  emit("tree", ctx.tree());
}

// ---- routes under #/~plugins ----
export function renderPluginRoute(path) {
  const { view, tools, crumbs } = ctx;
  const parts = path.split("/"); // ["~plugins", id?, view?]
  const crumb = (text, href) => href ? el("a", { href, text }) : el("span", { class: "here", text });
  if (parts.length >= 3) {
    const v = views.get(`${parts[1]}/${parts.slice(2).join("/")}`);
    crumbs.replaceChildren(el("span", { class: "sep", text: "/" }), crumb("Plugins", "#/~plugins"),
      el("span", { class: "sep", text: "/" }), crumb(v ? v.title : parts[1]));
    tools.replaceChildren();
    if (!v) {
      view.replaceChildren(el("p", { class: "empty", text: `No view “${parts.slice(1).join("/")}” (is the plugin on?).` }));
      return;
    }
    document.title = `${v.title} — QA passes`;
    const box = el("section", { class: "plugin-view" });
    view.replaceChildren(box);
    Promise.resolve(v.render(box, tools)).catch((e) => box.replaceChildren(el("p", { class: "empty", text: e.message })));
    return;
  }
  crumbs.replaceChildren(el("span", { class: "sep", text: "/" }), crumb("Plugins"));
  tools.replaceChildren();
  document.title = "Plugins — QA passes";
  renderPluginsPage(view);
}

async function renderPluginsPage(view) {
  const page = el("section", { class: "plugin-view plugins-page" },
    el("h1", { text: "Plugins" }),
    el("p", { class: "lede" }, "Core plugins ship with qap and are on unless you turn them off. Community plugins live in ",
      el("code", { text: "~/.config/qap/plugins" }), " (", el("code", { text: "qap plugins install <folder | git URL>" }),
      ") and stay off until you turn them on: a plugin runs code with your permissions."));
  view.replaceChildren(page);
  const data = await request("/api/plugins");
  if (!data.ok) { page.append(el("p", { class: "empty", text: data.error })); return; }
  infos = data.plugins;
  for (const core of [true, false]) {
    const group = infos.filter((p) => p.core === core);
    page.append(el("h2", { text: core ? "Core plugins" : "Community plugins" }));
    if (!group.length) page.append(el("p", { class: "empty", text: "None installed." }));
    for (const info of group) page.append(card(info));
  }
}

function card(info) {
  const toggle = el("input", { type: "checkbox", role: "switch", "aria-label": `Turn ${info.name || info.id} on or off` });
  toggle.checked = info.loaded;
  toggle.disabled = !info.name || info.compatible === false;
  toggle.addEventListener("change", async () => {
    const r = await request(`/api/plugins/${info.id}/${toggle.checked ? "enable" : "disable"}`, {});
    if (!r.ok) { toast(r.error, { error: true }); toggle.checked = !toggle.checked; return; }
    await sync();
    renderPluginsPage(ctx.view);
  });
  const box = el("article", { class: "plugin-card" + (info.loaded ? " on" : "") },
    el("header", {},
      el("div", {},
        el("h3", {}, info.name || info.id, " ", el("small", { text: `${info.version || ""} · ${info.core ? "core" : "community"}` })),
        info.description ? el("p", { text: info.description }) : null,
        info.author ? el("p", { class: "by", text: `by ${info.author}` }) : null),
      el("label", { class: "switch" }, toggle, el("span", { "aria-hidden": "true" }))));
  if (info.error) box.append(el("p", { class: "err", text: info.error }));
  if (info.loaded && info.settings?.length) box.append(el("h4", { text: "Settings" }), settingsForm(info));
  if (info.loaded && info.commands?.length) {
    const list = el("ul", { class: "plugin-commands" });
    for (const c of info.commands) {
      const run = c.dashboard && !c.needs_input ? el("button", { class: "btn", type: "button", text: "Run", onclick: async () => {
        run.disabled = true;
        const r = await request(`/api/plugins/${info.id}/run/${c.id}`, {});
        run.disabled = false;
        toast(r.text || r.error || "done", { error: !r.ok, ms: 9000 });
      } }) : null;
      list.append(el("li", {}, el("code", { text: c.cli }), el("span", { text: c.name }), run));
    }
    box.append(el("h4", { text: "Commands" }), list);
  }
  return box;
}

// A plugin's settings tab, drawn from the schema it declared (Setting(...) in Python): each field saves on change.
function settingsForm(info) {
  const form = el("div", { class: "plugin-settings" });
  for (const s of info.settings) {
    let input;
    if (s.type === "bool") {
      input = el("input", { type: "checkbox" });
      input.checked = !!s.value;
    } else if (s.choices.length) {
      input = el("select", {}, ...s.choices.map((c) => el("option", { value: c, text: c, selected: c === s.value })));
    } else {
      input = el("input", { type: s.type === "int" ? "number" : "text", min: s.type === "int" ? "0" : null, value: String(s.value) });
    }
    input.addEventListener("change", async () => {
      const value = s.type === "bool" ? input.checked : s.type === "int" ? Number(input.value) : input.value;
      const r = await request(`/api/plugins/${info.id}/settings`, { [s.key]: value });
      toast(r.ok ? `${s.label}: saved` : r.error, { error: !r.ok });
      if (r.ok) emit("settings", { plugin: info.id, key: s.key, value });
    });
    form.append(el("div", { class: "field" + (s.type === "bool" ? " inline" : "") },
      el("label", {}, s.type === "bool" ? input : null, el("span", { text: s.label }), s.type === "bool" ? null : input),
      s.help ? el("p", { class: "help", text: s.help }) : null));
  }
  return form;
}
