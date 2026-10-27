"""The CLI side of plugins: `qap plugins …`, and the commands enabled plugins add (`qap storage git sync`, …).

A plugin command's words come from its add_command(cli=…). Words shared by several plugins become a group
(`qap storage` could hold `git` and, later, `s3`); a word qap itself uses (list, build, …) is refused.
"""
from __future__ import annotations

import json
import sys

from . import plugins, prompt


def add_parsers(sub, common, app: plugins.App) -> None:
    builtin = set(sub.choices)

    p = sub.add_parser("plugins", parents=[common], help="list, enable, disable, configure and install plugins",
                       description="Plugins: core ones ship with qap (on by default), community ones live in "
                                   "~/.config/qap/plugins (off until enabled). `qap plugins` alone lists them.")
    p.set_defaults(fn=cmd_list)
    ps = p.add_subparsers(dest="plugins_action", metavar="<action>")
    q = ps.add_parser("list", parents=[common], help="every plugin, on or off, and what it adds")
    q.set_defaults(fn=cmd_list)
    for name, fn, text in (("enable", cmd_enable, "turn a plugin on"), ("disable", cmd_disable, "turn a plugin off")):
        q = ps.add_parser(name, parents=[common], help=text)
        q.add_argument("id")
        q.set_defaults(fn=fn)
    q = ps.add_parser("config", parents=[common], help="a plugin's settings tab: show, or set one key")
    q.add_argument("id")
    q.add_argument("key", nargs="?")
    q.add_argument("value", nargs="?")
    q.add_argument("--reset", action="store_true", help="back to the default value")
    q.set_defaults(fn=cmd_config)
    q = ps.add_parser("install", parents=[common], help="install a plugin from a folder or a git URL (stays off)")
    q.add_argument("source", help="a plugin folder (with manifest.json) or a git URL")
    q.add_argument("--link", action="store_true", help="symlink the folder instead of copying (for development)")
    q.set_defaults(fn=cmd_install)
    q = ps.add_parser("remove", parents=[common], help="delete a community plugin")
    q.add_argument("id")
    q.set_defaults(fn=cmd_remove)

    groups: dict[tuple, object] = {}
    for cmd in app.commands():
        if cmd.cli[0] in builtin or cmd.cli[0] == "plugins":
            app.log(f"plugin {cmd.plugin}: `qap {cmd.cli[0]}` belongs to qap itself; command {cmd.id} left out")
            continue
        parent, path = sub, ()
        for word in cmd.cli[:-1]:
            path += (word,)
            if path not in groups:
                if word in parent.choices:
                    parent = None
                    break
                gp = parent.add_parser(word, help=f"{' '.join(path)} commands (from plugins)")
                gp.set_defaults(group_help=gp.print_help)
                groups[path] = gp.add_subparsers(metavar="<command>")
            parent = groups[path]
        if parent is None or cmd.cli[-1] in parent.choices:
            app.log(f"plugin {cmd.plugin}: `qap {' '.join(cmd.cli)}` is taken; command {cmd.id} left out")
            continue
        leaf = parent.add_parser(cmd.cli[-1], parents=[common], help=cmd.name,
                                 description=f"{cmd.name} (plugin {cmd.plugin})")
        for flags, kw in cmd.args:
            leaf.add_argument(*flags, **kw)
        leaf.set_defaults(fn=run_command, plugin_command=cmd.full_id)


def _print(args, ok: bool, data: dict, text: str) -> None:
    if args.json:
        print(json.dumps({"ok": ok, **data}, indent=2, ensure_ascii=False, default=str))
    elif text:
        print(text, file=sys.stdout if ok else sys.stderr)
    if not ok:
        raise SystemExit(1)


def run_command(args) -> None:
    app: plugins.App = args.app
    cmd = app._commands[args.plugin_command]
    values = {k: getattr(args, k) for k in cmd.defaults() if hasattr(args, k)}
    result = app.run_command(cmd.full_id, values, source="cli", json_out=args.json,
                             interactive=prompt.interactive(args))
    ok = bool(result.pop("ok", True))
    _print(args, ok, result, result.get("text", ""))  # --json keeps "text": the how-to lines are for agents too


# ---------------------------------------------------------------------------- qap plugins …

def cmd_list(args) -> None:
    items = args.app.describe()
    lines = []
    for core in (True, False):
        group = [i for i in items if i["core"] == core]
        lines.append("Core plugins" if core else f"Community plugins  ({args.app.config_dir / 'plugins'})")
        if not group:
            lines.append("  none (qap plugins install <folder | git URL>)")
        for i in group:
            state = "on " if i["loaded"] else "off" if not i["error"] else "ERR"
            lines.append(f"  [{state}] {i['id']} {i.get('version', '')}  {i.get('name', '')}")
            if i.get("description"):
                lines.append(f"        {i['description']}")
            if i["error"]:
                lines.append(f"        error: {i['error']}")
            for c in i.get("commands", []):
                lines.append(f"        {c['cli']:<28} {c['name']}")
    _print(args, True, {"plugins": items}, "\n".join(lines))


def cmd_enable(args) -> None:
    plugin = args.app.enable(args.id)
    if plugin is None:
        raise plugins.PluginError(f"{args.id} is enabled but did not load: {args.app.errors.get(args.id, '?')}")
    _print(args, True, {"id": args.id, "enabled": True}, f"{args.id}: on")


def cmd_disable(args) -> None:
    args.app.disable(args.id)
    _print(args, True, {"id": args.id, "enabled": False}, f"{args.id}: off")


def cmd_config(args) -> None:
    plugin = args.app.get(args.id)
    schema = plugin._settings
    if args.key:
        if args.key not in schema:
            raise plugins.PluginError(f"{args.id} has no setting {args.key!r}; known: {', '.join(schema)}")
        if args.reset:
            data = plugin.load_data()
            (data.get("settings") or {}).pop(args.key, None)
            plugin.save_data(data)
        elif args.value is not None:
            plugin.set_setting(args.key, args.value)
    values = plugin.settings
    shown = [args.key] if args.key else list(schema)
    lines = []
    for key in shown:
        s = schema[key]
        mark = "" if values[key] == s.default else "   (default " + json.dumps(s.default) + ")"
        lines.append(f"{key} = {json.dumps(values[key], ensure_ascii=False)}{mark}")
        lines.append(f"    {s.label}" + (f": {s.help}" if s.help else "")
                     + (f" [{' | '.join(s.choices)}]" if s.choices else ""))
    _print(args, True, {"id": args.id, "settings": [schema[k].describe(values[k]) for k in shown]}, "\n".join(lines))


def cmd_install(args) -> None:
    found = args.app.install(args.source, link=args.link)
    m = found.manifest
    _print(args, True, {"id": m.id, "folder": str(found.folder), "enabled": False},
           f"installed {m.name} {m.version} at {found.folder}\n"
           f"  A plugin runs code with your permissions: read it, then `qap plugins enable {m.id}`.")


def cmd_remove(args) -> None:
    if prompt.interactive(args) and not prompt.confirm(f"Delete the plugin {args.id} and its folder?"):
        raise prompt.Cancelled()
    folder = args.app.remove(args.id)
    _print(args, True, {"id": args.id, "removed": str(folder)}, f"removed {folder}")
