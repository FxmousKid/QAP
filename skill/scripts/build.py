#!/usr/bin/env python3
"""Build a self-contained QA pass page from its source.

Usage: python3 build.py <QA-PASS-N.src.html> <QA-PASS-N.html>

Placeholders in the source:
  {{QA_PASS_HEAD}}            -> boot snippet (theme, contents pane, pixel ratio) + the shared stylesheet
  {{QA_PASS_JS}}              -> the shared behaviour (assets/qa-pass.js): theme, contents pane, stars dialog
  {{IMG:name.png}}            -> base64 data URI of <source dir>/img/name.png (also .jpg/.jpeg/.svg/.gif/.webp)
  {{AI:vendor|Name|Model}}    -> the AI speaker label: vendor logo + "Name Model", in the vendor colour.
                                 vendor: claude | openai | gemini | other. Example: {{AI:claude|Claude|Opus 5.5}}
  {{TOPBAR}}                  -> the fixed buttons: ☰ Contents (left), theme toggle + View ★s (right)

Every <figure> is numbered "P.K" (pass P, its K-th figure; html_span.figure_labels): data-fig="P.K", id="fig-P-K"
(unless it has an id), "Figure P.K" at the start of its caption, and a "Fig. P.K" badge just above its image.

References become links (only when the target exists in the page; idempotent, so a built page builds the same):
  "subject 05", "subject 05's", "subjects 09 and 20", "subjects 04–14"  -> <a href="#p5">…</a> per number
  "figure 2.3", "Figure 2.3", "fig. 2.3"                                -> the figure numbered 2.3
  each <li> of the first <ol> of the #need section gets id="need-N"; "need item 12", "need items 9 and 12" -> #need-N
  A need item named in a message of an earlier pass (a fold, or a skipped subject's open round) is an item of
  that pass's list, not this one's, so it links to the sibling page: QA-PASS-K.html#need-N.
    an AI message of pass K (data-pass="K", or an id ending -Ka)       -> pass K's page
    a user message of pass K (the reply to pass K-1, often quoting it)  -> pass K-1's page
  The sibling is the built QA-PASS-K.html next to the source; the link is made only when it has that item.
  This pass is <meta name="qa-pass">, else the number in the source's file name.
  Never inside <a>, <code>, <pre>, <script>, <style>, <title>, <summary>, <button>, chips, AI labels, tags or
  {{…}} placeholders.

What moved since the last pass (pass 2 on; stamp_news): each subject h2 gets data-new="subject" (opened in this
pass) or data-new="round" (a new round), data-since="P" (its latest pass) and data-asks="S R" (the decisions its
AI message of this pass asks); h2#need gets data-items="K". Only the built page carries them, never the source.
qa-pass.js draws them: a NEW sign on the contents pane's line and after the subject's number, the counts and an
"Only what's new" filter at the top of the pane.

The output is one HTML file with no external dependency: it opens offline and can be sent as is.
The build refuses when a placeholder is left or an image is missing.
"""
from __future__ import annotations

import base64
import math
import pathlib
import re
import sys
from collections import Counter

SKILL = pathlib.Path(__file__).resolve().parents[1]
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
        ".gif": "image/gif", ".webp": "image/webp"}
THEME_BOOT = (
    "<script>(function(){var r=document.documentElement,t=null,o=null;"
    "try{t=localStorage.getItem('qa-theme');o=localStorage.getItem('qa-toc')}catch(e){}"
    "if(!t){t=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}"
    "r.dataset.theme=t;if(window.innerWidth>1000&&o!=='closed'){r.classList.add('toc-open')}"
    "var d=window.devicePixelRatio||1;r.dataset.dpr=d>=2.5?'3':d>=1.5?'2':'1'"
    "})();</script>"
)
STAR = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 '
        '16.84l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9z" stroke="currentColor" stroke-width="1.6" '
        'stroke-linejoin="round"/></svg>')
TOPBAR = (
    '<button class="topbtn" id="toc-toggle" type="button" aria-expanded="false" aria-controls="toc-list" '
    'title="Show or hide the contents (\\)">☰ Contents</button>\n'
    '<button class="topbtn" id="theme-toggle" type="button" aria-label="Toggle dark mode">☾ Dark</button>\n'
    '<button class="topbtn" id="stars-open" type="button" aria-haspopup="dialog" title="Starred messages">'
    f'<span class="lbl">View <span class="ss">{STAR}s</span></span><span class="count"></span></button>'
)


def _claude_logo() -> str:
    # The Claude spark: rays of uneven length around the centre, drawn in currentColor.
    rays = []
    lengths = [10.4, 8.2, 9.6, 7.6, 10.2, 8.6, 9.2, 7.8, 10.0, 8.4, 9.4, 7.9]
    for k, outer in enumerate(lengths):
        a = math.radians(k * 30 + 8)
        x1, y1 = 12 + 2.4 * math.cos(a), 12 + 2.4 * math.sin(a)
        x2, y2 = 12 + outer * math.cos(a), 12 + outer * math.sin(a)
        rays.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')
    return ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.3" '
            f'stroke-linecap="round">{"".join(rays)}</svg>')


LOGOS = {
    "claude": _claude_logo(),
    "openai": ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5">'
               + "".join(f'<rect x="8.6" y="2.6" width="6.8" height="12" rx="3.4" transform="rotate({k * 60} 12 12)"/>'
                         for k in range(6)) + "</svg>"),
    "gemini": ('<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2c.6 5.4 4.6 9.4 10 10'
               '-5.4.6-9.4 4.6-10 10-.6-5.4-4.6-9.4-10-10 5.4-.6 9.4-4.6 10-10z"/></svg>'),
    "other": ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8">'
              '<rect x="4" y="6" width="16" height="13" rx="4"/><path d="M12 6V3"/><circle cx="9" cy="12.5" r="1.3" '
              'fill="currentColor"/><circle cx="15" cy="12.5" r="1.3" fill="currentColor"/></svg>'),
}


def ai_label(vendor: str, name: str, model: str) -> str:
    vendor = vendor.strip().lower()
    if vendor not in LOGOS:
        raise SystemExit(f"build: unknown AI vendor {vendor!r}; use one of {sorted(LOGOS)}")
    return (f'<span class="ai-label ai-{vendor}">{LOGOS[vendor]}<span class="ai-name">{name.strip()}</span>'
            f'<span class="ai-model">{model.strip()}</span></span>')


# ---- references become links -------------------------------------------------------------------------------
# One pass over the source. html_span copies comments, raw blocks (pre, script, style, textarea, title) and
# {{…}} placeholders whole, and it does not treat a '>' inside a quoted attribute as the end of a tag.
# Text is linked only outside the elements below, chips (the contents pane copies them into its own links) and
# AI labels.
SKIP = {"a", "code", "summary", "button", "kbd", "samp", "h1"}
NUM = r"\d{1,2}(?![\w]|[.,:]\d)"
SEP = r"(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|\s*(?:–|-|&ndash;|&#8211;)\s*|\s+to\s+)"
REF = re.compile(rf"\b(?P<word>subjects?|need\s+items?)(?P<gap>\s+|&nbsp;)(?P<first>{NUM})(?P<rest>(?:{SEP}{NUM})*)",
                 re.I)
REST = re.compile(rf"({SEP})({NUM})", re.I)
FIG = re.compile(r"\b(?P<word>fig(?:ure|\.)?)(?P<gap>\s+|&nbsp;)(?P<n>\d{1,2}\.\d{1,2})(?![\w.]\d)", re.I)


def need_items(html: str) -> list[tuple[int, str | None, int]]:
    """The top-level <li> of the first <ol> after <h2 id="need">: (number, its id or None, where an id would go)."""
    head = re.search(r"<h2\b[^>]*\bid=\"need\"[^>]*>", html)
    if not head:
        return []
    stop = re.compile(r"<h2\b|<footer\b|</main>", re.I).search(html, head.end())
    end = stop.start() if stop else len(html)
    ol = re.compile(r"<ol\b([^>]*)>", re.I).search(html, head.end(), end)
    if not ol:
        return []
    start = re.search(r"\bstart=\"?(\d+)", ol.group(1))
    n = int(start.group(1)) if start else 1
    items, depth = [], 0
    for m in re.compile(r"<(/?)(ol|ul|li)\b([^>]*)>", re.I).finditer(html, ol.end(), end):
        closing, tag = m.group(1), m.group(2).lower()
        if tag in ("ol", "ul"):
            if closing and depth == 0:
                break  # the end of the need list
            depth += -1 if closing else 1
        elif not closing and depth == 0:
            own = re.search(r"\bid=\"([^\"]*)\"", m.group(3))
            items.append((n, own.group(1) if own else None, m.end() - 1))
            n += 1
    return items


def number_need_items(html: str) -> str:
    """Give each item of the need list an id need-N (an item that already has an id keeps it)."""
    for n, own, at in reversed(need_items(html)):
        if own is None:
            html = html[:at] + f' id="need-{n}"' + html[at:]
    return html


def number_figures(html: str, current: int | None) -> tuple[str, int]:
    """Number every figure (see the module docstring). Idempotent: a built page builds the same."""
    labels = html_span.figure_labels(html, current)
    for tag, label in reversed(labels):
        close = html.find("</figure>", tag.end)
        close = len(html) if close < 0 else close
        badge = f'<b class="fig-n">Figure {label}</b> '
        cap = re.compile(r"<figcaption\b[^>]*>", re.I).search(html, tag.end, close)
        if cap is None:
            html = html[:close] + f"<figcaption>{badge.strip()}</figcaption>" + html[close:]
        elif 'class="fig-n"' not in html[cap.end():cap.end() + 40]:
            html = html[:cap.end()] + badge + html[cap.end():]
        extra = "" if html_span.attr(tag.attrs, "data-fig") else f' data-fig="{label}"'
        if html_span.attr(tag.attrs, "id") is None:
            extra += f' id="fig-{label.replace(".", "-")}"'
        html = html[:tag.end - 1] + extra + html[tag.end - 1:]
    return html, len(labels)


PASS_META = re.compile(r"<meta\s+name=\"qa-pass\"\s+content=\"(\d+)\"", re.I)
PASS_NAME = re.compile(r"^QA-PASS-(\d+)\b")
MSG_ID_PASS = re.compile(r"-(\d+)[ua]$")


def this_pass(html: str, src: pathlib.Path | None) -> int | None:
    """The number of the pass being built: <meta name="qa-pass">, else the source's file name."""
    m = PASS_META.search(html) or (PASS_NAME.match(src.name) if src else None)
    return int(m.group(1)) if m else None


def message_page(attrs: str) -> int | None | bool:
    """For a <div>'s attributes: the pass whose need list a .msg's "need item N" means, None when the message
    has no pass, False for a div that is not a message. An AI message of pass K writes about pass K's list; a
    user message of pass K answers (and quotes) the page of pass K-1."""
    cls = re.search(r"\bclass=\"([^\"]*)\"", attrs)
    classes = cls.group(1).split() if cls else []
    if "msg" not in classes:
        return False
    found = re.search(r"\bdata-pass=\"(\d+)\"", attrs)
    if not found:
        own = re.search(r"\bid=\"([^\"]*)\"", attrs)
        found = MSG_ID_PASS.search(own.group(1)) if own else None
    if not found:
        return None
    return int(found.group(1)) - (1 if "user" in classes else 0)


def _load_html_span():
    """The scanner lives next to this script. carry.py loads it under the same module name."""
    import importlib.util
    key = "qap_skill_html_span"
    loaded = sys.modules.get(key)
    if loaded is not None:
        return loaded
    path = pathlib.Path(__file__).resolve().parent / "html_span.py"
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"build: cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


html_span = _load_html_span()


# ---- what moved since the last pass ----------------------------------------------------------------------------
# Stamped on the h2 of the built page only, never the source, so carry.py never moves a stale mark into the next
# pass. Pass 1 gets nothing. qa-pass.js draws the NEW signs, the letters and the pane's counts from these.
NEWS_ATTR = re.compile(r'\s+data-(?:new|since|asks|items)="[^"]*"')
DECISION = re.compile(r"\bDecision\s+([A-Z]\d{0,2})(?![A-Za-z0-9])")
SUBJECT_ID = re.compile(r"^p\d+$")


def _msg_pass(attrs: str) -> int | None:
    """The pass a .msg belongs to: its data-pass, else the number its id ends with (p3-4a)."""
    found = html_span.attr(attrs, "data-pass")
    if found is None:
        own = MSG_ID_PASS.search(html_span.attr(attrs, "id") or "")
        found = own.group(1) if own else None
    return int(found) if found is not None and found.isdigit() else None


def stamp_news(html: str, current: int | None) -> tuple[str, Counter]:
    """Mark what moved in pass `current` (>= 2) on each subject h2 (id pN):
      data-new="subject" data-since="N"  every message of the subject is from this pass
      data-new="round"   data-since="N"  a round of this pass after older ones
      data-since="P"                     nothing from this pass: unchanged since pass P
      data-asks="S R"                    the decisions ("Decision S: …" in a div.call.violet) of its pass-N AI messages
    and data-items="K" on h2#need, K its items. Idempotent: earlier marks are replaced."""
    heads: list[dict] = []
    divs: list[tuple[bool, int | None, bool]] = []  # open divs: (is a message, its pass, is an AI message)
    for kind, _start, _end, tag in html_span.scan(html):
        if kind != "tag" or tag is None:
            continue
        if tag.name == "h2" and not tag.closing:
            heads.append({"tag": tag, "id": html_span.attr(tag.attrs, "id") or "", "passes": set(), "asks": []})
        elif tag.name == "div" and tag.closing:
            if divs:
                divs.pop()
        elif tag.name == "div" and not tag.self_closing:
            cls = html_span.classes(tag.attrs)
            if "msg" in cls:
                p = _msg_pass(tag.attrs)
                divs.append((True, p, "user" not in cls))
                if heads and p is not None:
                    heads[-1]["passes"].add(p)
            else:
                divs.append((False, None, False))
                msg = next((d for d in reversed(divs) if d[0]), None)
                if heads and msg and msg[2] and msg[1] == current and {"call", "violet"} <= cls:
                    h4 = re.compile(r"<h4\b[^>]*>(.*?)</h4>", re.S | re.I).search(html, tag.end)
                    code = DECISION.search(re.sub(r"<[^>]+>", "", h4.group(1))) if h4 else None
                    if code and code.group(1) not in heads[-1]["asks"]:
                        heads[-1]["asks"].append(code.group(1))
    counts: Counter = Counter()
    for head in reversed(heads):
        tag, marks = head["tag"], ""
        if current is not None and current >= 2:
            if SUBJECT_ID.match(head["id"]) and head["passes"]:
                latest = max(head["passes"])
                if latest == current:
                    state = "subject" if min(head["passes"]) == current else "round"
                    marks = f' data-new="{state}"'
                    counts[state] += 1
                else:
                    counts["unchanged"] += 1
                marks += f' data-since="{latest}"'
                if head["asks"]:
                    marks += f' data-asks="{" ".join(head["asks"])}"'
                    counts["asks"] += 1
            elif head["id"] == "need":
                marks = f' data-items="{len(need_items(html))}"'
        old = html[tag.start:tag.end]
        new = NEWS_ATTR.sub("", old)
        new = new[:-1] + marks + ">" if not new.endswith("/>") else new[:-2] + marks + "/>"
        html = html[:tag.start] + new + html[tag.end:]
    return html, counts


class _Link:
    """Link "subject NN" and "need item N" in one pass over the page."""

    def __init__(self, html: str, src: pathlib.Path | None):
        self.html = html
        self.src = src
        self.ids = set(re.findall(r"\bid=\"([^\"]+)\"", html))
        self.figs = {html_span.attr(t.attrs, "data-fig"): html_span.attr(t.attrs, "id")
                     for t, _ in html_span.figure_labels(html, None) if html_span.attr(t.attrs, "data-fig")}
        self.need = {n: own for n, own, _ in need_items(html) if own}
        self.current = this_pass(html, src)
        self.sibling_need: dict[int, dict[int, str]] = {}  # pass -> its page's need ids, read once
        self.made: Counter = Counter()
        self.unresolved: list[str] = []

    def elsewhere(self, page: int | None) -> bool:
        return page is not None and self.current is not None and page != self.current

    def need_of(self, page: int | None) -> tuple[str, dict[int, str]]:
        """(href prefix, {item number: id}) of the need list a reference on `page` means: this page's, or the
        built sibling page's ({} when it is missing, or for the chat before pass 1, which has no page)."""
        if not self.elsewhere(page):
            return "", self.need
        name = f"QA-PASS-{page}.html"
        if page not in self.sibling_need:
            path = self.src.parent / name if self.src and page >= 1 else None
            items = need_items(path.read_text(encoding="utf-8")) if path and path.is_file() else []
            self.sibling_need[page] = {n: own for n, own, _ in items if own}
        return name, self.sibling_need[page]

    def target(self, word: str, number: str, page: int | None) -> str | None:
        if word.lower().startswith("need"):
            prefix, items = self.need_of(page)
            own = items.get(int(number))
            return f"{prefix}#{own}" if own else None
        for candidate in (f"p{int(number)}", f"p{number}"):
            if candidate in self.ids:
                return f"#{candidate}"
        return None

    def link_text(self, text: str, page: int | None) -> str:
        def one(m: re.Match[str]) -> str:
            word = m.group("word")
            kind = "need item" if word.lower().startswith("need") else "subject"
            where = ""
            if kind == "need item" and self.elsewhere(page):
                where = f" (QA-PASS-{page}.html)" if page >= 1 else " (the chat before pass 1)"
            first = self.target(word, m.group("first"), page)
            if first:
                self.made[kind] += 1
                self.made["earlier page"] += bool(where)
                piece = f'<a href="{first}">{word}{m.group("gap")}{m.group("first")}</a>'
            else:
                self.unresolved.append(f"{word} {m.group('first')}{where}")
                piece = f"{word}{m.group('gap')}{m.group('first')}"

            def more(r: re.Match[str]) -> str:
                t = self.target(word, r.group(2), page)
                if not t:
                    self.unresolved.append(f"{word} {r.group(2)}{where}")
                    return r.group(0)
                self.made[kind] += 1
                self.made["earlier page"] += bool(where)
                return f'{r.group(1)}<a href="{t}">{r.group(2)}</a>'

            if not word.lower().endswith("s"):  # "subject 05, 3 tables": a list needs the plural
                return piece + m.group("rest")
            return piece + REST.sub(more, m.group("rest"))

        def fig(m: re.Match[str]) -> str:
            own = self.figs.get(m.group("n"))
            if not own:
                self.unresolved.append(f"figure {m.group('n')}")
                return m.group(0)
            self.made["figure"] += 1
            return f'<a href="#{own}">{m.group(0)}</a>'

        return FIG.sub(fig, REF.sub(one, text))

    def _on_tag(self, tag, stack: list[tuple[str, bool]], divs: list) -> None:
        name, attrs = tag.name, tag.attrs
        if name == "div":
            if tag.closing:
                if divs:
                    divs.pop()
            elif not tag.self_closing:
                divs.append(message_page(attrs))
            return
        if name not in SKIP and name not in ("span", "b"):
            return
        if tag.self_closing:
            return
        if tag.closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
            return
        cls = re.search(r"\bclass=\"([^\"]*)\"", attrs)
        label = name in ("span", "b") and cls is not None and {"chip", "ai-label", "fig-n"} & set(cls.group(1).split())
        stack.append((name, name in SKIP or bool(label)))

    def run(self) -> tuple[str, Counter, list[str]]:
        out: list[str] = []
        stack: list[tuple[str, bool]] = []  # open SKIP elements and spans (a chip span skips)
        divs: list = []  # open divs: message_page() of each (False: not a message)
        for kind, start, end, tag in html_span.scan(self.html):
            chunk = self.html[start:end]
            if kind == "text":
                page = next((p for p in reversed(divs) if p is not False), None)  # the innermost message's page
                out.append(chunk if any(skip for _, skip in stack) else self.link_text(chunk, page))
                continue
            out.append(chunk)
            if kind == "tag" and tag is not None:
                self._on_tag(tag, stack, divs)
        return "".join(out), self.made, self.unresolved


def link_references(html: str, src: pathlib.Path | None = None) -> tuple[str, Counter, list[str]]:
    """Link "subject NN" and "need item N" (see the module docstring). src: the source file, whose folder holds
    the earlier passes' pages that a need item of an earlier message links to."""
    return _Link(html, src).run()


def build(src: pathlib.Path, out: pathlib.Path) -> int:
    html = src.read_text(encoding="utf-8")
    css = (SKILL / "assets" / "qa-pass.css").read_text(encoding="utf-8")
    js = (SKILL / "assets" / "qa-pass.js").read_text(encoding="utf-8")
    html = html.replace("{{QA_PASS_HEAD}}", f"{THEME_BOOT}\n<style>\n{css}\n</style>")
    html = html.replace("{{QA_PASS_JS}}", f"<script>\n{js}\n</script>")
    html = html.replace("{{TOPBAR}}", TOPBAR)
    html = re.sub(r"\{\{AI:([^|}]+)\|([^|}]+)\|([^}]+)\}\}", lambda m: ai_label(*m.groups()), html)
    # After the labels and buttons are expanded, so a built page builds the same; before the images.
    html = number_need_items(html)
    html, figures = number_figures(html, this_pass(html, src))
    html, news = stamp_news(html, this_pass(html, src))
    html, made, unresolved = link_references(html, src)

    missing: list[str] = []

    def inline(match: re.Match[str]) -> str:
        path = src.parent / "img" / match.group(1)
        if not path.is_file():
            missing.append(str(path))
            return match.group(0)
        mime = MIME.get(path.suffix.lower(), "application/octet-stream")
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

    html = re.sub(r"\{\{IMG:([^}]+)\}\}", inline, html)
    if missing:
        raise SystemExit(f"build: refused, missing images: {missing}")
    left = re.findall(r"\{\{[A-Z_]+(?::[^}]*)?\}\}", html)
    if left:
        raise SystemExit(f"build: refused, placeholders left: {sorted(set(left))}")
    out.write_text(html, encoding="utf-8")
    print(f"{out} {len(html) // 1024} KB, {html.count('data:image')} images inlined, "
          f"{figures} figures numbered, {made['subject']} subject, {made['need item']} need-item and "
          f"{made['figure']} figure references linked"
          + (f" ({made['earlier page']} to an earlier pass's page)" if made["earlier page"] else ""))
    if news:
        print(f"  since the last pass: {news['subject']} new subject(s), {news['round']} new round(s), "
              f"{news['unchanged']} unchanged; {news['asks']} subject(s) ask you a decision")
    if unresolved:
        print(f"  not linked (no such id in this page, or in the earlier page named): {sorted(set(unresolved))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    raise SystemExit(build(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])))
