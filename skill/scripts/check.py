#!/usr/bin/env python3
"""Static check of a built QA pass page. Prints problems and warnings; exit 1 on problems.

Usage: python3 check.py <QA-PASS-N.html>

Problems (must fix):
  - unbuilt placeholders; a section h2 without an id; an open "earlier" fold;
  - a missing hook: #toc-toggle, #stars-open, #theme-toggle, #toc-list, #env, footer;
  - a .msg without an id, or a duplicate id (stars and deep links need stable, unique ids);
  - a .msg without its .who line; an AI message whose label is not the expanded {{AI:…}} logo + name + model;
  - the old format: .q / "You" blocks, or .me / .you blocks in folds ("Me" is the user, never the AI);
  - a link <a href="#x"> whose id x does not exist in the page.
Warnings (think twice):
  - a section title or a chip that uses a decision code (A1, C, D1…) without its meaning next to it
    ("D1 (drop the Langfuse ids)" or "… (D1)" is fine; "D1 built" is not): say what it means;
  - a reference without a link: "§ 4", "file.py:72", "subject 05", "need item 3" outside an <a>
    (open sections one line each; earlier folds are counted, not listed: they stay as written);
  - a subject with no open message from the user or no open answer;
  - a fold holding only one-line paragraphs while the original likely had lists (copy the original formatting);
  - no figure at all, or a numbers-heavy page with few figures;
  - decision boxes without a default, or without the "What I need from you" section.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from html.parser import HTMLParser

# A decision code: one capital letter, maybe a number (A1, C, D1, W2), standing alone.
CODE = re.compile(r"(?<![\w#@&./\\-])([A-Z])(\d{0,2})(?![\w&/-]|\.\w|['’](?![sS]\b))")
CONNECT = r"\s*(?:,|and|or|&|/|·)\s*"
# References that need a link: a section sign, a file:line, a subject or a need item.
REFS = re.compile(r"§\s*\d+(?:\.\d+)*"
                  r"|(?<![\w/])[\w.-]+\.(?:md|py|sql|ts|tsx|swift|kt|js|mjs)(?::|#L)\d+(?:[-–]L?\d+)?"
                  r"|\b[Ss]ubjects?\s+\d{1,2}\b|\bneed\s+items?\s+\d{1,2}\b")


def decision_codes(text: str) -> list[str]:
    """Decision codes in a title or chip that stand without their meaning ("D1 built", "C deferred")."""
    found = []
    for m in CODE.finditer(text):
        before, after = text[:m.start()], text[m.end():]
        if re.match(r"\s*(?:\(|:|=|—|–)", after):
            continue  # "D1 (drop the Langfuse ids)", "D1: drop …"
        if re.search(r"\(\s*(?:decision\s+)?$", before, re.I) and re.match(r"\s*\)", after):
            continue  # "… the Langfuse ids are dropped (D1)"
        if (re.search(rf"[a-z]{{3,}}[^:()]*:\s*(?:[A-Z]\d{{0,2}}{CONNECT})*$", before)
                and re.match(rf"(?:{CONNECT}[A-Z]\d{{0,2}})*\s*[?.!]?\s*$", after)):
            continue  # "Langfuse ids: D1 or D2?" (the words come first, only codes follow)
        if m.group(0) in ("A", "I"):
            # the article and the pronoun; a decision only when listed with another code ("I and J")
            listed = (re.search(rf"(?<![\w-])[A-Z]\d{{0,2}}{CONNECT}$", before)
                      or re.match(rf"{CONNECT}[A-Z]\d{{0,2}}(?![\w-])", after))
            if not listed:
                continue
        found.append(m.group(0))
    return found


# The rule, as examples. A row with no codes already says what the code means, or the capital is the
# article "A" or the pronoun "I". tests/test_pages.py checks decision_codes against this table.
EXAMPLES = (
    ("D1 built", ("D1",)),
    ("C deferred", ("C",)),
    ("B1 built; C deferred with the retype", ("B1", "C")),
    ("D1 (drop the Langfuse ids)", ()),
    ("D1: drop the column", ()),
    ("…dropped (D1)", ()),
    ("Langfuse ids: D1 or D2?", ()),
    ("the question in words: A1 or A2?", ()),
    ("A1 or A2?", ("A1", "A2")),
    ("I and J", ("I", "J")),
    ("I will wait", ()),
    ("A chart of the times", ()),
)


BLOCKS = {"p", "li", "div", "td", "th", "tr", "h1", "h2", "h3", "h4", "pre", "summary", "figcaption", "blockquote"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h2: list[dict] = []
        self.in_h2: dict | None = None
        self.stack: list[tuple[str, set[str], dict]] = []
        self.figures = 0
        self.earlier = 0
        self.earlier_open = 0
        self.calls_violet = 0
        self.ids: list[str] = []
        self.has_footer = False
        self.msgs: list[dict] = []
        self.old_format = 0
        self.section = None
        self.who_text: dict | None = None
        self.hrefs: list[str] = []
        self.chips: list[dict] = []
        self.chip: dict | None = None
        self.refs: list[dict] = []
        self.recent = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        if a.get("id"):
            self.ids.append(str(a["id"]))
        if tag == "h2":
            self.in_h2 = {"id": a.get("id"), "text": ""}
            self.section = a.get("id")
        if tag in BLOCKS:
            self.recent = ""  # the context of a reference starts in its own paragraph, cell or item
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.hrefs.append(str(a["href"]))
        if tag == "a" and a.get("name"):
            self.ids.append(str(a["name"]))
        if tag == "span" and "chip" in cls and self.chip is None:
            self.chip = {"section": self.section, "text": "", "depth": sum(1 for t, _, _ in self.stack if t == "span")}
        if tag == "figure":
            self.figures += 1
        if tag == "footer":
            self.has_footer = True
        in_fold = any(t == "details" and "earlier" in c for t, c, _ in self.stack)
        if tag == "details" and "earlier" in cls:
            self.earlier += 1
            if "open" in a:
                self.earlier_open += 1
        if tag == "div" and "call" in cls and "violet" in cls:
            self.calls_violet += 1
        if tag == "div" and ({"q"} & cls or (in_fold and {"me", "you"} & cls)):
            self.old_format += 1
        info: dict = {}
        if tag == "div" and "msg" in cls:
            info = {"id": a.get("id"), "kind": "user" if "user" in cls else "ai", "fold": in_fold,
                    "section": self.section, "who": None, "ai_label": False, "lists": 0, "paras": 0}
            self.msgs.append(info)
        if tag == "div" and "who" in cls:
            parent = self._msg()
            if parent is not None and parent["who"] is None:
                parent["who"] = ""
                self.who_text = parent
        if tag == "span" and "ai-label" in cls and self.who_text is not None:
            self.who_text["ai_label"] = True
        msg = self._msg()
        if msg is not None and tag in ("ul", "ol", "table", "figure", "pre"):
            msg["lists"] += 1
        if msg is not None and tag == "p":
            msg["paras"] += 1
        if tag not in VOID:
            self.stack.append((tag, cls, info))

    def _msg(self) -> dict | None:
        for _, cls, info in reversed(self.stack):
            if "msg" in cls and info:
                return info
        return None

    def handle_endtag(self, tag):
        if tag == "h2" and self.in_h2 is not None:
            self.h2.append(self.in_h2)
            self.in_h2 = None
        if tag == "span" and self.chip is not None and \
                sum(1 for t, _, _ in self.stack if t == "span") == self.chip["depth"] + 1:
            self.chips.append(self.chip)
            self.chip = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                closing = self.stack[i]
                del self.stack[i:]
                if tag == "div" and "who" in closing[1]:
                    self.who_text = None
                break

    def handle_data(self, data):
        if self.in_h2 is not None and not (self.stack and self.stack[-1][0] == "span" and "n" in self.stack[-1][1]):
            self.in_h2["text"] += data  # the title without its number span, so "05" + "B1 built" stays "B1 built"
        if self.who_text is not None:
            self.who_text["who"] += data
        if self.chip is not None:
            self.chip["text"] += data
        tags = [t for t, _, _ in self.stack]
        if "script" in tags or "style" in tags or "title" in tags:
            return
        if "a" not in tags and self.chip is None:  # a chip is copied into the contents' links: no link inside
            fold = any(t == "details" and "earlier" in c for t, c, _ in self.stack)
            for m in REFS.finditer(data):
                if ("pre" in tags or "code" in tags) and m.group(0)[0] in "Ssn":
                    continue  # "subject 05" in a pre or code (a ticket to paste, a diagram) is not linked by the build
                context = (self.recent + data[:m.start()])[-34:]
                context = context.split(" ", 1)[1] if " " in context[:-1] else context
                self.refs.append({"section": self.section, "ref": m.group(0), "fold": fold,
                                  "context": " ".join((context + m.group(0)).split())})
        self.recent = (self.recent + data)[-80:]


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        html = f.read()
    scan = Scan()
    scan.feed(html)
    problems, warnings = [], []
    if re.search(r"\{\{[A-Z_]+(?::[^}]*)?\}\}", html):
        problems.append("unbuilt placeholders left: run build.py")
    sections = [h for h in scan.h2 if h["text"].strip()]
    no_id = [h["text"].strip()[:50] for h in sections if not h["id"]]
    if no_id:
        problems.append(f"h2 without id (not in the contents): {no_id}")
    if scan.earlier_open:
        problems.append(f"{scan.earlier_open} 'earlier' fold(s) open by default: only the latest exchange stays open")
    for needed, why in (("toc-toggle", "Contents button"), ("stars-open", "View ★s button"),
                        ("theme-toggle", "theme toggle"), ("toc-list", "contents list"),
                        ("env", "screen diagnostic line in the footer")):
        if needed not in scan.ids:
            problems.append(f"no #{needed} ({why}): start from template/QA-PASS.src.html ({{{{TOPBAR}}}})")
    if not scan.has_footer:
        problems.append("no footer")
    dup = [i for i, n in Counter(scan.ids).items() if n > 1]
    if dup:
        problems.append(f"duplicate ids: {dup[:8]}")
    no_msg_id = sum(1 for m in scan.msgs if not m["id"])
    if no_msg_id:
        problems.append(f"{no_msg_id} .msg without an id (use p<subject>-<pass><u|a>, stable across passes)")
    no_who = [m["id"] for m in scan.msgs if m["who"] is None]
    if no_who:
        problems.append(f".msg without a .who line: {no_who[:8]}")
    bad_ai = [m["id"] for m in scan.msgs if m["kind"] == "ai" and m["who"] is not None and not m["ai_label"]]
    if bad_ai:
        problems.append(f"AI messages without the logo label ({{{{AI:claude|Claude|Opus 5.5}}}}): {bad_ai[:8]}")
    me_on_ai = [m["id"] for m in scan.msgs if m["kind"] == "ai" and (m["who"] or "").strip().lower() in ("me", "you")]
    if me_on_ai:
        problems.append(f"AI messages labelled Me/You (Me is the user): {me_on_ai[:8]}")
    if scan.old_format:
        problems.append(f"{scan.old_format} old-format blocks (.q, or .me/.you in folds): use .msg.user / .msg.ai")
    subjects = {h["id"] for h in sections if h["id"] and h["id"].startswith("p")}
    for sid in sorted(subjects, key=lambda s: (len(s), s)):
        open_msgs = [m for m in scan.msgs if m["section"] == sid and not m["fold"]]
        if open_msgs and not any(m["kind"] == "ai" for m in open_msgs):
            warnings.append(f"{sid}: the user's message has no open answer")
        if not open_msgs:
            warnings.append(f"{sid}: no open message (a settled subject still shows its last round open)")
    flat = [m["id"] for m in scan.msgs if m["fold"] and m["kind"] == "ai" and m["lists"] == 0 and m["paras"] == 1]
    if flat:
        warnings.append(f"{len(flat)} folded AI message(s) are a single paragraph: check the original had no "
                        f"options or lists to keep on their own lines ({flat[:4]})")
    if scan.figures == 0:
        warnings.append("no figure: a chart, plot, diagram or screenshot usually beats a paragraph of numbers")
    numbers = len(re.findall(r"\d+(?:[.,]\d+)?\s?%", html))
    if scan.figures and numbers / max(1, scan.figures) > 40:
        warnings.append(f"{numbers} percentages for {scan.figures} figure(s): consider another chart")
    if scan.calls_violet and "What I need from you" not in html:
        warnings.append("decision boxes but no 'What I need from you' section with the answer line")
    if scan.calls_violet and "Default" not in html:
        warnings.append("decision boxes without a 'Default:'")
    ids = set(scan.ids)
    broken = sorted({h for h in scan.hrefs if h not in ("#", "#top") and h[1:] not in ids})
    if broken:
        problems.append(f"{len(broken)} link(s) to an id that does not exist: {broken[:8]}")
    for h in sections:
        codes = decision_codes(h["text"])
        if codes:
            title = re.sub(r"^\s*\d+\s*", "", h["text"]).strip()
            warnings.append(f"{h['id']}: title uses decision code {', '.join(dict.fromkeys(codes))}: say what it "
                            f"means (\"{title[:90]}{'…' if len(title) > 90 else ''}\")")
    for c in scan.chips:
        codes = decision_codes(c["text"])
        if codes:
            warnings.append(f"{c['section'] or 'top'}: chip \"{c['text'].strip()}\" uses decision code "
                            f"{', '.join(dict.fromkeys(codes))}: say what it means")
    by_section: dict[str, list[str]] = {}
    for r in scan.refs:
        if not r["fold"]:
            by_section.setdefault(r["section"] or "top", []).append(r["context"])
    hint = " — link the exact place (GitHub blob at a SHA + #L…, a file:// URL, or the excerpt in a fold)"
    for sec, refs in by_section.items():
        distinct = list(dict.fromkeys(refs))
        shown = "; ".join(f"\"{x}\"" for x in distinct[:4]) + (f" (+{len(distinct) - 4})" if len(distinct) > 4 else "")
        warnings.append(f"{sec}: {len(refs)} reference(s) without a link: {shown}{hint}")
        hint = ""
    folded = sum(1 for r in scan.refs if r["fold"])
    if folded:
        warnings.append(f"{folded} more reference(s) without a link in earlier folds (quoted as written: link them "
                        "in the new answer when you point at them again)")
    users = sum(1 for m in scan.msgs if m["kind"] == "user")
    print(f"{path}: {len(sections)} sections, {len(scan.msgs)} messages ({users} from the user), "
          f"{scan.earlier} folds, {scan.figures} figures, {scan.calls_violet} decision boxes")
    for p in problems:
        print(f"  PROBLEM  {p}")
    for w in warnings:
        print(f"  warning  {w}")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
