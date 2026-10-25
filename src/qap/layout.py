"""The content tree: folders hold folders and subjects; a subject holds its passes.

    <content_root>/
      <folder>/                 any depth; optional folder.json {title, icon, order}
        <subject>/              subject.json {title, icon, qa_project, sources, created}
          QA-PASS-1.src.html, QA-PASS-1.html, …, img/

A directory is a subject when it holds subject.json (or, without one, QA-PASS files: an "implicit" subject).
Every other visible directory is a folder. Paths in and out of this module are POSIX paths relative to the
content root ("coach/v3/interaction"); "" is the root itself.

folder.json "order" is either a number (this folder's rank among its siblings) or a list of child names
(the order of this folder's children). Children not named in a list follow, folders first, then by title.

Every mutation the CLI and the dashboard make goes through the functions below (make_folder, make_subject,
move, set_meta, place), so both write the same manifests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from . import passes as P

SUBJECT_FILE = "subject.json"
FOLDER_FILE = "folder.json"
RESERVED = {"img", "__pycache__", "node_modules"}
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +-]{0,79}$")


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


# ---------------------------------------------------------------------------- reading the tree

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
    if not root.is_dir():
        raise LayoutError(f"content root {root} does not exist (set it with `qap config content_root <path>`)")
    return folder_node(root, root, with_titles)


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
    its qa_project or its title, case-insensitive. kind: 'subject', 'folder' or None for either."""
    ref = (ref or "").strip()
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


# ---------------------------------------------------------------------------- writing

def _require_folder(root: Path, rel: str) -> Path:
    path = abs_path(root, rel)
    if not path.is_dir():
        raise LayoutError(f"folder {rel or '/'} does not exist")
    if rel and is_subject_dir(path):
        raise LayoutError(f"{rel} is a subject, not a folder")
    return path


def make_folder(root: Path, rel: str, title: str | None = None, icon: str | None = None,
                parents: bool = True) -> dict:
    """Create a folder (and its missing parents); writes folder.json when a title or icon is given."""
    rel = clean_rel(rel)
    if not rel:
        raise LayoutError("give the folder a name")
    path = abs_path(root, rel)
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    if not parents:
        _require_folder(root, parent)
    else:
        for i, part in enumerate(rel.split("/")[:-1]):
            p = abs_path(root, "/".join(rel.split("/")[: i + 1]))
            if p.exists() and is_subject_dir(p):
                raise LayoutError(f"{rel_path(root, p)} is a subject; a folder cannot go inside it")
    if path.exists():
        raise LayoutError(f"{rel} already exists")
    path.mkdir(parents=True)
    if title or icon:
        meta = {k: v for k, v in (("title", title), ("icon", icon)) if v}
        write_json(path / FOLDER_FILE, meta)
    _order_add(root, parent, path.name)
    return folder_node(root, path, False)


def make_subject(root: Path, rel: str, title: str | None = None, icon: str | None = None,
                 qa_project: str | None = None, sources: list[str] | None = None) -> dict:
    """Create a subject folder with its subject.json (parent folders are created as needed)."""
    rel = clean_rel(rel)
    if not rel:
        raise LayoutError("give the subject a path, for example coach/v3/interaction")
    path = abs_path(root, rel)
    if (path / SUBJECT_FILE).exists():
        raise LayoutError(f"subject {rel} already exists")
    parts = rel.split("/")
    for i in range(1, len(parts)):
        p = abs_path(root, "/".join(parts[:i]))
        if p.exists() and is_subject_dir(p):
            raise LayoutError(f"{rel_path(root, p)} is a subject; a subject cannot go inside it")
    existed = path.exists()
    (path / "img").mkdir(parents=True, exist_ok=True)
    write_json(path / SUBJECT_FILE, {
        "title": title or pretty(path.name),
        "icon": icon or "",
        "qa_project": qa_project or path.name,
        "sources": list(sources or []),
        "created": date.today().isoformat(),
    })
    if not existed:
        _order_add(root, "/".join(parts[:-1]), path.name)
    return subject_node(root, path, False)


def set_meta(root: Path, rel: str, **fields) -> dict:
    """Update a folder's or subject's manifest (title, icon, color, qa_project, order). None leaves a field as is;
    '' clears it. The root folder's title and icon live in <root>/folder.json."""
    rel = clean_rel(rel)
    path = abs_path(root, rel)
    if not path.is_dir():
        raise LayoutError(f"{rel or '/'} does not exist")
    subject = bool(rel) and is_subject_dir(path)
    allowed = {"title", "icon", "color", "qa_project"} if subject else {"title", "icon", "color", "order"}
    bad = {k for k, v in fields.items() if v is not None} - allowed
    if bad:
        raise LayoutError(f"cannot set {sorted(bad)} on a {'subject' if subject else 'folder'}")
    manifest = path / (SUBJECT_FILE if subject else FOLDER_FILE)
    meta = read_json(manifest)
    for k, v in fields.items():
        if v is None:
            continue
        if v == "":
            meta.pop(k, None)
        else:
            meta[k] = v
    if subject and "title" not in meta:
        meta["title"] = pretty(path.name)
    write_json(manifest, meta)
    return subject_node(root, path, False) if subject else folder_node(root, path, False)


def _order_add(root: Path, parent_rel: str, name: str) -> None:
    manifest = abs_path(root, parent_rel) / FOLDER_FILE
    meta = read_json(manifest)
    if isinstance(meta.get("order"), list) and name not in meta["order"]:
        meta["order"].append(name)
        write_json(manifest, meta)


def _order_remove(root: Path, parent_rel: str, name: str) -> None:
    manifest = abs_path(root, parent_rel) / FOLDER_FILE
    meta = read_json(manifest)
    if isinstance(meta.get("order"), list) and name in meta["order"]:
        meta["order"].remove(name)
        write_json(manifest, meta)


def _subject_dirs_under(path: Path) -> list[Path]:
    if is_subject_dir(path):
        return [path]
    out = []
    for child in _visible_dirs(path):
        out.extend(_subject_dirs_under(child))
    return out


def _repoint(link: Path, olds: set[str], new_dir: Path) -> str | None:
    target = os.readlink(link)
    for old in olds:
        if target == old or target.startswith(old + os.sep):
            new_target = str(new_dir) + target[len(old):]
            tmp = link.with_name(link.name + ".qap-tmp")
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            os.symlink(new_target, tmp)
            os.replace(tmp, link)
            return f"{link} -> {new_target}"
    return None


def relink_sources(subject_dir: Path, old_dir: Path, old_real: Path | None = None) -> list[str]:
    """After a subject moved from old_dir to subject_dir: re-point the symlinks left at its old locations
    (subject.json sources). A source is either the symlink itself (an old choices/ folder or file) or a real
    folder holding per-file symlinks into the subject (RBAC/choices/QA-PASS-N.html)."""
    meta = read_json(subject_dir / SUBJECT_FILE)
    olds = {str(old_dir)} | ({str(old_real)} if old_real else set())
    done = []
    for src in meta.get("sources") or []:
        path = Path(src).expanduser()
        links = [path] if path.is_symlink() else (
            [p for p in sorted(path.iterdir()) if p.is_symlink()] if path.is_dir() else [])
        for link in links:
            line = _repoint(link, olds, subject_dir)
            if line:
                done.append(line)
    return done


def move(root: Path, src_rel: str, dest_rel: str) -> dict:
    """Move a subject or a folder. dest is an existing folder (the item goes inside it, keeping its name)
    or a new path whose parent folder exists (move and rename, like `mv`). Symlinks left at the subjects'
    old locations (subject.json sources) are re-pointed, and folder.json order lists follow."""
    src_rel, dest_rel = clean_rel(src_rel), clean_rel(dest_rel)
    if not src_rel:
        raise LayoutError("cannot move the content root")
    src = abs_path(root, src_rel)
    if not src.is_dir():
        raise LayoutError(f"{src_rel} does not exist")
    dest = abs_path(root, dest_rel)
    if dest.is_dir() and not (dest_rel and is_subject_dir(dest)):
        target = dest / src.name
        target_rel = f"{dest_rel}/{src.name}" if dest_rel else src.name
    else:
        if dest.exists():
            raise LayoutError(f"{dest_rel} already exists and is not a folder")
        parent_rel = dest_rel.rsplit("/", 1)[0] if "/" in dest_rel else ""
        _require_folder(root, parent_rel)
        target, target_rel = dest, dest_rel
    if target_rel == src_rel:
        raise LayoutError(f"{src_rel} is already in {dest_rel or 'the top level'}")
    if target.exists():
        raise LayoutError(f"{target_rel} already exists")
    if target_rel.startswith(src_rel + "/"):
        raise LayoutError(f"cannot move {src_rel} into itself")
    old_parent = src_rel.rsplit("/", 1)[0] if "/" in src_rel else ""
    new_parent = target_rel.rsplit("/", 1)[0] if "/" in target_rel else ""
    old_subjects = {p: (p.relative_to(src), p.resolve()) for p in _subject_dirs_under(src)}
    os.rename(src, target)
    relinked = []
    for old_dir, (inner, old_real) in old_subjects.items():
        relinked += relink_sources(target / inner, old_dir, old_real)
    _order_remove(root, old_parent, src.name)
    _order_add(root, new_parent, target.name)
    return {"from": src_rel, "path": target_rel, "relinked": relinked}


def place(root: Path, item: Path, subject_rel: str, link: bool | None = None, as_n: int | None = None,
          create: bool = False, title: str | None = None, icon: str | None = None, force: bool = False) -> dict:
    """Move a pass (a QA-PASS file) or a whole folder of passes (an old choices/ folder) into a subject.

    A file: moves it (and its built page when it is a source, and the other way round), renamed to pass
      as_n when given; a source's {{IMG:…}} images are copied into the subject's img/.
    A folder: moves everything it holds into the subject (img/ merged); a file already in the subject with
      the same name is refused unless identical (then the copy being placed is dropped) or force is set.
    link (default: on for a folder, off for a file) leaves a symlink at the old location, recorded in the
    subject's sources, so old links keep working. create makes the subject when it does not exist.
    """
    item = item.expanduser()
    if not item.exists():
        raise LayoutError(f"{item} does not exist")
    item = item.absolute()
    if item.is_symlink():
        raise LayoutError(f"{item} is a symlink (already placed?); give the real file or folder")
    subject_rel = clean_rel(subject_rel)
    subject_dir = abs_path(root, subject_rel)
    if link is None:
        link = item.is_dir()
    if not (subject_dir / SUBJECT_FILE).is_file():
        if not create:
            raise LayoutError(f"subject {subject_rel} does not exist (create it with `qap new-subject "
                              f"{subject_rel}` or pass --create)")
        project = ""
        pages = [item] if item.is_file() else sorted(item.glob("QA-PASS*.html"))
        for page in reversed(pages):
            project = P.page_project(page)
            if project:
                break
        make_subject(root, subject_rel, title=title, icon=icon, qa_project=project or None)
    if item.is_dir():
        if subject_dir.resolve() == item.resolve() or subject_dir.resolve().is_relative_to(item.resolve()):
            raise LayoutError("cannot place a folder into itself")
        moved = _merge_dir(item, subject_dir, force)
        try:
            item.rmdir()  # everything moved out; a leftover (a hidden file) keeps the folder
        except OSError:
            if link:
                raise LayoutError(f"{item} is not empty after the move; no symlink left there")
        pairs = [(item, subject_dir)]
    else:
        pairs = _place_file(item, subject_dir, as_n, force)
        moved = [str(new) for _, new in pairs]
    links = []
    if link:
        meta = read_json(subject_dir / SUBJECT_FILE)
        sources = meta.get("sources") or []
        for old, new in pairs:
            os.symlink(new, old)
            links.append(f"{old} -> {new}")
            if str(old) not in sources:
                sources.append(str(old))
        meta["sources"] = sources
        write_json(subject_dir / SUBJECT_FILE, meta)
    return {"subject": subject_rel, "moved": moved, "links": links}


def _same_file(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    return a.read_bytes() == b.read_bytes()


def _merge_dir(src: Path, dest: Path, force: bool) -> list[str]:
    plan, clashes = [], []
    for p in sorted(src.rglob("*")):
        if p.is_dir() and not p.is_symlink():
            continue
        target = dest / p.relative_to(src)
        if p.name == SUBJECT_FILE and p.parent == src:
            continue  # the subject keeps its own manifest
        if target.exists() and not force and not _same_file(p, target):
            clashes.append(str(p.relative_to(src)))
        plan.append((p, target))
    if clashes:
        raise LayoutError(f"{len(clashes)} file(s) already in the subject with other content: "
                          f"{', '.join(clashes[:8])}{' …' if len(clashes) > 8 else ''} (use --force to overwrite)")
    moved = []
    for p, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            p.unlink()  # identical copy already there
        else:
            shutil.move(str(p), str(target))
        moved.append(str(target))
    for d in sorted((d for d in src.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    leftover = src / SUBJECT_FILE
    if leftover.exists():
        leftover.unlink()
    return moved


def _place_file(item: Path, subject_dir: Path, as_n: int | None, force: bool) -> list[tuple[Path, Path]]:
    info = P.parse_name(item.name)
    if not info:
        raise LayoutError(f"{item.name} is not a QA pass file (QA-PASS-N.html, QA-PASS-N.src.html, QA-PASS*.md)")
    pair_ext = {"src.html": "html", "html": "src.html"}.get(info["ext"])
    stem = item.name[: -len(info["ext"]) - 1]
    group = [item]
    if pair_ext and (item.parent / f"{stem}.{pair_ext}").is_file():
        group.append(item.parent / f"{stem}.{pair_ext}")
    new_stem = f"QA-PASS-{as_n}{info['tag']}" if as_n is not None else stem
    plan = [(p, subject_dir / (new_stem + p.name[len(stem):])) for p in group]
    clashes = [t.name for _, t in plan if t.exists() and not force]
    if clashes:
        raise LayoutError(f"{', '.join(clashes)} already in {subject_dir} (use --as N for another number, "
                          f"or --force)")
    images = []
    for p, _ in plan:
        if p.name.endswith(".src.html"):
            images += re.findall(r"\{\{IMG:([^}]+)\}\}", p.read_text(encoding="utf-8"))
    for name in sorted(set(images)):
        src_img, dest_img = item.parent / "img" / name, subject_dir / "img" / name
        if not src_img.is_file():
            continue
        if dest_img.exists() and not _same_file(src_img, dest_img) and not force:
            raise LayoutError(f"img/{name} already in the subject with other content (rename it, or --force)")
        dest_img.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_img, dest_img)
    for p, target in plan:
        shutil.move(str(p), str(target))
        if as_n is not None and target.name.endswith(".src.html"):
            text = target.read_text(encoding="utf-8")
            target.write_text(re.sub(r'(<meta name="qa-pass" content=")\d+(")', rf"\g<1>{as_n}\2", text),
                              encoding="utf-8")
    return plan
