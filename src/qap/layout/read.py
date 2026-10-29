"""The tree the dashboard and `qap list` show, and finding a thing by what someone typed.

tree() walks the folders and attaches each top-level item's project. resolve() finds a
folder or a subject; a ref that starts with "@", or kind "project", finds a project.
"""
from __future__ import annotations

from pathlib import Path

from .. import passes as P
from .paths import (
    FOLDER_FILE, SUBJECT_FILE, LayoutError, _visible_dirs, is_subject_dir, pretty, read_json, rel_path,
)

def subject_node(root: Path, path: Path, with_titles: bool = True) -> dict:
    meta = read_json(path / SUBJECT_FILE)
    passes = P.list_passes(path, with_titles=with_titles)
    last = passes[-1] if passes else None
    qa_project = meta.get("qa_project") or (P.page_project(path / last["file"]) if last else "")
    return {
        "kind": "subject",
        "name": path.name,
        "path": rel_path(root, path),
        "title": meta.get("title") or pretty(path.name),
        "icon": meta.get("icon") or "",
        "color": meta.get("color") or "",
        "qa_project": qa_project,
        "sources": meta.get("sources") or [],
        "created": meta.get("created") or "",
        "implicit": not (path / SUBJECT_FILE).is_file(),
        "passes": passes,
        "count": len(passes),
        "latest": last["label"] if last else None,
        "updated": max((p["mtime"] for p in passes), default=""),
    }


def folder_node(root: Path, path: Path, with_titles: bool = True) -> dict:
    meta = read_json(path / FOLDER_FILE) if path != root else read_json(root / FOLDER_FILE)
    children = []
    for child in _visible_dirs(path):
        if is_subject_dir(child):
            children.append(subject_node(root, child, with_titles))
        else:
            children.append(folder_node(root, child, with_titles))
    order = meta.get("order")
    rank = {name: i for i, name in enumerate(order)} if isinstance(order, list) else {}

    def key(c: dict):
        own = c.get("order")
        return (rank.get(c["name"], len(rank)),
                own if isinstance(own, (int, float)) else 1e9,
                c["kind"] != "folder",
                c["title"].casefold())

    children.sort(key=key)
    subjects = sum(c["subjects"] if c["kind"] == "folder" else 1 for c in children)
    updated = max((c["updated"] for c in children if c["updated"]), default="")
    return {
        "kind": "folder",
        "name": path.name if path != root else "",
        "path": rel_path(root, path),
        "title": meta.get("title") or (pretty(path.name) if path != root else "QA passes"),
        "icon": meta.get("icon") or "",
        "color": meta.get("color") or "",
        "order": order if isinstance(order, (int, float)) else None,
        "children": children,
        "subjects": subjects,
        "updated": updated,
    }


def tree(root: Path, with_titles: bool = True) -> dict:
    """The root folder node. Its top-level children carry "project" (their project's id, "" for none) and the
    root carries "projects", the project nodes in projects.json order ([] when the tree has no projects)."""
    # project.py imports find_project and folder_node from this file, so this import stays inside the call.
    from .project import _project_of, project_node, read_projects

    if not root.is_dir():
        raise LayoutError(f"content root {root} does not exist (set it with `qap config content_root <path>`)")
    node = folder_node(root, root, with_titles)
    registry = read_projects(root)
    for child in node["children"]:
        child["project"] = _project_of(root, child, registry)
    node["projects"] = [project_node(p, registry, node["children"]) for p in registry["projects"]]
    return node


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def subjects(root: Path, with_titles: bool = False) -> list[dict]:
    return [n for n in walk(tree(root, with_titles)) if n["kind"] == "subject"]


def folders(root: Path) -> list[dict]:
    return [n for n in walk(tree(root, False)) if n["kind"] == "folder"]


def resolve(root: Path, ref: str, kind: str | None = None) -> dict:
    """Find a subject or folder from what a user types: its path, or (when unique) its directory name,
    its qa_project or its title, case-insensitive. kind: 'subject', 'folder' or None for either.
    "@<id>" (or kind 'project' with an id or a title) finds a project."""
    ref = (ref or "").strip()
    if ref.startswith("@") or kind == "project":
        if kind not in (None, "project"):
            raise LayoutError(f"{ref!r} is a project, not a {kind}")
        return find_project(root, ref)
    nodes = [n for n in walk(tree(root, False)) if kind is None or n["kind"] == kind]
    wanted = ref.strip("/")
    for n in nodes:
        if n["path"] == wanted:
            return n
    low = wanted.casefold()
    for field in ("name", "qa_project", "title"):
        hits = [n for n in nodes if (n.get(field) or "").casefold() == low and (field != "name" or n["path"])]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise LayoutError(f"{ref!r} matches several {kind or 'items'}: "
                              + ", ".join(h["path"] for h in hits) + " — give the path")
    hits = [n for n in nodes if n["path"] and low in n["path"].casefold()]
    if len(hits) == 1:
        return hits[0]
    what = kind or "subject or folder"
    if hits:
        raise LayoutError(f"{ref!r} matches several: {', '.join(h['path'] for h in hits)} — give the path")
    raise LayoutError(f"no {what} {ref!r} under {root} (see `qap list`)")


def projects(root: Path) -> list[dict]:
    return tree(root, False)["projects"]


def find_project(root: Path, ref: str) -> dict:
    """A project from "@id", "id" or its title (case-insensitive)."""
    want = (ref or "").strip().removeprefix("@").casefold()
    nodes = projects(root)
    if not nodes:
        raise LayoutError("no project yet (create one with `qap project new <id>`)")
    for field in ("id", "title"):
        hits = [p for p in nodes if p[field].casefold() == want]
        if len(hits) == 1:
            return hits[0]
    raise LayoutError(f"no project {ref!r}; projects: {', '.join('@' + p['id'] for p in nodes)}")
