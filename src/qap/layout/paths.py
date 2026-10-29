"""A legal relative path, and reading or writing one json manifest.

Paths in and out of qap are POSIX paths relative to the content root
("coach/v3/interaction"). "" is the root. A directory is a subject when it holds
subject.json or, without one, a QA pass file.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .. import passes as P

SUBJECT_FILE = "subject.json"
FOLDER_FILE = "folder.json"
PROJECTS_FILE = "projects.json"
RESERVED = {"img", "__pycache__", "node_modules"}
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +-]{0,79}$")
PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


class LayoutError(Exception):
    """A refused operation; the message says why, in words a user can act on."""


# ---------------------------------------------------------------------------- paths and manifests

def clean_rel(rel: str | None) -> str:
    """Normalise a relative path ('/coach//v3/' -> 'coach/v3') and refuse anything outside the root."""
    rel = (rel or "").strip().strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    for part in parts:
        if part == ".." or part.startswith(".") or part in RESERVED or not SEGMENT.match(part):
            raise LayoutError(f"bad path segment {part!r} in {rel!r} (letters, digits, '.', '_', '-', '+', space; "
                              f"not hidden, not {sorted(RESERVED)})")
    return "/".join(parts)


def abs_path(root: Path, rel: str) -> Path:
    return root / clean_rel(rel) if rel else root


def rel_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix() if path.resolve() != root.resolve() else ""


def slug(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._+-]+", "-", title.strip()).strip("-.").lower()
    return s[:60] or "folder"


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise LayoutError(f"cannot read {path}: {e}")
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def is_subject_dir(path: Path) -> bool:
    if (path / SUBJECT_FILE).is_file():
        return True
    try:
        return any(P.parse_name(p.name) for p in path.iterdir() if p.is_file())
    except OSError:
        return False


def _visible_dirs(path: Path) -> list[Path]:
    try:
        entries = sorted(path.iterdir())
    except OSError:
        return []
    return [p for p in entries if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
            and p.name not in RESERVED]


def pretty(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip() or name
