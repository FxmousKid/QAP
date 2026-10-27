"""qap — place, carry, build and browse QA passes.

Humans: run a command without its arguments in a terminal and qap asks (folders and subjects from a menu).
Agents: give every argument, add --json for machine output and --yes to skip confirmations.
Every command that changes the content goes through qap.layout, the same functions the dashboard uses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, icons, layout as L, passes as P, plugin_cli, plugins, prompt, skill

EPILOG = """examples:
  qap list                                  the tree of folders, subjects and passes
  qap where interaction --json              a subject's folder, latest pass and next pass
  qap next authz/rbac                       the next pass number and its file names
  qap carry db-migration-v3/interaction     start the next pass (carry.py; the template for pass 1)
  qap build interaction && qap check interaction
  qap new-subject coach/billing --title "Billing" --icon money --qa-project billing
  qap mkdir work --title "Work" --icon 💼
  qap mv authz work                         move a folder (or a subject) into another folder
  qap project new personal --title Personal --icon 🏡    a project: work and personal folders never mix
  qap project move side-projects personal   put a top-level folder (a family) in a project
  qap place ~/old/choices brain/prd16       move a folder of passes in; leaves a symlink behind
  qap serve --open                          the dashboard on http://127.0.0.1:8750
  qap plugins                               plugins: core (git-storage) and community ones
  qap storage git init --remote <url>       back the content up in a git remote (git-storage plugin)
"""


# ---------------------------------------------------------------------------- output

class Fail(Exception):
    pass


def emit(args, data: dict, human: str) -> None:
    if args.json:
        print(json.dumps({"ok": True, **data}, indent=2, ensure_ascii=False))
    elif human:
        print(human)


def root_of(args) -> Path:
    return config.content_root(getattr(args, "root", None))[0]


def show_icon(icon: str) -> str:
    if not icon:
        return "·"
    return f"[{icon}]" if icon in icons.builtin() else icon


# ---------------------------------------------------------------------------- picking things

def pick_subject(args, ref: str | None, what: str = "subject") -> dict:
    root = root_of(args)
    if ref:
        return L.resolve(root, ref, "subject")
    if not prompt.interactive(args):
        raise Fail(f"give a {what} (a path such as db-migration-v3/interaction, or a unique name; see `qap list`)")
    subjects = L.subjects(root)
    if not subjects:
        raise Fail(f"no subject under {root} yet (create one with `qap new-subject`)")
    value = prompt.choose(f"Which {what}?", [(s["path"], f"{show_icon(s['icon'])} {s['title']}  ({s['path']}, "
                                                          f"{s['count']} pass{'es' if s['count'] != 1 else ''})")
                                             for s in subjects])
    return L.resolve(root, value, "subject")


def pick_folder(args, ref: str | None, text: str = "Which folder?", allow_new: bool = False) -> str:
    root = root_of(args)
    if ref is not None:
        if ref.strip("/") == "":
            return ""
        node = L.resolve(root, ref, "folder")
        return node["path"]
    if not prompt.interactive(args):
        raise Fail("give a folder path ('/' for the top level; see `qap list`)")
    options = [(f["path"], ("  " * f["path"].count("/")) + f"{show_icon(f['icon'])} {f['title']}  "
                           f"({f['path'] or '/'})") for f in L.folders(root)]
    return prompt.choose(text, options, allow_new="a new folder path" if allow_new else None)


def pick_icon(args, current: str | None) -> str | None:
    if current is not None or not prompt.interactive(args):
        return icons.validate(current)
    names = sorted(icons.builtin())
    raw = prompt.ask(f"Icon (an emoji, or one of: {', '.join(names)}; empty for none)", required=False)
    return icons.validate(raw) if raw else None


def go_ahead(args, text: str) -> None:
    if prompt.interactive(args) and not prompt.confirm(text):
        raise prompt.Cancelled()


# ---------------------------------------------------------------------------- commands

def cmd_config(args) -> None:
    if args.key:
        if args.key not in config.KEYS:
            raise Fail(f"unknown key {args.key!r}; known: {', '.join(config.KEYS)}")
        if args.unset:
            config.write_config(args.key, None)
        elif args.value:
            config.write_config(args.key, args.value)
        elif prompt.interactive(args):
            config.write_config(args.key, prompt.ask(f"{args.key}", str(getattr(config, args.key)()[0])))
    root, root_from = config.content_root(getattr(args, "root", None))
    sk, sk_from = config.skill_dir()
    data = {"config_file": str(config.config_path()), "content_root": str(root), "content_root_from": root_from,
            "content_root_exists": root.is_dir(), "skill_dir": str(sk), "skill_dir_from": sk_from}
    emit(args, data, "\n".join([
        f"config file   {data['config_file']}",
        f"content_root  {root}  (from {root_from}{'' if root.is_dir() else ', MISSING'})",
        f"skill_dir     {sk}  (from {sk_from})",
    ]))


def _strip(node: dict, with_passes: bool) -> dict:
    out = {k: v for k, v in node.items() if k not in ("children", "passes", "projects")}
    if node["kind"] == "folder":
        out["children"] = [_strip(c, with_passes) for c in node["children"]]
    elif with_passes:
        out["passes"] = node["passes"]
    return out


def cmd_list(args) -> None:
    root = root_of(args)
    tree = L.tree(root, with_titles=args.passes)
    if args.path:
        node = L.resolve(root, args.path)
        tree = next(n for n in L.walk(tree) if n["path"] == node["path"])
    lines = [f"{tree['title']}  ({root / tree['path'] if tree['path'] else root})"]

    def draw(node: dict, depth: int) -> None:
        pad = "  " * depth
        if node["kind"] == "folder":
            lines.append(f"{pad}{show_icon(node['icon'])} {node['title']}/  {node['path']}  "
                         f"· {node['subjects']} subject{'s' if node['subjects'] != 1 else ''}")
            for child in node["children"]:
                draw(child, depth + 1)
            return
        when = node["updated"][:10] if node["updated"] else "—"
        lines.append(f"{pad}{show_icon(node['icon'])} {node['title']}  {node['path']}  · {node['count']} "
                     f"pass{'es' if node['count'] != 1 else ''}"
                     f" · latest {node['latest'] or '—'} · {when}")
        if args.passes:
            for p in node["passes"]:
                lines.append(f"{pad}    {p['label']:>4}  {p['file']}  {p['mtime'][:10]}  {p.get('title', '')[:70]}")

    top = tree.get("children", []) if tree["kind"] == "folder" else [tree]
    projects = (tree.get("projects") or []) if not args.path else []
    for project in projects:
        lines.append(f"  {show_icon(project['icon'])} {project['title']}  @{project['id']}"
                     f"{'  (default)' if project['default'] else ''}  · {_count(project['families'], 'family', 'families')}"
                     f" · {_count(project['subjects'], 'subject')}")
        for child in top:
            if child.get("project") == project["id"]:
                draw(child, 2)
    for child in top:
        if not projects or not child.get("project"):
            draw(child, 1)
    emit(args, {"root": str(root), "projects": projects, "tree": _strip(tree, args.passes)}, "\n".join(lines))


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _where(root: Path, node: dict) -> dict:
    d = L.abs_path(root, node["path"])
    last = node["passes"][-1] if node["passes"] else None
    return {
        "subject": node["path"], "dir": str(d), "title": node["title"], "icon": node["icon"],
        "qa_project": node["qa_project"], "count": node["count"],
        "latest": ({**last, "path": str(d / last["file"])} if last else None),
        "next": P.next_pass(d), "sources": node["sources"],
    }


def cmd_where(args) -> None:
    root = root_of(args)
    node = pick_subject(args, args.subject)
    data = _where(root, node)
    nxt = data["next"]
    emit(args, data, "\n".join([
        f"{node['title']}  ({node['path']})",
        f"  dir          {data['dir']}",
        f"  qa-project   {data['qa_project'] or '— (pages without <meta name=\"qa-project\">)'}",
        f"  passes       {data['count']}" + (f", latest {data['latest']['file']}" if data["latest"] else ""),
        f"  next pass    {nxt['n']}: {Path(nxt['src']).name} -> {Path(nxt['html']).name}"
        + (f" (carried from {Path(nxt['carry_from']).name})" if nxt["carry_from"] else " (from the template)"),
        f"  images       {nxt['img']}",
    ]))


def cmd_next(args) -> None:
    root = root_of(args)
    node = pick_subject(args, args.subject)
    nxt = P.next_pass(L.abs_path(root, node["path"]))
    emit(args, {"subject": node["path"], **nxt}, f"{nxt['n']}\n{nxt['src']}\n{nxt['html']}")


def cmd_new_subject(args) -> None:
    root = root_of(args)
    path = args.path
    if not path:
        if not prompt.interactive(args):
            raise Fail("give the subject's path, for example db-migration-v3/interaction")
        folder = pick_folder(args, None, "In which folder?", allow_new=True)
        title = args.title or prompt.ask("Title (shown on the tile)")
        name = prompt.ask("Folder name", L.slug(title))
        path = f"{folder}/{name}" if folder else name
        args.title = title
    title = args.title
    if title is None and prompt.interactive(args):
        title = prompt.ask("Title (shown on the tile)", L.pretty(path.rsplit("/", 1)[-1]))
    icon = pick_icon(args, args.icon)
    qa_project = args.qa_project
    if qa_project is None and prompt.interactive(args):
        qa_project = prompt.ask("qa-project (the pages' <meta name=\"qa-project\">; stars are kept per project)",
                                path.rsplit("/", 1)[-1])
    go_ahead(args, f"Create subject {path}?")
    node = L.make_subject(root, path, title=title, icon=icon, qa_project=qa_project, project=args.project)
    d = L.abs_path(root, node["path"])
    emit(args, {"subject": node["path"], "dir": str(d), "next": P.next_pass(d)},
         f"created {d}\n  next: `qap carry {node['path']}` starts pass 1 from the template")


def cmd_mkdir(args) -> None:
    root = root_of(args)
    path = args.path
    if not path:
        if not prompt.interactive(args):
            raise Fail("give the folder path, for example work/billing")
        parent = pick_folder(args, None, "Inside which folder?")
        args.title = args.title or prompt.ask("Title (shown on the tile)")
        name = prompt.ask("Folder name", L.slug(args.title))
        path = f"{parent}/{name}" if parent else name
    icon = pick_icon(args, args.icon)
    node = L.make_folder(root, path, title=args.title, icon=icon, project=args.project)
    emit(args, {"folder": node["path"], "dir": str(L.abs_path(root, node["path"]))}, f"created {node['path']}/")


def cmd_mv(args) -> None:
    root = root_of(args)
    src = args.src
    if not src:
        if not prompt.interactive(args):
            raise Fail("give what to move (a subject or folder path) and where")
        items = [n for n in L.walk(L.tree(root, False)) if n["path"]]
        src = prompt.choose("Move what?", [(n["path"], ("  " * n["path"].count("/")) + f"{show_icon(n['icon'])} "
                                                       f"{n['title']}  ({n['path']}{'/' if n['kind'] == 'folder' else ''})")
                                          for n in items])
    else:
        src = L.resolve(root, src)["path"]
    dest = args.dest
    if dest and dest.strip().startswith("@"):
        project = L.find_project(root, dest)
        go_ahead(args, f"Put {src} in project {project['title']}?")
        result = L.assign_project(root, src, project["path"])
        emit(args, result, f"{result['path']} is in {project['title']} now"
             + (f" (moved up from {result['from']})" if not result["from"].startswith("@") and result["from"] else "")
             + "".join(f"\n  relinked {r}" for r in result["relinked"]))
        return
    if dest is None:
        dest = pick_folder(args, None, f"Move {src} into which folder?")
    elif dest.strip("/") and not L.abs_path(root, dest).exists():
        dest = L.clean_rel(dest)  # a new path: move and rename
    elif dest.strip("/"):
        dest = L.resolve(root, dest, "folder")["path"]
    go_ahead(args, f"Move {src} -> {dest or '/'}?")
    result = L.move(root, src, dest)
    emit(args, result, f"moved {result['from']} -> {result['path']}"
         + "".join(f"\n  relinked {r}" for r in result["relinked"]))


def cmd_rmdir(args) -> None:
    root = root_of(args)
    node = L.resolve(root, args.path, "folder")
    go_ahead(args, f"Remove the empty folder {node['path']}?")
    result = L.remove_folder(root, node["path"])
    emit(args, result, f"removed {result['path']}/")


def cmd_rename(args) -> None:
    root = root_of(args)
    node = L.resolve(root, args.path) if args.path.strip("/") else {"path": ""}
    title = args.title or (prompt.ask("New title") if prompt.interactive(args) else None)
    if not title:
        raise Fail("give the new title")
    out = L.set_meta(root, node["path"], title=title)
    emit(args, {"path": out["path"], "title": out["title"]}, f"{out['path'] or '/'}: title is now {out['title']!r}")


def cmd_icon(args) -> None:
    root = root_of(args)
    node = L.resolve(root, args.path) if args.path.strip("/") else {"path": ""}
    icon = icons.validate(args.icon) if args.icon is not None else pick_icon(args, None)
    color = icons.validate_color(args.color)
    out = L.set_meta(root, node["path"], icon=icon, color=color)
    emit(args, {"path": out["path"], "icon": out["icon"], "color": out["color"]},
         f"{out['path'] or '/'}: icon {show_icon(out['icon'])}" + (f", colour {out['color']}" if out["color"] else ""))


def cmd_place(args) -> None:
    root = root_of(args)
    item = Path(args.item).expanduser()
    subject = args.subject
    if not subject:
        if not prompt.interactive(args):
            raise Fail("give the subject to place it in (see `qap list`)")
        node = pick_subject(args, None, "subject to place it in")
        subject = node["path"]
    else:
        try:
            subject = L.resolve(root, subject, "subject")["path"]
        except L.LayoutError:
            if not args.create:
                raise
            subject = L.clean_rel(subject)
    link = args.link if args.link is not None else None
    go_ahead(args, f"Move {item} into {subject}"
             + (" and leave a symlink behind?" if (link if link is not None else item.is_dir()) else "?"))
    result = L.place(root, item, subject, link=link, as_n=args.as_n, create=args.create, title=args.title,
                     icon=icons.validate(args.icon), force=args.force)
    emit(args, result, f"placed {len(result['moved'])} file(s) in {result['subject']}"
         + "".join(f"\n  link {line}" for line in result["links"]))


def cmd_project(args) -> None:
    """qap project [list] | new <id> | move <folder|subject> <project> | set <project> | rm <project>"""
    root = root_of(args)
    action = args.action or "list"
    if action == "list":
        nodes = L.projects(root)
        lines = [f"{show_icon(p['icon'])} {p['title']}  @{p['id']}{'  (default)' if p['default'] else ''}  · "
                 f"{_count(p['families'], 'family', 'families')} · {_count(p['subjects'], 'subject')}"
                 + "".join(f"\n    {m}" for m in p["members"]) for p in nodes]
        emit(args, {"projects": nodes}, "\n".join(lines) or "no project yet: `qap project new work --title Work` "
                                                          "puts every top-level folder in it")
        return
    if action == "new":
        name = args.name or (prompt.ask("Project id (work, personal…)") if prompt.interactive(args) else None)
        if not name:
            raise Fail("give the project an id, for example `qap project new personal --title Personal`")
        title = args.title or (prompt.ask("Title (shown on its box)", L.pretty(name)) if prompt.interactive(args)
                               else None)
        node = L.make_project(root, name, title=title, icon=pick_icon(args, args.icon),
                              color=icons.validate_color(args.color), default=args.default)
        emit(args, {"project": node}, f"created {node['path']} ({node['title']})"
             + (": the default, so every top-level folder without a project is in it" if node["default"] else ""))
        return
    if action == "move":
        if not args.name:
            if not prompt.interactive(args):
                raise Fail("give the folder or subject, then the project: qap project move <path> <project>")
            items = [n for n in L.walk(L.tree(root, False)) if n["path"]]
            args.name = prompt.choose("Which folder or subject?", [
                (n["path"], ("  " * n["path"].count("/")) + f"{show_icon(n['icon'])} {n['title']}  ({n['path']})")
                for n in items])
        if not args.target:
            if not prompt.interactive(args):
                raise Fail("give the project: qap project move <path> <project>")
            args.target = prompt.choose("Into which project?", [(p["path"], f"{show_icon(p['icon'])} {p['title']}")
                                                                for p in L.projects(root)])
        node = L.resolve(root, args.name)
        project = L.find_project(root, args.target)
        if "/" in node["path"]:
            go_ahead(args, f"{node['path']} is not at the top level: move it up to the top level and into "
                           f"{project['title']}?")
        result = L.assign_project(root, node["path"], project["path"])
        emit(args, result, f"{result['path']} is in {project['title']} now"
             + "".join(f"\n  relinked {r}" for r in result["relinked"]))
        return
    if action == "set":
        if not args.name:
            raise Fail("give the project: qap project set <project> [--title] [--icon] [--color] [--default]")
        node = L.set_project_meta(root, args.name, title=args.title, icon=icons.validate(args.icon),
                                  color=icons.validate_color(args.color), default=args.default or None)
        emit(args, {"project": node}, f"{node['path']}: {node['title']}, icon {show_icon(node['icon'])}"
             + (", the default" if node["default"] else ""))
        return
    if action == "rm":
        if not args.name:
            raise Fail("give the project to remove (it must be empty)")
        node = L.find_project(root, args.name)
        go_ahead(args, f"Remove the empty project {node['title']}?")
        result = L.remove_project(root, node["path"])
        emit(args, result, f"removed {result['path']}")
        return
    raise Fail(f"unknown action {action!r}: list, new, move, set or rm")


def cmd_carry(args) -> None:
    root = root_of(args)
    node = pick_subject(args, args.subject)
    d = L.abs_path(root, node["path"])
    nxt = P.next_pass(d)
    if Path(nxt["src"]).exists():
        raise Fail(f"{nxt['src']} already exists")
    if nxt["carry_from"]:
        result = skill.carry(Path(nxt["carry_from"]), Path(nxt["src"]), nxt["n"], args.skip, args.stars, args.ai)
    else:
        result = skill.seed_first(Path(nxt["src"]), node["qa_project"] or Path(node["path"]).name, nxt["n"])
    if not result["ok"]:
        raise Fail(result["output"])
    emit(args, {"subject": node["path"], **result, "html": nxt["html"]}, result["output"])


def _sources(root: Path, node: dict, n: int | None, every: bool) -> list[Path]:
    d = L.abs_path(root, node["path"])
    if every:
        return [d / p["src"] for p in node["passes"] if p["src"]]
    return [P.source_for(d, n)]


def cmd_build(args) -> None:
    root = root_of(args)
    node = pick_subject(args, args.subject)
    results = []
    for src in _sources(root, node, args.n, args.all):
        r = skill.rebuild_safely(src) if args.all else skill.build(src)
        if args.check and r["ok"] and not args.all:
            r["check"] = skill.check(Path(r["html"]))
        results.append(r)
    lines = []
    for r in results:
        if args.all:
            lines.append(f"{Path(r['html']).name:<24} {r['reason']}")
        else:
            lines.append(r["output"])
            if "check" in r:
                lines.append(r["check"]["output"])
    failed = [r for r in results if not r["ok"] or (r.get("check") and not r["check"]["ok"])]
    data = {"subject": node["path"], "results": results}
    heard = args.app.emit("pass_built", {"subject": node["path"], "ok": not failed, "source": "cli",
                                         "pages": [r["html"] for r in results if r["ok"]],
                                         "interactive": prompt.interactive(args)}) if hasattr(args, "app") else {}
    if heard:
        data["plugins"] = heard
        lines += [r["text"] for r in heard.values() if r.get("text")]
    emit(args, data, "\n".join(lines) or "nothing to build")
    if failed and not args.all:
        raise SystemExit(1)


def cmd_check(args) -> None:
    root = root_of(args)
    node = pick_subject(args, args.subject)
    d = L.abs_path(root, node["path"])
    if args.all:
        pages = [d / p["file"] for p in node["passes"] if p["kind"] == "html"]
    elif args.n is not None:
        pages = [d / f"QA-PASS-{args.n}.html"]
    else:
        pages = [d / node["passes"][-1]["file"]] if node["passes"] else []
    results = [skill.check(p) for p in pages]
    emit(args, {"subject": node["path"], "results": results}, "\n".join(r["output"] for r in results))
    if any(not r["ok"] for r in results):
        raise SystemExit(1)


def cmd_serve(args) -> None:
    from . import server
    app = getattr(args, "app", None)
    if app is not None:  # reload the plugins in serve mode: their intervals run while the server does
        app.unload_all()
        app.mode = "serve"
        app.load_enabled()
    server.serve(root_of(args), args.port, args.open, as_json=args.json, app=app)


# ---------------------------------------------------------------------------- parser

def parser(app: plugins.App | None = None) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="content root (default: QAP_CONTENT_ROOT, then config, then "
                                       "~/Desktop/Dev/ai/QAP/contents)")
    common.add_argument("--json", action="store_true", help="machine-readable output, no prompts")
    common.add_argument("--yes", "-y", action="store_true", help="no prompts, no confirmations")

    ap = argparse.ArgumentParser(prog="qap", description=__doc__, epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", metavar="<command>")

    def add(name, fn, help_, **kw):
        p = sub.add_parser(name, parents=[common], help=help_, description=help_, **kw)
        p.set_defaults(fn=fn)
        return p

    p = add("config", cmd_config, "show the configuration, or set a key (content_root, skill_dir)")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--unset", action="store_true", help="remove the key from the config file")

    p = add("list", cmd_list, "the tree of folders, subjects and passes")
    p.add_argument("path", nargs="?", help="only this folder or subject")
    p.add_argument("--passes", action="store_true", help="every pass, with its title")

    p = add("where", cmd_where, "a subject's folder, latest pass and next pass")
    p.add_argument("subject", nargs="?")
    p = add("next", cmd_next, "the next pass number and its file names")
    p.add_argument("subject", nargs="?")

    p = add("new-subject", cmd_new_subject, "create a subject: <folder>/<subject> with its subject.json")
    p.add_argument("path", nargs="?")
    p.add_argument("--title")
    p.add_argument("--icon", help="an emoji or a built-in icon name")
    p.add_argument("--qa-project", dest="qa_project", help="the pages' <meta name=\"qa-project\"> (stars key)")
    p.add_argument("--project", help="the project (work, personal…) a new top-level folder joins; not --qa-project")

    p = add("mkdir", cmd_mkdir, "create a folder (parents included)")
    p.add_argument("path", nargs="?")
    p.add_argument("--title")
    p.add_argument("--icon")
    p.add_argument("--project", help="the project (work, personal…) a new top-level folder joins")

    p = add("mv", cmd_mv, "move a subject or folder into a folder (or to a new path: move and rename)")
    p.add_argument("src", nargs="?")
    p.add_argument("dest", nargs="?", help="a folder ('/' = top level), a new path, or @project")

    p = add("project", cmd_project, "projects above the top-level folders: list, new, move, set, rm")
    p.add_argument("action", nargs="?", choices=("list", "new", "move", "set", "rm"))
    p.add_argument("name", nargs="?", help="new/set/rm: the project id; move: the folder or subject")
    p.add_argument("target", nargs="?", help="move: the project (@id, id or title)")
    p.add_argument("--title")
    p.add_argument("--icon", help="an emoji or a built-in icon name")
    p.add_argument("--color", help="#RRGGBB")
    p.add_argument("--default", action="store_true",
                   help="the project of every top-level folder that names none")

    p = add("rmdir", cmd_rmdir, "remove an empty folder (subjects and non-empty folders are refused)")
    p.add_argument("path")

    p = add("rename", cmd_rename, "change the title shown on a tile (the folder name on disk stays)")
    p.add_argument("path")
    p.add_argument("title", nargs="?")

    p = add("icon", cmd_icon, "set the icon (emoji or built-in name; '' clears) and optionally the tile colour")
    p.add_argument("path")
    p.add_argument("icon", nargs="?")
    p.add_argument("--color", help="#RRGGBB")

    p = add("place", cmd_place, "move a pass file, or a folder of passes, into a subject")
    p.add_argument("item")
    p.add_argument("subject", nargs="?")
    p.add_argument("--as", dest="as_n", type=int, help="renumber the pass to N")
    p.add_argument("--link", dest="link", action="store_true", default=None,
                   help="leave a symlink at the old place (default for a folder)")
    p.add_argument("--no-link", dest="link", action="store_false")
    p.add_argument("--create", action="store_true", help="create the subject when it does not exist")
    p.add_argument("--title")
    p.add_argument("--icon")
    p.add_argument("--force", action="store_true", help="overwrite files with the same name")

    p = add("carry", cmd_carry, "start the next pass of a subject (carry.py; the template for pass 1)")
    p.add_argument("subject", nargs="?")
    p.add_argument("--skip", default="", help="subject ids that get no new round (p7,p8)")
    p.add_argument("--stars", default="", help="file with the stars dialog's 'Copy list' ('-' = stdin)")
    p.add_argument("--ai", default="", help="vendor|Name|Model, default claude|Claude|Opus 5.5")

    for name, fn, help_ in (("build", cmd_build, "build a pass page from its source (build.py)"),
                            ("check", cmd_check, "check a built page (check.py)")):
        p = add(name, fn, help_)
        p.add_argument("subject", nargs="?")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--pass", dest="n", type=int, help="pass number (default: the latest)")
        g.add_argument("--all", action="store_true",
                       help="every pass" + (" that has a source; keeps the old page when the rebuilt one has "
                                            "check problems" if name == "build" else ""))
        if name == "build":
            p.add_argument("--check", action="store_true", help="run check.py after the build")

    p = add("serve", cmd_serve, "serve the dashboard and the content on 127.0.0.1")
    p.add_argument("--port", type=int, default=None, help="default 8750 (the next free one if taken)")
    p.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    if app is not None:
        plugin_cli.add_parsers(sub, common, app)
    return ap


# Commands that change the content: plugins hear "content_changed" after each of them (mkdir, new-subject with
# --project and mv to @project included). `project` changes it unless it only lists.
CHANGES = {"new-subject", "mkdir", "mv", "rmdir", "rename", "icon", "place", "carry", "project"}


def changed_content(args) -> dict | None:
    """The content_changed payload for a command that wrote to the content root, else None."""
    if args.command not in CHANGES:
        return None
    if args.command == "project":
        action = args.action or "list"
        return None if action == "list" else {"action": "project", "project_action": action, "source": "cli"}
    return {"action": args.command, "source": "cli"}


def main(argv: list[str] | None = None) -> int:
    app = plugins.App()
    app.load_enabled()
    ap = parser(app)
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        (getattr(args, "group_help", None) or ap.print_help)()
        return 0
    args.app = app
    try:
        app.set_root(root_of(args))
        args.fn(args)
        payload = changed_content(args)
        if payload:
            app.emit("content_changed", payload)
    except prompt.Cancelled:
        print("cancelled", file=sys.stderr)
        return 130
    except SystemExit as e:  # a command that printed its output and failed (build, a plugin command)
        if isinstance(e.code, int):
            return e.code
        message = str(e.code or "failed")  # SystemExit("qap: cannot read …"): say it
        if args.json:
            print(json.dumps({"ok": False, "error": message.removeprefix("qap: ")}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 1
    except (Fail, L.LayoutError, plugins.PluginError, ValueError, LookupError, FileNotFoundError, OSError) as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"qap: {e}", file=sys.stderr)
        return 1
    finally:
        app.unload_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
