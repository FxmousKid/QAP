"""The passes inside one subject folder: which files are pages, their numbers, titles, and the next pass.

File names (as the skill writes them):
  QA-PASS-3.src.html     the source of pass 3 (edited by hand or by carry.py)
  QA-PASS-3.html         the built page (what the reader opens)
  QA-PASS-42-org-units.html, QA-PASS.md, QA-PASS-B.md   older or odd names: still listed
  QA-PASS-1.msg.src.html  an intermediate source with a tag: counted for numbering, never listed as a page
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

PASS_FILE = re.compile(r"^QA-PASS(?:-(?P<n>\d+))?(?P<tag>[-.][^/]*?)??\.(?P<ext>src\.html|html|md)$")
H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)
TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)
QA_PROJECT = re.compile(r'<meta\s+name="qa-project"\s+content="([^"]*)"', re.I)
TAGS = re.compile(r"<[^>]+>")


def parse_name(name: str) -> dict | None:
    """{n, tag, ext} for a QA pass file name, None for any other file."""
    m = PASS_FILE.match(name)
    if not m:
        return None
    return {"n": int(m.group("n")) if m.group("n") else None, "tag": m.group("tag") or "", "ext": m.group("ext")}


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub("", fragment))).strip()


@lru_cache(maxsize=4096)
def _head_info(path: str, mtime_ns: int, size: int) -> tuple[str, str]:
    """(title, qa_project) read from the first 256 KB of a page; cached per file version."""
    try:
        with open(path, "rb") as f:
            head = f.read(256 * 1024).decode("utf-8", "replace")
    except OSError:
        return "", ""
    if path.endswith(".md"):
        m = re.search(r"^#\s+(.+)$", head, re.M)
        return (m.group(1).strip() if m else ""), ""
    m = H1.search(head) or TITLE.search(head)
    project = QA_PROJECT.search(head)
    return (_clean(m.group(1)) if m else ""), (project.group(1) if project else "")


def head_info(path: Path) -> tuple[str, str]:
    st = path.stat()
    return _head_info(str(path), st.st_mtime_ns, st.st_size)


def _label(name: str, ext: str) -> str:
    stem = name[: -len(ext) - 1]
    return stem[len("QA-PASS-"):] if stem.startswith("QA-PASS-") else "pass"


def list_passes(subject_dir: Path, with_titles: bool = True) -> list[dict]:
    """Every readable page of a subject (built .html or .md), oldest first.

    Each entry: n (int or None), label ("3", "42-org-units"), file, src (the matching .src.html or None),
    kind ("html" | "md"), mtime (ISO), title. Sources with no built page yet are not listed (see next_pass).
    """
    try:
        names = sorted(p.name for p in subject_dir.iterdir() if p.is_file())
    except OSError:
        return []
    found = {name: parse_name(name) for name in names}
    sources = {(i["n"], i["tag"]): name for name, i in found.items() if i and i["ext"] == "src.html"}
    out = []
    for name, info in found.items():
        if not info or info["ext"] == "src.html":
            continue
        path = subject_dir / name
        st = path.stat()
        entry = {
            "n": info["n"],
            "label": _label(name, info["ext"]),
            "file": name,
            "src": sources.get((info["n"], info["tag"])),
            "kind": "md" if info["ext"] == "md" else "html",
            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
            "size": st.st_size,
        }
        if with_titles:
            entry["title"] = head_info(path)[0]
        out.append(entry)
    # Numbered passes in order; a plain name before its tagged variants; .html before .md for one number.
    out.sort(key=lambda e: (e["n"] if e["n"] is not None else 0, e["label"] != str(e["n"]), e["kind"], e["file"]))
    return out


def latest(passes: list[dict]) -> dict | None:
    return passes[-1] if passes else None


def numbers_used(subject_dir: Path) -> list[int]:
    """Every pass number present in the folder, sources and tagged files included."""
    used = set()
    for p in subject_dir.iterdir() if subject_dir.is_dir() else []:
        info = parse_name(p.name)
        if info and info["n"] is not None:
            used.add(info["n"])
    return sorted(used)


def latest_source(subject_dir: Path) -> Path | None:
    """The source to carry from: the highest-numbered untagged QA-PASS-N.src.html."""
    best = None
    for p in subject_dir.iterdir() if subject_dir.is_dir() else []:
        info = parse_name(p.name)
        if info and info["ext"] == "src.html" and info["n"] is not None and not info["tag"]:
            if best is None or info["n"] > best[0]:
                best = (info["n"], p)
    return best[1] if best else None


def next_pass(subject_dir: Path) -> dict:
    """The number and file names of the pass to write next, plus the source it would carry from."""
    used = numbers_used(subject_dir)
    n = (used[-1] + 1) if used else 1
    prev = latest_source(subject_dir)
    return {
        "n": n,
        "src": str(subject_dir / f"QA-PASS-{n}.src.html"),
        "html": str(subject_dir / f"QA-PASS-{n}.html"),
        "img": str(subject_dir / "img"),
        "carry_from": str(prev) if prev else None,
    }


def source_for(subject_dir: Path, n: int | None) -> Path:
    """The source of pass n (latest untagged source when n is None)."""
    if n is None:
        src = latest_source(subject_dir)
        if not src:
            raise LookupError(f"no QA-PASS-N.src.html in {subject_dir}")
        return src
    src = subject_dir / f"QA-PASS-{n}.src.html"
    if not src.is_file():
        raise LookupError(f"no source for pass {n}: {src} does not exist")
    return src


def built_for(src: Path) -> Path:
    return src.with_name(src.name[: -len(".src.html")] + ".html")


def page_project(path: Path) -> str:
    """The <meta name="qa-project"> of a page or source ('' when absent)."""
    try:
        return head_info(path)[1]
    except OSError:
        return ""
