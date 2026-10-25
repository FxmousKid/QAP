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

References become links (only when the target exists in the page; idempotent, so a built page builds the same):
  "subject 05", "subject 05's", "subjects 09 and 20", "subjects 04–14"  -> <a href="#p5">…</a> per number
  each <li> of the first <ol> of the #need section gets id="need-N"; "need item 12", "need items 9 and 12" -> #need-N
  Never inside <a>, <code>, <pre>, <script>, <style>, <title>, <summary>, <button>, chips, AI labels, tags or
  {{…}} placeholders.

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
# One pass over the source: comments, raw-text blocks, tags and {{…}} placeholders are copied untouched; text is
# linked only outside the elements below, chips (the contents pane copies them into its own links) and AI labels.
SKIP = {"a", "code", "summary", "button", "kbd", "samp", "h1"}
TOKENS = re.compile(
    r"<!--.*?-->"
    r"|<(script|style|pre|textarea|title)\b[^>]*>.*?</\1\s*>"
    r"|<[a-zA-Z/!][^>\"']*(?:(?:\"[^\"]*\"|'[^']*')[^>\"']*)*>"
    r"|\{\{.*?\}\}",
    re.S | re.I,
)
TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*)>", re.S)
NUM = r"\d{1,2}(?![\w]|[.,:]\d)"
SEP = r"(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|\s*(?:–|-|&ndash;|&#8211;)\s*|\s+to\s+)"
REF = re.compile(rf"\b(?P<word>subjects?|need\s+items?)(?P<gap>\s+|&nbsp;)(?P<first>{NUM})(?P<rest>(?:{SEP}{NUM})*)",
                 re.I)
REST = re.compile(rf"({SEP})({NUM})", re.I)


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


def link_references(html: str) -> tuple[str, Counter, list[str]]:
    ids = set(re.findall(r"\bid=\"([^\"]+)\"", html))
    need = {n: own for n, own, _ in need_items(html) if own}
    made: Counter = Counter()
    unresolved: list[str] = []

    def target(word: str, number: str) -> str | None:
        if word.lower().startswith("need"):
            return need.get(int(number))
        for candidate in (f"p{int(number)}", f"p{number}"):
            if candidate in ids:
                return candidate
        return None

    def link_text(text: str) -> str:
        def one(m: re.Match[str]) -> str:
            word = m.group("word")
            kind = "need item" if word.lower().startswith("need") else "subject"
            first = target(word, m.group("first"))
            if first:
                made[kind] += 1
                piece = f'<a href="#{first}">{word}{m.group("gap")}{m.group("first")}</a>'
            else:
                unresolved.append(f"{word} {m.group('first')}")
                piece = f"{word}{m.group('gap')}{m.group('first')}"

            def more(r: re.Match[str]) -> str:
                t = target(word, r.group(2))
                if not t:
                    unresolved.append(f"{word} {r.group(2)}")
                    return r.group(0)
                made[kind] += 1
                return f'{r.group(1)}<a href="#{t}">{r.group(2)}</a>'

            if not word.lower().endswith("s"):  # "subject 05, 3 tables": a list needs the plural
                return piece + m.group("rest")
            return piece + REST.sub(more, m.group("rest"))

        return REF.sub(one, text)

    out: list[str] = []
    stack: list[tuple[str, bool]] = []  # open SKIP elements and spans (a chip span skips)
    pos = 0
    for m in TOKENS.finditer(html):
        text = html[pos:m.start()]
        out.append(link_text(text) if not any(skip for _, skip in stack) else text)
        out.append(m.group(0))
        pos = m.end()
        tag = TAG.match(m.group(0))
        if not tag or m.group(0).startswith("<!--"):
            continue
        closing, name, attrs = tag.group(1), tag.group(2).lower(), tag.group(3)
        if name not in SKIP and name != "span":
            continue
        if attrs.rstrip().endswith("/"):
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
        else:
            cls = re.search(r"\bclass=\"([^\"]*)\"", attrs)
            label = name == "span" and cls is not None and {"chip", "ai-label"} & set(cls.group(1).split())
            stack.append((name, name in SKIP or bool(label)))
    rest = html[pos:]
    out.append(link_text(rest) if not any(skip for _, skip in stack) else rest)
    return "".join(out), made, unresolved


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
    html, made, unresolved = link_references(html)

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
          f"{made['subject']} subject and {made['need item']} need-item references linked")
    if unresolved:
        print(f"  not linked (no such id in this page): {sorted(set(unresolved))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    raise SystemExit(build(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])))
