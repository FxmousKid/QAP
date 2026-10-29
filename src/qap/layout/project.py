"""projects.json. A project is a box on the home screen, not a directory.

A top-level folder or subject joins one with "project": "<id>" in its own manifest.
One without that key belongs to the default. assign_project moves a nested item up to
the top level first, then writes the field. Nothing else moves on disk, so a tree
without projects.json reads exactly as before.
"""
from __future__ import annotations

import re
from pathlib import Path

from .paths import (
    FOLDER_FILE, PROJECTS_FILE, PROJECT_ID, SUBJECT_FILE, LayoutError, abs_path, clean_rel, is_subject_dir,
    pretty, read_json, write_json,
)
from .read import find_project, folder_node


def read_projects(root: Path) -> dict:
    """{default, projects: [{id, title, icon, color}]} from <root>/projects.json; no file means no projects.
    Entries with a bad id are skipped; a default that names no project means none."""
    data = read_json(root / PROJECTS_FILE)
    out, seen = [], set()
    for p in data.get("projects") or []:
        pid = str(p.get("id") or "") if isinstance(p, dict) else ""
        if PROJECT_ID.match(pid) and pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "title": p.get("title") or pretty(pid), "icon": p.get("icon") or "",
                        "color": p.get("color") or ""})
    default = data.get("default") if data.get("default") in seen else None
    return {"default": default, "projects": out}


def _write_projects(root: Path, registry: dict) -> None:
    write_json(root / PROJECTS_FILE, {"default": registry["default"],
                                      "projects": [{k: v for k, v in p.items() if v} for p in registry["projects"]]})


def _manifest(path: Path) -> Path:
    return path / (SUBJECT_FILE if is_subject_dir(path) else FOLDER_FILE)


def _project_of(root: Path, node: dict, registry: dict) -> str:
    """The project of a top-level folder or subject: its own "project" key when it names a project, else the
    default ('' when the tree has no projects)."""
    if not registry["projects"]:
        return ""
    own = read_json(_manifest(abs_path(root, node["path"]))).get("project")
    ids = {p["id"] for p in registry["projects"]}
    return own if own in ids else (registry["default"] or "")


def project_node(entry: dict, registry: dict, top: list[dict]) -> dict:
    members = [c for c in top if c.get("project") == entry["id"]]
    return {
        "kind": "project",
        "id": entry["id"],
        "name": entry["id"],
        "path": "@" + entry["id"],
        "title": entry["title"],
        "icon": entry["icon"],
        "color": entry["color"],
        "default": registry["default"] == entry["id"],
        "members": [c["path"] for c in members],
        "families": sum(1 for c in members if c["kind"] == "folder"),
        "subjects": sum(c["subjects"] if c["kind"] == "folder" else 1 for c in members),
        "updated": max((c["updated"] for c in members if c["updated"]), default=""),
    }


def _pin_default(root: Path, registry: dict) -> None:
    """Before the default project changes: write "project" into every top-level item that belongs to the old
    default without saying so, so that it stays there. The default then only decides where new folders go."""
    old = registry["default"]
    if not old:
        return
    for child in folder_node(root, root, False)["children"]:
        manifest = _manifest(abs_path(root, child["path"]))
        meta = read_json(manifest)
        if meta.get("project") not in {p["id"] for p in registry["projects"]}:
            meta["project"] = old
            if manifest.name == SUBJECT_FILE and "title" not in meta:
                meta["title"] = pretty(child["name"])
            write_json(manifest, meta)


def project_id(text: str) -> str:
    pid = re.sub(r"[^a-z0-9._-]+", "-", (text or "").strip().lower()).strip("-.")[:40]
    if not PROJECT_ID.match(pid):
        raise LayoutError(f"bad project id {text!r} (lower-case letters, digits, '.', '_', '-')")
    return pid


def make_project(root: Path, pid: str | None = None, title: str | None = None, icon: str | None = None,
                 color: str | None = None, default: bool = False) -> dict:
    """Add a project to projects.json. The first project becomes the default, so the folders already there (none
    of which names a project) all land in it: creating "work" first is the whole migration of an existing tree."""
    if not root.is_dir():
        raise LayoutError(f"content root {root} does not exist")
    pid = project_id(pid or title or "")
    registry = read_projects(root)
    if any(p["id"] == pid for p in registry["projects"]):
        raise LayoutError(f"project @{pid} already exists")
    registry["projects"].append({"id": pid, "title": title or pretty(pid), "icon": icon or "", "color": color or ""})
    if default or not registry["default"]:
        _pin_default(root, registry)
        registry["default"] = pid
    _write_projects(root, registry)
    return find_project(root, "@" + pid)


def set_project_meta(root: Path, ref: str, title: str | None = None, icon: str | None = None,
                     color: str | None = None, default: bool | None = None) -> dict:
    """Change a project's title, icon or colour (None leaves a field, '' clears icon or colour), or make it the
    default."""
    pid = find_project(root, ref)["id"]
    registry = read_projects(root)
    entry = next(p for p in registry["projects"] if p["id"] == pid)
    if title is not None and title.strip():
        entry["title"] = title.strip()
    for key, value in (("icon", icon), ("color", color)):
        if value is not None:
            entry[key] = value
    if default and registry["default"] != pid:
        _pin_default(root, registry)
        registry["default"] = pid
    _write_projects(root, registry)
    return find_project(root, "@" + pid)


def assign_project(root: Path, rel: str, ref: str) -> dict:
    """Put a folder or subject in a project. One below the top level moves to the top level first (qap.move:
    symlinks re-pointed), since a project holds top-level items. Writes "project" in the item's manifest."""
    # write.py imports _check_top from this file, so move is imported when the function runs.
    from .write import move

    target = find_project(root, ref)
    rel = clean_rel(rel)
    if not rel:
        raise LayoutError("give the folder or subject to put in the project")
    path = abs_path(root, rel)
    if not path.is_dir():
        raise LayoutError(f"{rel} does not exist")
    registry = read_projects(root)
    moved = None
    if "/" in rel:
        moved = move(root, rel, "")
        came_from = rel.rsplit("/", 1)[0]
        rel, path = moved["path"], abs_path(root, moved["path"])
    manifest = _manifest(path)
    meta = read_json(manifest)
    before = _project_of(root, {"path": rel}, registry)
    if not moved:
        came_from = "@" + before if before else ""
        if meta.get("project") == target["id"]:
            raise LayoutError(f"{rel} is already in {target['title']}")
    meta["project"] = target["id"]
    if manifest.name == SUBJECT_FILE and "title" not in meta:
        meta["title"] = pretty(path.name)
    write_json(manifest, meta)
    return {"from": came_from, "path": rel, "project": target["id"], "relinked": moved["relinked"] if moved else []}


def remove_project(root: Path, ref: str) -> dict:
    """Delete an empty project from projects.json (its folders are never touched: move them out first)."""
    node = find_project(root, ref)
    if node["members"]:
        raise LayoutError(f"{node['title']} still holds {', '.join(node['members'][:5])}; move them to another "
                          f"project first (`qap project move <folder> <project>`)")
    registry = read_projects(root)
    registry["projects"] = [p for p in registry["projects"] if p["id"] != node["id"]]
    if registry["default"] == node["id"]:
        registry["default"] = registry["projects"][0]["id"] if registry["projects"] else None
    _write_projects(root, registry)
    return {"path": node["path"]}


def _check_top(root: Path, rel: str, ref: str | None) -> str | None:
    """Before make_folder / make_subject with a project: the id the new top-level item will join, or None
    (no project asked, or the top-level folder exists already and is in that project: nothing to write).
    An existing top-level folder in another project is refused, before anything is created."""
    if not ref:
        return None
    pid = find_project(root, ref)["id"]
    top = rel.split("/")[0]
    if not abs_path(root, top).exists():
        return pid
    have = _project_of(root, {"path": top}, read_projects(root))
    if have != pid:
        raise LayoutError(f"{top} is in project @{have or '-'}, not @{pid} "
                          f"(move it first: `qap project move {top} {pid}`)")
    return None


def _claim_top(root: Path, rel: str, pid: str | None) -> None:
    """After the create: the new top-level item joins the project _check_top returned."""
    if not pid:
        return
    manifest = _manifest(abs_path(root, rel.split("/")[0]))
    meta = read_json(manifest)
    meta["project"] = pid
    write_json(manifest, meta)
