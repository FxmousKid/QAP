#!/usr/bin/env python3
"""Start the next QA pass from the previous one: fold each subject's latest round into its thread.

Usage:
  python3 carry.py QA-PASS-1.src.html QA-PASS-2.src.html --pass 2 [--ai "claude|Claude|Opus 5.5"]
                   [--skip p10,p12] [--stars stars.txt]

For every subject section (an h2 whose id starts with "p") that holds open .msg blocks:
  - the open .msg blocks (the user's latest words and the AI's answer) move, byte for byte, to the end of the
    section's details.earlier fold (created if missing). Their ids, figures, tables, lists and decision boxes
    stay as they were, so stars and deep links keep working and the fold shows the original formatting;
  - two placeholders are added for the new round: the user's reply (id <subject>-<pass>u) and the answer
    (<subject>-<pass>a). They contain {{TODO:…}}, so build.py refuses the page until they are filled or deleted.
Subjects in --skip keep their last round open (settled subjects that get no new round).
--stars takes the text of the stars dialog's "Copy list" (a file, or "-" for stdin): its message ids
(#p3-2a) are written into the new pass as a seed, which the page merges once into the browser's stars.
That carries the stars even when the browser keeps them per file (some viewers do).
Everything else (header, lede, closing sections) is copied unchanged: rewrite those by hand.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

H2 = re.compile(r'<h2\b[^>]*\bid="([^"]+)"[^>]*>')
MSG = re.compile(r'<div class="msg (?:user|ai)\b[^"]*"')
DETAILS_OPEN = re.compile(r'<details class="earlier"[^>]*>')


def _match_end(text: str, start: int, tag: str) -> int:
    """Index just past the element that opens at `start`, counting nested tags of the same name."""
    pattern = re.compile(rf"<{tag}\b|</{tag}>")
    depth = 0
    for m in pattern.finditer(text, start):
        depth += 1 if not m.group(0).startswith("</") else -1
        if depth == 0:
            return m.end()
    raise SystemExit(f"carry: unbalanced <{tag}> starting at offset {start}")


def carry_section(section: str, sid: str, n: int, ai: str) -> str:
    fold = DETAILS_OPEN.search(section)
    fold_span = (fold.start(), _match_end(section, fold.start(), "details")) if fold else None
    spans = []
    for m in MSG.finditer(section):
        if fold_span and fold_span[0] <= m.start() < fold_span[1]:
            continue
        if spans and m.start() < spans[-1][1]:
            continue  # nested inside the previous message
        spans.append((m.start(), _match_end(section, m.start(), "div")))
    if not spans:
        return section
    moved = "\n".join(section[a:b] for a, b in spans)
    rest = section
    for a, b in reversed(spans):
        rest = rest[:a] + rest[b:]
    placeholders = (
        f'<div class="msg user" id="{sid}-{n}u" data-pass="{n}"><div class="who">Me</div>\n'
        f"  <p>“{{{{TODO:the user's reply, verbatim}}}}”</p>\n</div>\n"
        f'<div class="msg ai" id="{sid}-{n}a" data-pass="{n}"><div class="who">{{{{AI:{ai}}}}}</div>\n'
        f"  <p>{{{{TODO:your answer}}}}</p>\n</div>\n"
    )
    fold = DETAILS_OPEN.search(rest)
    if fold:
        end = _match_end(rest, fold.start(), "details")
        close = rest.rfind("</details>", fold.start(), end)
        rest = rest[:close] + moved + "\n" + rest[close:end] + "\n" + placeholders + rest[end:].lstrip("\n")
        rest = re.sub(r"(<summary>Earlier in this thread)\s*·\s*\d+\s+messages?(</summary>)", r"\1\2", rest)
    else:
        h2 = H2.search(rest)
        assert h2 is not None, "a subject section starts with its h2"
        close_h2 = rest.find("</h2>", h2.end()) + len("</h2>")
        after = close_h2
        chips = re.compile(r'\s*<span class="chip[^"]*">[^<]*</span>')
        while (m := chips.match(rest, after)):
            after = m.end()
        block = (f'\n<details class="earlier"><summary>Earlier in this thread</summary>\n{moved}\n</details>\n'
                 + placeholders)
        rest = rest[:after] + block + rest[after:].lstrip("\n")
    return rest


STAR_ID = re.compile(r"#?\b(p\d+-\d+[ua])\b")


def seed_stars(text: str, source: str) -> tuple[str, list[str]] | list:
    """Write the message ids of a pasted "Copy list" into <meta name="qa-stars-seed">, merged with any seed
    already there. The page adds them to the browser's stars once (an unstar sticks)."""
    raw = sys.stdin.read() if source == "-" else pathlib.Path(source).read_text(encoding="utf-8")
    ids = sorted(set(STAR_ID.findall(raw)))
    if not ids:
        return []
    old = re.search(r'<meta name="qa-stars-seed" content="([^"]*)">', text)
    merged = sorted(set(ids) | set(filter(None, (old.group(1) if old else "").split(","))))
    tag = f'<meta name="qa-stars-seed" content="{",".join(merged)}">'
    if old:
        text = text.replace(old.group(0), tag)
    else:
        text = re.sub(r'(<meta name="qa-pass" content="\d+">)', lambda m: m.group(1) + "\n" + tag, text, count=1)
    return text, ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prev")
    ap.add_argument("next")
    ap.add_argument("--pass", dest="n", type=int, required=True, help="number of the new pass")
    ap.add_argument("--ai", default="claude|Claude|Opus 5.5", help='vendor|Name|Model of the AI writing the pass')
    ap.add_argument("--skip", default="", help="comma-separated subject ids that get no new round")
    ap.add_argument("--stars", default="", help='file holding the "Copy list" text of the stars dialog ("-": stdin)')
    ns = ap.parse_args()
    src = pathlib.Path(ns.prev).read_text(encoding="utf-8")
    skip = {s.strip() for s in ns.skip.split(",") if s.strip()}
    heads = list(H2.finditer(src))
    out, last, carried = [], 0, []
    for i, h in enumerate(heads):
        start = h.start()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(src)
        sid = h.group(1)
        out.append(src[last:start])
        section = src[start:end]
        if sid.startswith("p") and sid not in skip:
            new = carry_section(section, sid, ns.n, ns.ai)
            if new != section:
                carried.append(sid)
            section = new
        out.append(section)
        last = end
    out.append(src[last:])
    text = "".join(out)
    text = re.sub(r'(<meta name="qa-pass" content=")\d+(")', rf"\g<1>{ns.n}\2", text)
    seeded = seed_stars(text, ns.stars) if ns.stars else []
    if seeded:
        text = seeded[0]
    pathlib.Path(ns.next).write_text(text, encoding="utf-8")
    print(f"{ns.next}: carried {len(carried)} subjects into their folds ({', '.join(carried)}); "
          f"skipped {sorted(skip) or 'none'}. Fill every {{{{TODO:…}}}} or delete the placeholder, "
          f"then rewrite the header, lede and closing sections."
          + (f" Seeded {len(seeded[1])} star(s): {', '.join(seeded[1])}." if seeded else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
