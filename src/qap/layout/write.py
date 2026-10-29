"""Create, move, place and remove folders and subjects.

make_folder, make_subject, remove_folder and set_meta edit a manifest where it stands.
move relocates a folder or a subject and re-points the symlinks it left behind.
place brings a pass file, or an old folder of passes, into a subject.
A project given to make_folder or make_subject is resolved in project.py.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import date
from pathlib import Path

from .. import passes as P
from .paths import (
    FOLDER_FILE, SUBJECT_FILE, LayoutError, _visible_dirs, abs_path, clean_rel, is_subject_dir, pretty,
    read_json, rel_path, write_json,
)
from .project import _check_top, _claim_top, set_project_meta
from .read import folder_node, subject_node

def _require_folder(root: Path, rel: str) -> Path:
    path = abs_path(root, rel)
    if not path.is_dir():
        raise LayoutError(f"folder {rel or '/'} does not exist")
    if rel and is_subject_dir(path):
        raise LayoutError(f"{rel} is a subject, not a folder")
    return path


def make_folder(root: Path, rel: str, title: str | None = None, icon: str | None = None,
                parents: bool = True, project: str | None = None) -> dict:
    """Create a folder (and its missing parents); writes folder.json when a title or icon is given.
    project ("@work" or "work"): the project the new path's top-level folder joins (see _check_top)."""
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
    claim = _check_top(root, rel, project)
    path.mkdir(parents=True)
    if title or icon:
        meta = {k: v for k, v in (("title", title), ("icon", icon)) if v}
        write_json(path / FOLDER_FILE, meta)
    _order_add(root, parent, path.name)
    _claim_top(root, rel, claim)
    return folder_node(root, path, False)


def make_subject(root: Path, rel: str, title: str | None = None, icon: str | None = None,
                 qa_project: str | None = None, sources: list[str] | None = None,
                 project: str | None = None) -> dict:
    """Create a subject folder with its subject.json (parent folders are created as needed).
    qa_project is the pages' stars key; project ("@work") is the project its top-level folder joins."""
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
    claim = _check_top(root, rel, project)
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
    _claim_top(root, rel, claim)
    return subject_node(root, path, False)


def remove_folder(root: Path, rel: str) -> dict:
    """Delete an empty folder (its folder.json included). Subjects and non-empty folders are refused:
    nothing that holds a pass is ever deleted by qap."""
    rel = clean_rel(rel)
    if not rel:
        raise LayoutError("cannot remove the content root")
    path = abs_path(root, rel)
    if not path.is_dir():
        raise LayoutError(f"{rel} does not exist")
    if is_subject_dir(path):
        raise LayoutError(f"{rel} is a subject; qap never deletes passes (move it instead)")
    left = [p.name for p in path.iterdir() if p.name != FOLDER_FILE and p.name != ".DS_Store"]
    if left:
        raise LayoutError(f"{rel} is not empty ({', '.join(sorted(left)[:5])}); move what it holds first")
    for p in path.iterdir():
        p.unlink()
    path.rmdir()
    _order_remove(root, rel.rsplit("/", 1)[0] if "/" in rel else "", path.name)
    return {"path": rel}


def set_meta(root: Path, rel: str, **fields) -> dict:
    """Update a folder's or subject's manifest (title, icon, color, qa_project, order). None leaves a field as is;
    '' clears it. The root folder's title and icon live in <root>/folder.json. "@<id>" changes a project
    (title, icon, color)."""
    if (rel or "").strip().startswith("@"):
        bad = {k for k, v in fields.items() if v is not None} - {"title", "icon", "color"}
        if bad:
            raise LayoutError(f"cannot set {sorted(bad)} on a project")
        return set_project_meta(root, rel.strip(), **{k: fields.get(k) for k in ("title", "icon", "color")})
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
