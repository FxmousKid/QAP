// The search dialog: every project, family, subject and pass, ranked as you type (fuzzy.js) and shown as cards
// carrying the same coloured icon boxes as the dashboard's tiles. Empty, it shows the home: the projects (or the
// top-level tiles) and the subjects updated last.
//
// The dashboard imports it; a pass page served by `qap serve` loads it from /ui/search.js the first time its
// Search button (or ⌘K, /) is used, so the two share this one file. It only reads the palette variables both
// define. The server builds the index (GET /api/search); it is fetched when the dialog opens and kept 15 s.
//
// Keys: type to search · ↑ ↓ the row above or below · Tab, Shift+Tab the next or previous card · Enter opens
// (⌘/Ctrl+Enter: a new tab) · Esc closes.
import { el } from "./dom.js";
import { loadIcons, glyph, colorOf, defaultIcon } from "./icons.js";
import { prepare, search, marks, KIND_ORDER } from "./fuzzy.js";

const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
export const SHORTCUT = MAC ? "⌘K" : "Ctrl+K";
const HEADS = { project: "Projects", folder: "Families", subject: "Subjects", pass: "Passes" };
const LIMITS = { project: 12, folder: 12, subject: 18, pass: 24 };
const MAGNIFIER = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20.5 20.5"/></svg>';

// prefix goes before every "#/…" route: "" in the dashboard, "/" in a pass page (results open the dashboard).
const options = { prefix: "" };
export function configure(o) { Object.assign(options, o); }

export function isShortcut(e) {
  return (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K");
}

// ---- the index ----
let index = null;
let fetchedAt = 0;
let loading = null;

export function invalidate() { fetchedAt = 0; }

function loadIndex() {
  if (index && Date.now() - fetchedAt < 15000) return Promise.resolve(index);
  if (!loading) {
    loading = fetch("/api/search", { cache: "no-store" })
      .then((res) => res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` })))
      .then((data) => {
        if (!data.ok) throw new Error(data.error || "the index did not load");
        index = { ...data, items: prepare(data.items) };
        fetchedAt = Date.now();
        return index;
      })
      .finally(() => { loading = null; });
  }
  return loading;
}

// ---- the stylesheet (a pass page does not have it until the first open) ----
let styled = null;
function ensureStyles() {
  if (styled) return styled;
  const href = new URL("./search.css", import.meta.url).href;
  if ([...document.querySelectorAll('link[rel="stylesheet"]')].some((l) => l.href === href)) {
    styled = Promise.resolve();
  } else {
    const link = el("link", { rel: "stylesheet", href });
    styled = new Promise((done) => { link.onload = link.onerror = done; setTimeout(done, 1500); });
    document.head.append(link);
  }
  return styled;
}

// ---- the button: top right of the dashboard bar, left of ‹ in the pass viewer ----
export function searchButton({ compact = false } = {}) {
  const b = el("button", { class: "searchbtn" + (compact ? " compact" : ""), type: "button", "aria-label": "Search",
    title: `Search every project, family, subject and pass (${SHORTCUT})`, "aria-keyshortcuts": MAC ? "Meta+K" : "Control+K",
    onclick: () => openSearch() });
  b.innerHTML = MAGNIFIER;
  b.append(el("span", { class: "lbl", text: "Search" }), el("kbd", { text: SHORTCUT }));
  return b;
}

// ---- the dialog ----
let dlg = null;
let input = null;
let body = null;
let foot = null;
let cards = [];
let active = 0;
let opener = null;

function build() {
  input = el("input", { type: "text", class: "qs-input", placeholder: "Search projects, families, subjects and passes",
    "aria-label": "Search", autocomplete: "off", spellcheck: "false", enterkeyhint: "go", role: "combobox",
    "aria-expanded": "true", "aria-controls": "qs-results", "aria-autocomplete": "list" });
  const mag = el("span", { class: "qs-mag" });
  mag.innerHTML = MAGNIFIER;
  const close = el("button", { class: "qs-close", type: "button", "aria-label": "Close", title: "Close (Esc)",
    onclick: () => closeSearch() }, el("kbd", { text: "esc" }));
  body = el("div", { class: "qs-body", id: "qs-results", role: "listbox", "aria-label": "Results" });
  foot = el("div", { class: "qs-foot" });
  dlg = el("dialog", { class: "qs", "aria-label": "Search" },
    el("div", { class: "qs-head" }, mag, input, close), body, foot);
  input.addEventListener("input", () => paint());
  input.addEventListener("keydown", onKey);
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); closeSearch(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeSearch(); }); // the backdrop
  body.addEventListener("mousemove", (e) => {
    const c = e.target.closest?.(".qs-card");
    if (c && Number(c.dataset.i) !== active) setActive(Number(c.dataset.i), false);
  });
  body.addEventListener("click", (e) => {
    const c = e.target.closest?.(".qs-card");
    if (c && !(e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1)) closeSearch(false);
  });
  document.body.append(dlg);
}

export function isOpen() { return !!dlg?.open; }

export async function openSearch() {
  await ensureStyles();
  if (!dlg) build();
  if (!dlg.open) {
    opener = document.activeElement;
    dlg.showModal();
  }
  input.focus();
  input.select();
  paint();
  try {
    await Promise.all([loadIcons(), loadIndex()]);
    if (dlg.open) paint();
  } catch (e) {
    body.replaceChildren(el("div", { class: "qs-empty" }, "Search needs the server of ", el("code", { text: "qap serve" }),
      ` (${e.message}). Open the dashboard with qap serve --open.`));
  }
}

export function closeSearch(restoreFocus = true) {
  if (!dlg?.open) return;
  dlg.close();
  if (restoreFocus && opener?.isConnected) opener.focus?.({ preventScroll: true });
}

function onKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); step(e.key === "ArrowDown" ? "down" : "up"); }
  else if (e.key === "Tab") { e.preventDefault(); step(e.shiftKey ? "prev" : "next"); }
  else if (e.key === "Enter") { e.preventDefault(); openCard(cards[active], e.metaKey || e.ctrlKey); }
  else if (e.key === "Escape") { e.preventDefault(); closeSearch(); }
}

function openCard(card, newTab) {
  if (!card) return;
  if (newTab) { window.open(card.href, "_blank", "noopener"); return; }
  closeSearch(false);
  location.assign(card.href);
}

function setActive(i, scroll) {
  cards[active]?.setAttribute("aria-selected", "false");
  active = i;
  const c = cards[i];
  if (!c) { input.removeAttribute("aria-activedescendant"); return; }
  c.setAttribute("aria-selected", "true");
  input.setAttribute("aria-activedescendant", c.id);
  if (scroll) c.scrollIntoView({ block: "nearest" });
}

// ↑ ↓ go to the nearest card in the row above or below, whatever the number of columns; Tab goes in reading order.
function step(dir) {
  if (!cards.length) return;
  if (dir === "next" || dir === "prev") return setActive((active + (dir === "next" ? 1 : -1) + cards.length) % cards.length, true);
  const cur = cards[active].getBoundingClientRect();
  const x = cur.left + cur.width / 2;
  let best = -1;
  let bestCost = Infinity;
  cards.forEach((c, i) => {
    const r = c.getBoundingClientRect();
    const gap = dir === "down" ? r.top - cur.bottom : cur.top - r.bottom;
    if (i === active || gap < -2) return;
    const cost = gap * 1000 + Math.abs(r.left + r.width / 2 - x);
    if (cost < bestCost) { bestCost = cost; best = i; }
  });
  if (best >= 0) setActive(best, true);
}

// ---- what the dialog shows ----
function paint() {
  const q = input.value.trim();
  if (!index) {
    body.replaceChildren(el("div", { class: "qs-empty", text: "Loading the index…" }));
    return;
  }
  const groups = q ? ranked(q) : home();
  cards = [];
  const sections = groups.filter((g) => g.rows.length).map((g) => {
    const shown = g.rows.slice(0, g.limit || g.rows.length);
    return el("section", { class: "qs-group", "aria-label": g.title },
      el("div", { class: "qs-h" }, g.title, el("span", { class: "n", text: String(g.rows.length) })),
      el("div", { class: "qs-grid" }, shown.map((r) => card(r))),
      g.rows.length > shown.length
        ? el("div", { class: "qs-more", text: `${g.rows.length - shown.length} more: add a word to narrow the search` }) : null);
  });
  body.replaceChildren(...(sections.length ? sections : [el("div", { class: "qs-empty" },
    `Nothing matches “${q}”. Every word must match: try fewer words, or a part of a name.`)]));
  body.scrollTop = 0;
  active = 0;
  setActive(0, false);
  const projects = index.projects ? `${index.projects} project${index.projects === 1 ? "" : "s"} · ` : "";
  const total = index.items.filter((i) => i.kind !== "project").length;
  foot.replaceChildren(
    el("span", { class: "keys" }, el("kbd", { text: "↑↓" }), " ", el("kbd", { text: "tab" }), " move ",
      el("kbd", { text: "↵" }), " open ", el("kbd", { text: MAC ? "⌘↵" : "Ctrl+↵" }), " new tab"),
    el("span", { class: "sp" }),
    el("span", { text: `${projects}${total} families, subjects and passes` }));
}

// Grouped like the home: projects, then families, subjects, passes; best first inside each group.
function ranked(q) {
  const results = search(index.items, q);
  return KIND_ORDER.map((kind) => ({ title: HEADS[kind], rows: results.filter((r) => r.item.kind === kind), limit: LIMITS[kind] }));
}

function home() {
  const items = index.items;
  const top = index.projects
    ? items.filter((i) => i.kind === "project")
    : items.filter((i) => (i.kind === "folder" || i.kind === "subject") && !i.crumbs.length);
  const recent = items.filter((i) => i.kind === "subject" && i.updated)
    .sort((a, b) => b.updated.localeCompare(a.updated)).slice(0, 6);
  return [{ title: index.projects ? "Projects" : "Home", rows: top.map((item) => ({ item, hits: [] })) },
    { title: "Updated last", rows: recent.map((item) => ({ item, hits: [] })) }];
}

function card(r) {
  const it = r.item;
  const i = cards.length;
  const section = r.hits.filter((h) => h.field.key === "section").sort((a, b) => b.score - a.score)[0];
  const href = options.prefix + it.href + (section ? `&at=${encodeURIComponent(section.field.section.id)}` : "");
  const title = it.title || (it.kind === "pass" ? `Pass ${it.label}` : it.name);
  const a = el("a", { class: "qs-card", href, role: "option", id: `qs-o${i}`, "aria-selected": "false", "data-i": i,
    title: [...it.crumbs, title].join(" › ") },
    icon(it),
    el("span", { class: "qs-text" },
      el("span", { class: "qs-title" }, lit(title, r.hits.filter((h) => h.field.key === "title"))),
      it.crumbs.length ? el("span", { class: "qs-crumbs", text: it.crumbs.join(" › ") }) : null,
      section ? el("span", { class: "qs-secline" }, section.field.section.num ? el("b", { text: section.field.section.num }) : "§ ",
        lit(section.field.text, r.hits.filter((h) => h.field === section.field), 16)) : null,
      el("span", { class: "qs-meta", text: meta(it) })));
  cards.push(a);
  return a;
}

// The tile's box, small: its colour, its icon, a tab for a family, the pass count (or the pass number) as a badge.
function icon(it) {
  const box = el("span", { class: "qs-box" }, glyph(it.icon, defaultIcon(it)));
  if (it.kind === "subject") box.append(el("span", { class: "qs-badge", text: String(it.count) }));
  if (it.kind === "pass") box.append(el("span", { class: "qs-badge", text: it.label }));
  const wrap = el("span", { class: `qs-icon is-${it.kind}` }, box);
  wrap.style.setProperty("--box", colorOf(it));
  return wrap;
}

// A text with its matched letters in <mark>; hits whose field shows this very text. lead: on a one-line text, the
// most characters kept before the first match (the start is cut at a word, "…"), so the match stays in view.
function lit(text, hits, lead = 0) {
  if (!hits.length) return text;
  const field = hits[0].field;
  if (field.text !== text) return text;
  const spans = marks(field, hits.flatMap((h) => h.ranges));
  const out = [];
  let at = 0;
  if (lead && spans.length && spans[0][0] > lead) {
    const space = text.indexOf(" ", spans[0][0] - lead + 6);
    at = space > 0 && space < spans[0][0] ? space + 1 : spans[0][0] - lead + 8;
    out.push("…");
  }
  for (const [a, b] of spans) {
    if (a > at) out.push(text.slice(at, a));
    out.push(el("mark", { text: text.slice(a, b) }));
    at = b;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + "s"}`; }

function meta(it) {
  const date = when(it.updated);
  const parts = {
    project: [plural(it.families || 0, "family", "families"), plural(it.count || 0, "subject")],
    folder: [plural(it.count || 0, "subject"), date],
    subject: [plural(it.count || 0, "pass", "passes"), date],
    pass: [`pass ${it.label}`, date, it.latest ? "latest" : ""],
  }[it.kind];
  return parts.filter(Boolean).join(" · ");
}
