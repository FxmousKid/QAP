"""The search index: one flat list of every project, folder, subject and pass, for GET /api/search.

The dashboard and the pass pages rank it in the browser (web/fuzzy.js), so typing never waits for the server.
Each item carries what its result card shows and where it opens:

  kind      "project" | "folder" | "subject" | "pass"
  title     the name on the card (a pass: its h1 without the "Q&A pass N —" prefix)
  name      directory name (project: its id) — the tile colour comes from it, as on the dashboard
  icon, color
  crumbs    the titles above it: project › folders (› subject, for a pass)
  href      the dashboard route ("#/authz/rbac?pass=3"); a matched section adds "&at=<its id>"
  project   its project's id ('' without projects)
  count, updated, and per kind: qa_project (subject); label, n, file, kicker, latest, sections (pass)

Titles come from the page heads (passes.head_info), sections and kickers from the sources (passes.outline); both
are cached per file version, so a request after the first one only stats files.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import layout as L, passes as P

PASS_PREFIX = re.compile(r"^\s*Q\s*&\s*A\s+pass\s+[\w.-]+\s*(?:[—–:]|-\s)\s*", re.I)


def pass_title(h1: str) -> str:
    """'Q&A pass 3 — the indexing plan' -> 'the indexing plan' (the card shows the number in its badge)."""
    rest = PASS_PREFIX.sub("", h1 or "", count=1).strip()
    return (rest[:1].upper() + rest[1:]) if rest else ""


def route(path: str, params: str = "") -> str:
    return "#/" + path + (("?" + params) if params else "")


def build(root: Path) -> dict:
    tree = L.tree(root, with_titles=True)
    projects = {p["id"]: p for p in tree["projects"]}
    items: list[dict] = []

    for p in tree["projects"]:
        items.append({"kind": "project", "key": p["path"], "title": p["title"], "name": p["id"], "path": p["path"],
                      "icon": p["icon"], "color": p["color"], "crumbs": [], "href": route(p["path"]),
                      "project": p["id"], "count": p["subjects"], "families": p["families"], "updated": p["updated"]})

    def visit(node: dict, crumbs: list[str], project: str) -> None:
        for child in node["children"]:
            pid = child.get("project", project) if node is tree else project
            above = crumbs if node is not tree else ([projects[pid]["title"]] if pid in projects else [])
            base = {"key": child["path"], "title": child["title"], "name": child["name"], "path": child["path"],
                    "icon": child["icon"], "color": child["color"], "crumbs": above, "href": route(child["path"]),
                    "project": pid, "updated": child["updated"]}
            if child["kind"] == "folder":
                items.append({"kind": "folder", **base, "count": child["subjects"]})
                visit(child, above + [child["title"]], pid)
                continue
            items.append({"kind": "subject", **base, "count": child["count"], "qa_project": child["qa_project"]})
            subject_dir = L.abs_path(root, child["path"])
            last = len(child["passes"]) - 1
            for i, entry in enumerate(child["passes"]):
                kicker, sections = P.outline(subject_dir, entry)
                items.append({
                    "kind": "pass", "key": f"{child['path']}#{entry['label']}",
                    "title": pass_title(entry.get("title", "")), "h1": entry.get("title", ""),
                    "name": child["name"], "path": child["path"], "icon": child["icon"], "color": child["color"],
                    "crumbs": above + [child["title"]], "project": pid,
                    "href": route(child["path"], "pass=" + quote(entry["label"], safe="")),
                    "label": entry["label"], "n": entry["n"], "file": entry["file"], "kicker": kicker,
                    "latest": i == last, "updated": entry["mtime"],
                    "sections": [{"id": sid, "num": num, "title": title} for sid, num, title in sections if title],
                })

    visit(tree, [], "")
    return {"ok": True, "root_title": tree["title"], "projects": len(tree["projects"]),
            "generated": datetime.now().astimezone().isoformat(timespec="seconds"), "items": items}
