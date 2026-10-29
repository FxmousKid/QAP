"""The tree and the search index, reused while the vault is unchanged.

`qap serve` is asked for the tree on each dashboard load and for the search index
the first time search opens. Both walk the content root and read page heads. On a
vault of about 600 passes that walk was about 20 ms the first time and about 12 ms
once the page-head cache was warm; the stamp below is a few milliseconds and does
not read the files.

The stamp is the path, mtime and size of every html, markdown and json file. Images
are not in it: they do not change the tree or the index. A write through the
dashboard, a `qap` command in another process, or a git pull changes a mtime, and
the next request rebuilds. The cached objects are shared, so callers must not
mutate them.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from . import layout as L
from . import search

_LOCK = threading.Lock()
_SLOTS: dict[str, dict] = {}
_STAMPED = (".html", ".md", ".json")


def content_stamp(root: Path) -> tuple:
    """What the tree and the search index are built from, in an order that compares equal."""
    root = root.resolve()
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != ".git" and not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            if name.startswith(".") or not name.endswith(_STAMPED):
                continue
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            rows.append((full.relative_to(root).as_posix(), st.st_mtime_ns, st.st_size))
    rows.sort()
    return tuple(rows)


def _cached(root: Path, kind: str, build):
    root = root.resolve()
    key = str(root)
    stamp = content_stamp(root)
    with _LOCK:
        slot = _SLOTS.get(key)
        if slot and slot["stamp"] == stamp and kind in slot:
            return slot[kind]
    value = build()
    if content_stamp(root) != stamp:
        return value  # the vault moved while it was read: answer this once, do not keep it
    with _LOCK:
        slot = _SLOTS.get(key)
        if slot is None or slot["stamp"] != stamp:
            slot = {"stamp": stamp}
            _SLOTS[key] = slot
        slot[kind] = value
        return value


def tree(root: Path) -> dict:
    return _cached(root, "tree", lambda: L.tree(root))


def search_index(root: Path) -> dict:
    return _cached(root, "search", lambda: search.build(root))
