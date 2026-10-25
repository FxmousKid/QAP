// The subject view: one pass in a large frame, and a selector made for subjects with 40+ passes:
// ‹ › steps, a strip of every pass number, and a searchable list (click "Pass N", or press /).
// Keys: ← → (or [ ]) older / newer, Home / End first / latest, / search. [ ] also work inside the page.
import { contentUrl } from "./api.js";
import { el } from "./dialogs.js";
import { href, shortDate } from "./tiles.js";

let current = null; // {node, index, frame, strip, pick}

export function leaveViewer() {
  current = null;
  document.body.classList.remove("viewing");
  closeList();
}

function indexOf(node, label) {
  if (label == null) return node.passes.length - 1;
  const i = node.passes.findIndex((p) => p.label === label);
  return i < 0 ? node.passes.length - 1 : i;
}

function go(i) {
  if (!current) return;
  const n = current.node.passes.length;
  i = Math.max(0, Math.min(n - 1, i));
  if (i === current.index) return;
  const latest = i === n - 1;
  location.hash = href(current.node.path, latest ? "" : "pass=" + encodeURIComponent(current.node.passes[i].label));
}

export function renderViewer(view, tools, node, params) {
  document.body.classList.add("viewing");
  if (!node.passes.length) {
    leaveViewer();
    view.replaceChildren(el("p", { class: "empty", text: "No built pass in this subject yet (qap carry, then qap build)." }));
    tools.replaceChildren();
    return;
  }
  const index = indexOf(node, params.get("pass"));
  const pass = node.passes[index];
  const url = contentUrl(node.path, pass.file) + (params.get("at") ? "#" + params.get("at") : "");
  if (current && current.node.path === node.path && current.frame.isConnected) {
    // Same subject: swap the page in place, without a second history entry.
    current.node = node;
    if (current.index !== index || params.get("at")) current.frame.contentWindow.location.replace(url);
    current.index = index;
  } else {
    const frame = el("iframe", { class: "frame", title: `${node.title}, pass ${pass.label}`, src: url });
    frame.addEventListener("load", () => { wireFrame(frame); followFrame(frame); });
    view.replaceChildren(el("section", { class: "viewer" }, frame));
    current = { node, index, frame };
  }
  current.tools = tools;
  current.frame.title = `${node.title}, pass ${pass.label}`;
  tools.replaceChildren(passNav(node, index));
  document.title = `${node.title} · pass ${pass.label} — QA passes`;
  const bar = document.querySelector(".bar");
  document.documentElement.style.setProperty("--bar-h", bar.offsetHeight + "px");
}

function passNav(node, index) {
  const passes = node.passes;
  const pass = passes[index];
  const prev = el("button", { class: "iconbtn step", type: "button", title: "Older pass (←)", "aria-label": "Older pass",
    disabled: index === 0, text: "‹", onclick: () => go(index - 1) });
  const next = el("button", { class: "iconbtn step", type: "button", title: "Newer pass (→)", "aria-label": "Newer pass",
    disabled: index === passes.length - 1, text: "›", onclick: () => go(index + 1) });
  const pick = el("button", { class: "btn pick", type: "button", "aria-haspopup": "listbox", title: "Every pass (/)",
    onclick: () => openList(pick) },
    `Pass ${pass.label}`, el("small", { text: `of ${passes.length}` }), " ▾");
  const strip = el("div", { class: "strip", role: "navigation", "aria-label": "Passes" },
    passes.map((p, i) => el("a", { href: href(node.path, i === passes.length - 1 ? "" : "pass=" + encodeURIComponent(p.label)),
      "aria-current": String(i === index), title: `${p.title || p.file} · ${shortDate(p.mtime)}`, text: p.label })));
  const open = el("a", { class: "iconbtn open-page", href: contentUrl(node.path, pass.file), target: "_blank",
    title: "Open this pass alone, in a new tab", text: "↗" });
  if (current) current.pick = pick;
  requestAnimationFrame(() => {
    const on = strip.querySelector('[aria-current="true"]');
    if (on) strip.scrollLeft = on.offsetLeft - strip.clientWidth / 2 + on.offsetWidth / 2;
  });
  return el("div", { class: "passnav" }, prev, pick, next, strip, open);
}

// ---- the searchable list ----
let list = null;
function closeList() { list?.remove(); list = null; }

function openList(anchor) {
  if (list) return closeList();
  const node = current.node;
  const input = el("input", { type: "search", placeholder: `Search ${node.passes.length} passes: number, title, date`,
    "aria-label": "Search passes" });
  const box = el("div", { class: "list", role: "listbox" });
  list = el("div", { class: "popover" }, input, box);
  let sel = 0;
  let rows = [];
  const paint = () => {
    const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    const items = node.passes.map((p, i) => ({ p, i, hay: `${p.label} ${p.title || ""} ${p.file} ${shortDate(p.mtime)} ${p.mtime}`.toLowerCase() }))
      .filter((x) => words.every((w) => x.hay.includes(w))).reverse();
    rows = items.map((x) => el("button", { class: "prow" + (x.i === current.index ? " current" : ""), type: "button",
      role: "option", onclick: () => { closeList(); go(x.i); } },
      el("b", { text: x.p.label }), el("span", { class: "t", text: x.p.title || x.p.file }),
      el("span", { class: "d", text: shortDate(x.p.mtime) })));
    box.replaceChildren(...(rows.length ? rows : [el("div", { class: "none", text: "No pass matches." })]));
    sel = Math.max(0, Math.min(sel, rows.length - 1));
    rows.forEach((r, k) => r.setAttribute("aria-selected", String(k === sel)));
    rows[sel]?.scrollIntoView({ block: "nearest" });
  };
  input.addEventListener("input", () => { sel = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(rows.length - 1, sel + 1); paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); paint(); e.preventDefault(); }
    else if (e.key === "Enter") { rows[sel]?.click(); e.preventDefault(); }
    else if (e.key === "Escape") { closeList(); anchor.focus(); }
  });
  document.body.append(list);
  const r = anchor.getBoundingClientRect();
  list.style.top = r.bottom + 6 + "px";
  list.style.left = Math.max(12, Math.min(r.left, innerWidth - list.offsetWidth - 12)) + "px";
  paint();
  input.focus();
}
document.addEventListener("pointerdown", (e) => {
  if (list && !list.contains(e.target) && !e.target.closest?.(".pick")) closeList();
});

// ---- keys: in the dashboard, and [ ] inside the framed page (same origin) ----
function onKey(e, fromFrame) {
  if (!current || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && /input|textarea|select/i.test(t.tagName || "")) return;
  if (t && t.isContentEditable) return;
  const keys = fromFrame ? { "[": -1, "]": 1 } : { ArrowLeft: -1, ArrowRight: 1, "[": -1, "]": 1 };
  if (e.key in keys) { e.preventDefault(); go(current.index + keys[e.key]); }
  else if (!fromFrame && e.key === "Home") { e.preventDefault(); go(0); }
  else if (!fromFrame && e.key === "End") { e.preventDefault(); go(current.node.passes.length - 1); }
  else if (e.key === "/" && current.pick) { e.preventDefault(); openList(current.pick); }
}
document.addEventListener("keydown", (e) => onKey(e, false));

// A link inside a page can open another pass of the subject: the selector follows it.
function followFrame(frame) {
  if (!current || current.frame !== frame) return;
  let file;
  try { file = decodeURIComponent(frame.contentWindow.location.pathname.split("/").pop()); } catch (x) { return; }
  const i = current.node.passes.findIndex((p) => p.file === file);
  if (i < 0 || i === current.index) return;
  current.index = i;
  const latest = i === current.node.passes.length - 1;
  history.replaceState(null, "", href(current.node.path, latest ? "" : "pass=" + encodeURIComponent(current.node.passes[i].label)));
  current.tools.replaceChildren(passNav(current.node, i));
}

function wireFrame(frame) {
  let doc;
  try { doc = frame.contentDocument; } catch (x) { return; }
  if (!doc || doc.__qapWired) return;
  doc.__qapWired = true;
  doc.addEventListener("keydown", (e) => onKey(e, true));
  // A theme picked in the dashboard reaches pages built before they listened for it.
  const theme = document.documentElement.dataset.theme;
  if (doc.documentElement.dataset.theme && doc.documentElement.dataset.theme !== theme) {
    doc.getElementById("theme-toggle")?.click();
  }
}

export function frameTheme(theme) {
  try {
    const doc = current?.frame.contentDocument;
    if (doc && doc.documentElement.dataset.theme && doc.documentElement.dataset.theme !== theme) {
      const toggle = doc.getElementById("theme-toggle");
      if (toggle) toggle.click(); else doc.documentElement.dataset.theme = theme;
    }
  } catch (x) { /* a page from elsewhere */ }
}
