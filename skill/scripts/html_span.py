"""Tag spans in the QA-pass HTML dialect, as offsets into the original text.

carry.py moves messages byte for byte, and build.py links words only in real text.
Both need to know where a tag ends. A '>' inside an attribute, a '</div>' inside a
comment, and the inside of a <pre>, <script> or <style> are not tags. The pages are
hand-written: tags are ASCII, attributes are quoted.

Nothing here re-serialises the page. Callers slice the original string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RAW = {"script", "style", "pre", "textarea", "title"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_NAME = re.compile(r"([A-Za-z][\w:-]*)")
_ATTR = re.compile(r"""\b([A-Za-z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


@dataclass(frozen=True)
class Tag:
    start: int
    end: int  # just past '>'
    closing: bool
    name: str
    attrs: str
    self_closing: bool


def attr(attrs: str, name: str) -> str | None:
    """The value of one attribute, quotes removed. None when it is absent."""
    want = name.lower()
    for found in _ATTR.finditer(attrs):
        if found.group(1).lower() == want:
            return found.group(2) if found.group(2) is not None else found.group(3)
    return None


def classes(attrs: str) -> set[str]:
    raw = attr(attrs, "class")
    return set(raw.split()) if raw else set()


def _find_gt(text: str, i: int) -> int | None:
    quote = ""
    for k in range(i + 1, len(text)):
        c = text[k]
        if quote:
            if c == quote:
                quote = ""
            continue
        if c in "\"'":
            quote = c
            continue
        if c == ">":
            return k
    return None


def parse_tag(text: str, i: int) -> Tag | None:
    """The tag that opens at text[i] == '<', or None when that '<' is not a tag."""
    if i >= len(text) or text[i] != "<":
        return None
    gt = _find_gt(text, i)
    if gt is None:
        return None
    body = text[i + 1:gt]
    closing = body.startswith("/")
    rest = body[1:] if closing else body
    name_match = _NAME.match(rest)
    if not name_match:
        return None
    name = name_match.group(1).lower()
    attrs = rest[name_match.end():]
    self_closing = not closing and (name in VOID or attrs.rstrip().endswith("/"))
    return Tag(i, gt + 1, closing, name, attrs, self_closing)


def _raw_end(text: str, i: int) -> int | None:
    """Index just past a <pre>, <script>, <style>, <textarea> or <title> block, else None.

    The inside is opaque: a diagram or a script may contain the characters '</div>'.
    """
    tag = parse_tag(text, i)
    if tag is None or tag.closing or tag.name not in RAW:
        return None
    close = re.search(rf"</{tag.name}\s*>", text[tag.end:], re.I)
    return len(text) if close is None else tag.end + close.end()


def scan(text: str, start: int = 0):
    """Yield (kind, start, end, tag).

    kind is 'text' (linkable prose), 'copy' (comment, {{…}} placeholder, or a raw block,
    kept whole) or 'tag'. tag is a Tag for kind 'tag', else None.
    """
    i, n = start, len(text)
    while i < n:
        if text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            if end < 0:
                yield ("text", i, n, None)
                return
            yield ("copy", i, end + 3, None)
            i = end + 3
            continue
        if text.startswith("{{", i):
            end = text.find("}}", i + 2)
            if end < 0:
                yield ("text", i, n, None)
                return
            yield ("copy", i, end + 2, None)
            i = end + 2
            continue
        if text[i] == "<":
            raw = _raw_end(text, i)
            if raw is not None:
                yield ("copy", i, raw, None)
                i = raw
                continue
            tag = parse_tag(text, i)
            if tag is not None:
                yield ("tag", tag.start, tag.end, tag)
                i = tag.end
                continue
        j = i + 1
        while j < n and text[j] != "<" and not text.startswith("{{", j):
            j += 1
        yield ("text", i, j, None)
        i = j


def element_end(text: str, start: int) -> int:
    """Index just past the element that opens at `start`.

    Void and self-closing tags end at their own tag. Nested tags of the same name count.
    A comment, a raw block, or a quoted '>' does not. A <pre> or <script> is one span:
    the characters '</div>' inside it are not tags.
    """
    raw = _raw_end(text, start)
    if raw is not None:
        return raw
    tag = parse_tag(text, start)
    if tag is None or tag.closing:
        raise ValueError(f"no opening tag at offset {start}")
    if tag.self_closing:
        return tag.end
    depth = 1
    for kind, _a, _b, inner in scan(text, tag.end):
        if kind != "tag" or inner is None or inner.name != tag.name:
            continue
        if inner.closing:
            depth -= 1
            if depth == 0:
                return inner.end
        elif not inner.self_closing:
            depth += 1
    raise ValueError(f"unbalanced <{tag.name}> at offset {start}")


_MSG_ID_PASS = re.compile(r"-(\d+)[ua]$")


def _figure_pass(attrs: str) -> int | None | bool:
    """For a <div>'s attributes: the pass of a .msg (its data-pass, or the pass in its id), None for a .msg
    with no pass, False for a div that is not a message."""
    if "msg" not in classes(attrs):
        return False
    own = attr(attrs, "data-pass")
    if own and own.isdigit():
        return int(own)
    found = _MSG_ID_PASS.search(attr(attrs, "id") or "")
    return int(found.group(1)) if found else None


def figure_labels(text: str, current: int | None) -> list[tuple[Tag, str]]:
    """Every <figure> opening tag with its label "P.K", in page order. A figure that has data-fig keeps it.
    Otherwise P is the pass of the innermost .msg holding it (the page's pass outside messages) and K its rank
    among pass P's figures, skipping any K a data-fig already took. carry.py stamps the labels into the source
    it carries from, so a figure keeps its number in every later pass, even when other figures are dropped."""
    found: list[tuple[Tag, str | int]] = []
    divs: list[int | None | bool] = []
    taken: dict[int, set[int]] = {}
    for kind, _start, _end, tag in scan(text):
        if kind != "tag" or tag is None:
            continue
        if tag.name == "div":
            if tag.closing:
                if divs:
                    divs.pop()
            elif not tag.self_closing:
                divs.append(_figure_pass(tag.attrs))
        elif tag.name == "figure" and not tag.closing:
            own = attr(tag.attrs, "data-fig")
            if own:
                p, _, k = own.partition(".")
                if p.isdigit() and k.isdigit():
                    taken.setdefault(int(p), set()).add(int(k))
                found.append((tag, own))
            else:
                page = next((d for d in reversed(divs) if d is not False and d is not None), current)
                found.append((tag, page or 0))
    rank: dict[int, int] = {}
    out: list[tuple[Tag, str]] = []
    for tag, label in found:
        if isinstance(label, str):
            out.append((tag, label))
            continue
        k = rank.get(label, 0) + 1
        while k in taken.get(label, set()):
            k += 1
        rank[label] = k
        taken.setdefault(label, set()).add(k)
        out.append((tag, f"{label}.{k}"))
    return out


def stamp_figures(text: str, current: int | None) -> str:
    """The same text with data-fig="P.K" on every <figure> that has none (see figure_labels)."""
    for tag, label in reversed(figure_labels(text, current)):
        if attr(tag.attrs, "data-fig") is None:
            text = text[:tag.end - 1] + f' data-fig="{label}"' + text[tag.end - 1:]
    return text
