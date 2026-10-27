// Fuzzy ranking for the search dialog. Pure functions, no DOM: tests/test_search.py runs it with node.
//
// The query is split on spaces and every word must match some field of an item. A word against one field, best
// match first:
//   100  the whole field                                  "rbac"    ~ "RBAC"
//    85  the start of the field                           "migr"    ~ "Migration v3"
//    75  the start of a word in it                        "flex"    ~ "We go with the Flex tier"
//    50  anywhere in it                                   "lex"     ~ "Flex"
//        (+5 when the word ends where a word of the field ends)
//    72  the same word, give or take a plural              "retry"   ~ "Payment retries"
//    62  the start of such a word                          "retri"   ~ "retries"
//    60  the same letters without separators              "inv204"  ~ "inv-204"
//  ≤ 45  its letters in order, like fzf: word starts      "dbmig"   ~ "DB migration"
//        and runs of letters count, gaps cost
//  ≤ 34  one typo (two in words of 8 letters or more):    "migartion" ~ "migration"
//        a swapped, missing, extra or wrong letter
//  ≤ 30  trigram likeness with a whole word
// A word of digits only matches whole numbers: "3" finds pass 3 and "3 retries", never "2026-10-03" or "13".
// Case and accents never matter.
//
// An item's score is the sum, over the words, of its best field score times that field's weight (a title counts
// 1, the breadcrumb above it 0.25 to 0.4), plus a bonus when the whole phrase sits in one field, a small kind order
// (project, folder, subject, pass) and freshness. Results under a third of the best score are dropped: they are
// noise next to it.

const MARKS = /\p{M}/gu;
const ALNUM = /[\p{L}\p{N}]/u;
const DIGIT = /[0-9]/;
const KIND_BONUS = { project: 4, folder: 3, subject: 2, pass: 0 };
export const KIND_ORDER = ["project", "folder", "subject", "pass"];

const isAlnum = (c) => c !== undefined && ALNUM.test(c);
const isDigit = (c) => c !== undefined && DIGIT.test(c);

// Lower case, accents off. map[i] is the index in the original text of folded character i (map has one extra
// entry, the text's length), so a match in the folded text can be highlighted in the original.
export function fold(text) {
  const t = String(text ?? "");
  let s = "";
  const map = [];
  for (let i = 0; i < t.length;) {
    const ch = String.fromCodePoint(t.codePointAt(i));
    const f = ch.normalize("NFD").replace(MARKS, "").toLowerCase();
    for (let k = 0; k < f.length; k++) map.push(i);
    s += f;
    i += ch.length;
  }
  map.push(t.length);
  return { s, map };
}

// A word without its plural or its -ing/-ed ending: "retries" -> "retry", "passes" -> "pass", "indexing" -> "index".
// Crude on purpose: it only has to make a word and its plural meet.
export function stem(w) {
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 4 && /(ss|sh|ch|x|z)es$/.test(w)) return w.slice(0, -2);
  if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith("ed") && !w.endsWith("eed")) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !/(ss|us|is)$/.test(w)) return w.slice(0, -1);
  return w;
}

// A field, ready to match: folded text, word starts, words (and their stems), the text without separators.
export function field(text) {
  const { s, map } = fold(text);
  const starts = new Array(s.length).fill(false);
  const words = [];
  let from = -1;
  for (let i = 0; i < s.length; i++) {
    const a = isAlnum(s[i]);
    const prev = s[i - 1];
    if (a && (i === 0 || !isAlnum(prev) || isDigit(prev) !== isDigit(s[i]))) starts[i] = true;
    if (a && from < 0) from = i;
    if (!a && from >= 0) { words.push([from, i]); from = -1; }
  }
  if (from >= 0) words.push([from, s.length]);
  let cs = "";
  const cmap = [];
  for (let i = 0; i < s.length; i++) if (isAlnum(s[i])) { cs += s[i]; cmap.push(i); }
  const stems = words.map(([a, b]) => stem(s.slice(a, b)));
  return { text: String(text ?? ""), s, map, starts, words, stems, cs, cmap };
}

function ranges(positions) {
  const out = [];
  for (const p of positions) {
    const last = out[out.length - 1];
    if (last && last[1] === p) last[1] = p + 1;
    else out.push([p, p + 1]);
  }
  return out;
}

function numberMatch(t, F) {
  const s = F.s;
  let prefix = null;
  for (let i = s.indexOf(t); i >= 0; i = s.indexOf(t, i + 1)) {
    const end = i + t.length;
    if (isDigit(s[i - 1])) continue;
    if (!isDigit(s[end])) return { score: i === 0 && end === s.length ? 100 : 70, ranges: [[i, end]] };
    if (!prefix) prefix = { score: 30, ranges: [[i, end]] };  // "11" starts "111"
  }
  return prefix;
}

function subsequence(t, F) {
  const s = F.s;
  let best = null;
  for (let start = s.indexOf(t[0]); start >= 0; start = s.indexOf(t[0], start + 1)) {
    const pos = [start];
    for (let k = 1, j = start + 1; k < t.length; k++) {
      const at = s.indexOf(t[k], j);
      if (at < 0) return best; // a later start has fewer letters after it: it cannot match either
      pos.push(at);
      j = at + 1;
    }
    let raw = 0;
    pos.forEach((p, k) => { raw += 1 + (F.starts[p] ? 2 : 0) + (k && p === pos[k - 1] + 1 ? 1.5 : 0); });
    const span = pos[pos.length - 1] - pos[0] + 1;
    const q = raw / (t.length * 3) - Math.min(0.35, (span - t.length) / (t.length * 6));
    if (q < 0.4) continue; // scattered letters are noise, not a match
    const score = Math.round(45 * Math.min(1, q));
    if (!best || score > best.score) best = { score, ranges: ranges(pos) };
  }
  return best;
}

// Optimal string alignment distance (Levenshtein plus swaps of two neighbours), giving up above max.
export function osa(a, b, max = 2) {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    let low = Infinity;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, d[i - 2][j - 2] + 1);
      d[i][j] = v;
      low = Math.min(low, v);
    }
    if (low > max) return max + 1;
  }
  return d[a.length][b.length];
}

function trigrams(w) {
  const p = ` ${w} `;
  const out = new Set();
  for (let i = 0; i + 3 <= p.length; i++) out.add(p.slice(i, i + 3));
  return out;
}

export function dice(a, b) {
  const A = trigrams(a), B = trigrams(b);
  let common = 0;
  for (const g of A) if (B.has(g)) common++;
  return (2 * common) / (A.size + B.size);
}

function typo(t, F) {
  const max = t.length >= 8 ? 2 : 1;
  let best = null;
  const take = (score, a, b) => { if (!best || score > best.score) best = { score, ranges: [[a, b]] }; };
  for (const [a, b] of F.words) {
    const w = F.s.slice(a, b);
    if (w.length < 3 || w[0] !== t[0]) continue;
    // the whole word, or its start (a word still being typed)
    for (const len of new Set([w.length, t.length - 1, t.length, t.length + 1])) {
      if (len < 3 || len > w.length || Math.abs(len - t.length) > max) continue;
      const dist = osa(t, w.slice(0, len), max);
      if (dist >= 1 && dist <= max) take((len === w.length ? 34 : 30) - 9 * dist, a, a + len);
    }
    const sim = dice(t, w);
    if (sim >= 0.5) take(Math.round(30 * sim), a, b);
  }
  return best;
}

// The best match of one query word (already folded) in one field: {score 0–105, ranges in F.s} or null.
export function matchWord(t, F) {
  if (!t || !F.s) return null;
  if (/^[0-9]+$/.test(t)) return numberMatch(t, F);
  const s = F.s;
  const first = s.indexOf(t);
  if (first >= 0) {
    let at = first;
    for (let j = first; j >= 0; j = s.indexOf(t, j + 1)) if (F.starts[j]) { at = j; break; }
    const end = at + t.length;
    let score = at === 0 && end === s.length ? 100 : at === 0 ? 85 : F.starts[at] ? 75 : 50;
    if (score < 100 && !isAlnum(s[end])) score += 5;
    return { score, ranges: [[at, end]] };
  }
  const st = stem(t);
  let near = null;
  F.words.forEach(([a, b], k) => {
    if (F.stems[k] === st) near = near && near.score >= 72 ? near : { score: 72, ranges: [[a, b]] };
    else if (!near && st.length >= 3 && F.stems[k].startsWith(st)) near = { score: 62, ranges: [[a, b]] };
  });
  if (near) return near;
  const ct = t.replace(/[^\p{L}\p{N}]/gu, "");
  if (ct.length >= 2) {
    const k = F.cs.indexOf(ct);
    if (k >= 0) return { score: 60, ranges: ranges(F.cmap.slice(k, k + ct.length)) };
  }
  let best = t.length >= 2 ? subsequence(t, F) : null;
  if (t.length >= 4) {
    const near = typo(t, F);
    if (near && (!best || near.score > best.score)) best = near;
  }
  return best;
}

// The fields an item is searched by, with their weights. Items come from GET /api/search (qap/search.py).
export function prepare(items) {
  for (const it of items) {
    const fields = [];
    const add = (key, text, weight, extra = {}) => {
      if (text) fields.push({ key, weight, ...field(text), ...extra });
    };
    const crumbs = it.crumbs || [];
    add("title", it.title, 1);
    if (it.kind === "pass") {
      add("label", it.label, 1);
      add("pass", `pass ${it.label}`, 1);
      (it.sections || []).forEach((sec) => add("section", sec.title, 0.8, { section: sec }));
      add("kicker", it.kicker, 0.5);
      add("subject", crumbs[crumbs.length - 1], 0.5);
      add("crumbs", crumbs.slice(0, -1).join(" › "), 0.25);
    } else {
      add("name", it.name, it.kind === "project" ? 0.9 : 0.85);
      if (it.kind === "subject") add("qa_project", it.qa_project, 0.85);
      add("crumbs", crumbs.join(" › "), 0.4);
    }
    it._fields = fields;
  }
  return items;
}

function freshness(iso, now) {
  const t = Date.parse(iso || "");
  if (!t) return 0;
  return 3 * Math.max(0, 1 - (now - t) / (60 * 86400e3));
}

// Every item matching every word of the query, best first: [{item, score, hits: [{field, score, ranges}]}].
export function search(items, query, now = Date.now()) {
  const words = fold(query).s.split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const phrase = words.length > 1 ? words.join(" ") : "";
  const out = [];
  for (const it of items) {
    let total = 0;
    const hits = [];
    for (const w of words) {
      let best = null;
      for (const f of it._fields) {
        const m = matchWord(w, f);
        if (m && (!best || m.score * f.weight > best.score)) best = { field: f, score: m.score * f.weight, ranges: m.ranges };
      }
      if (!best) { total = -1; break; }
      total += best.score;
      hits.push(best);
    }
    if (total < 0) continue;
    if (phrase) {
      const holder = it._fields.filter((f) => f.s.includes(phrase)).sort((a, b) => b.weight - a.weight)[0];
      if (holder) total += 20 * holder.weight;
    }
    total += KIND_BONUS[it.kind] + freshness(it.updated, now) + (it.latest ? 1 : 0);
    out.push({ item: it, score: total, hits });
  }
  let top = 0;
  for (const r of out) top = Math.max(top, r.score);
  return out.filter((r) => r.score >= top / 3).sort((a, b) =>
    b.score - a.score || KIND_ORDER.indexOf(a.item.kind) - KIND_ORDER.indexOf(b.item.kind) ||
    String(b.item.updated || "").localeCompare(String(a.item.updated || "")));
}

// Where to highlight a field's text: [[start, end], …] in the original text, merged and sorted.
export function marks(F, rangeList) {
  const spans = rangeList.map(([a, b]) => [F.map[a], F.map[b]]).sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const [a, b] of spans) {
    const last = out[out.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return out;
}
