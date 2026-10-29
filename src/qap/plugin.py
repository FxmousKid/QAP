"""What a plugin author subclasses. `qap.plugins` re-exports every name defined here.

A plugin's main module defines one Plugin subclass. onload() registers commands, routes, events
and settings; unload removes them. The host that finds plugins and calls those hooks is plugins.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
EVENTS = ("startup", "shutdown", "pass_built", "content_changed")
ROUTE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")
RESERVED_ROUTES = ("run", "settings", "enable", "disable")  # /api/plugins/<id>/<these> belong to qap


class PluginError(Exception):
    """A refused plugin operation (bad manifest, unknown setting, failing command); the message says why."""


# ---------------------------------------------------------------------------- manifests

@dataclass
class Manifest:
    id: str
    name: str
    version: str
    min_app_version: str
    description: str
    author: str = ""
    author_url: str = ""
    main: str = "main.py"
    web: dict = field(default_factory=dict)  # {"main": "web/main.js", "style": "web/style.css"}

    @classmethod
    def read(cls, folder: Path) -> "Manifest":
        path = folder / "manifest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PluginError(f"cannot read {path}: {e}")
        if not isinstance(data, dict):
            raise PluginError(f"{path}: expected a JSON object")
        missing = [k for k in ("id", "name", "version", "minAppVersion", "description") if not data.get(k)]
        if missing:
            raise PluginError(f"{path}: missing {', '.join(missing)}")
        if not ID.match(str(data["id"])):
            raise PluginError(f"{path}: id {data['id']!r} must be lowercase letters, digits and single hyphens")
        for key in ("version", "minAppVersion"):
            if not VERSION.match(str(data[key])):
                raise PluginError(f"{path}: {key} {data[key]!r} must be x.y.z")
        web = data.get("web") or {}
        if not isinstance(web, dict) or any(not isinstance(v, str) for v in web.values()):
            raise PluginError(f"{path}: web must be an object like {{\"main\": \"web/main.js\"}}")
        return cls(id=data["id"], name=str(data["name"]), version=data["version"],
                   min_app_version=data["minAppVersion"], description=str(data["description"]),
                   author=str(data.get("author") or ""), author_url=str(data.get("authorUrl") or ""),
                   main=str(data.get("main") or "main.py"), web=web)


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def check_args(name: str, args: list) -> None:
    """Declare a command's args on a parser that already has qap's own options (-h, --root, --json, --yes/-y),
    so a clash or a bad argparse keyword is caught when the plugin loads."""
    p = argparse.ArgumentParser(prog=name)
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")
    for item in args:
        try:
            flags, kw = item
            p.add_argument(*flags, **kw)
        except (argparse.ArgumentError, TypeError, ValueError) as e:
            raise PluginError(f"{name}: bad argument {item!r}: {e}")


# ---------------------------------------------------------------------------- what plugins register

@dataclass
class Setting:
    """One field of a plugin's settings tab. The type is the default's type (bool, int or str);
    choices turns a str into a pick list."""
    key: str
    label: str
    default: Any
    help: str = ""
    choices: tuple = ()

    @property
    def type(self) -> str:
        return "bool" if isinstance(self.default, bool) else "int" if isinstance(self.default, int) else "str"

    def coerce(self, value: Any) -> Any:
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off"):
                return False
            raise PluginError(f"{self.key}: expected true or false, got {value!r}")
        if self.type == "int":
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise PluginError(f"{self.key}: expected a whole number, got {value!r}")
            if number < 0:
                raise PluginError(f"{self.key}: expected 0 or more")
            return number
        text = str(value)
        if self.choices and text not in self.choices:
            raise PluginError(f"{self.key}: expected one of {', '.join(self.choices)}, got {text!r}")
        return text

    def describe(self, value: Any) -> dict:
        return {"key": self.key, "label": self.label, "help": self.help, "type": self.type,
                "choices": list(self.choices), "default": self.default, "value": value}


@dataclass
class Command:
    plugin: str
    id: str
    name: str
    callback: Callable[[SimpleNamespace], dict]
    cli: tuple[str, ...]
    args: list
    dashboard: bool
    needs_input: bool = False

    @property
    def full_id(self) -> str:
        return f"{self.plugin}:{self.id}"

    def defaults(self) -> dict:
        """The value of every declared argument when nobody gives it (what argparse would fill in)."""
        p = argparse.ArgumentParser(add_help=False)
        for flags, kw in self.args:
            p.add_argument(*flags, **kw)
        return {a.dest: a.default for a in p._actions}


# ---------------------------------------------------------------------------- the plugin base class

class Plugin:
    """Subclass it in your plugin's main module. qap calls onload() when the plugin is enabled (in every
    `qap` process: keep it to registering things) and onunload() when it is disabled or qap exits."""

    def __init__(self, app: "App", manifest: Manifest, folder: Path, core: bool):
        self.app = app
        self.manifest = manifest
        self.folder = folder
        self.core = core
        self._cleanups: list[Callable[[], None]] = []
        self._settings: dict[str, Setting] = {}

    # -- lifecycle (override these)
    def onload(self) -> None:
        pass

    def onunload(self) -> None:
        pass

    # -- registration: every add_/register_ call is undone when the plugin unloads
    def register(self, cleanup: Callable[[], None]) -> None:
        self._cleanups.append(cleanup)

    def add_command(self, id: str, name: str, callback: Callable[[SimpleNamespace], dict], *,
                    cli: tuple[str, ...] | list[str] | str | None = None, args: list | None = None,
                    dashboard: bool = True, needs_input: bool | None = None) -> Command:
        """callback(opts) -> dict. opts holds the declared args (argparse dest names) plus .source ("cli" or
        "dashboard"), .json and .interactive. Return {"ok": bool, "text": human line(s), ...data}.
        cli: the words after `qap` (default: <plugin id> <command id>). args: [(flags, argparse kwargs), ...].
        dashboard: the dashboard may run it (POST /api/plugins/<id>/run/<command>). needs_input: it makes no sense
        without arguments, so the Plugins page shows no Run button (default: an argument is positional or required)."""
        if not ID.match(id):
            raise PluginError(f"{self.manifest.id}: command id {id!r} must be lowercase letters, digits, hyphens")
        words = tuple(cli.split()) if isinstance(cli, str) else tuple(cli or (self.manifest.id, id))
        args = list(args or [])
        check_args(f"{self.manifest.id}:{id}", args)  # a bad declaration fails this plugin's load, not qap
        if needs_input is None:
            needs_input = any(not flags[0].startswith("-") or kw.get("required") for flags, kw in args)
        cmd = Command(self.manifest.id, id, name, callback, words, args, dashboard, needs_input)
        self.app._commands[cmd.full_id] = cmd
        self.register(lambda: self.app._commands.pop(cmd.full_id, None))
        return cmd

    def register_route(self, method: str, path: str, handler: Callable[[dict], dict]) -> None:
        """handler(body) -> dict, served at /api/plugins/<id>/<path>. GET gets the query string as body.
        POSTs pass the same guards as the dashboard's own writes (this origin only, JSON body). A GET must not
        change anything: any web page can make the browser send one (it cannot read the answer)."""
        method = method.upper()
        if method not in ("GET", "POST") or not ROUTE.match(path) or path.split("/")[0] in RESERVED_ROUTES:
            raise PluginError(f"{self.manifest.id}: bad route {method} {path!r}")
        key = (self.manifest.id, method, path)
        self.app._routes[key] = handler
        self.register(lambda: self.app._routes.pop(key, None))

    def register_event(self, name: str, handler: Callable[[dict], dict | None]) -> None:
        """handler(payload) -> optional dict ({"text": ...} is shown after the command that fired the event).
        Built-in events: startup / shutdown (qap serve), pass_built (qap build), content_changed (any write
        from the CLI or the dashboard). Plugins may emit their own, named "<plugin id>:<event>"."""
        entry = (self.manifest.id, handler)
        handlers = self.app._handlers.setdefault(name, [])
        handlers.append(entry)

        def undo() -> None:
            if entry in handlers:
                handlers.remove(entry)

        self.register(undo)

    def register_interval(self, seconds: int | Callable[[], int], fn: Callable[[], Any]) -> None:
        """Call fn every `seconds` (a number, or a function read each time; 0 = paused) while `qap serve`
        runs. In one-shot CLI runs nothing is scheduled."""
        if self.app.mode != "serve":
            return
        stop = threading.Event()

        def loop() -> None:
            last = time.monotonic()
            while not stop.wait(self.app.tick):
                try:
                    period = seconds() if callable(seconds) else seconds
                except Exception as e:  # e.g. an unreadable data.json: skip this tick, keep the thread alive
                    self.log(f"interval: {e}")
                    period = 0
                if period and time.monotonic() - last >= period:
                    last = time.monotonic()
                    self.app._safely(self.manifest.id, "interval", fn)

        thread = threading.Thread(target=loop, name=f"qap-plugin-{self.manifest.id}", daemon=True)
        thread.start()

        def undo() -> None:  # let a run in progress (a git sync) finish, within reason
            stop.set()
            if thread is not threading.current_thread():
                thread.join(timeout=30)

        self.register(undo)

    def add_settings(self, *settings: Setting) -> None:
        for s in settings:
            self._settings[s.key] = s
        self.register(lambda: [self._settings.pop(s.key, None) for s in settings])

    # -- data: ~/.config/qap/plugins/<id>/data.json
    @property
    def data_dir(self) -> Path:
        return self.app.config_dir / "plugins" / self.manifest.id

    def load_data(self) -> dict:
        path = self.data_dir / "data.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise PluginError(f"cannot read {path}: {e}")
        return data if isinstance(data, dict) else {}

    def save_data(self, data: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "data.json"
        tmp = path.with_name("data.json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @property
    def settings(self) -> dict:
        saved = self.load_data().get("settings") or {}
        out = {}
        for key, s in self._settings.items():
            try:
                out[key] = s.coerce(saved[key]) if key in saved else s.default
            except PluginError:
                out[key] = s.default
        return out

    def set_setting(self, key: str, value: Any) -> Any:
        if key not in self._settings:
            raise PluginError(f"{self.manifest.id} has no setting {key!r}; known: {', '.join(self._settings)}")
        value = self._settings[key].coerce(value)
        data = self.load_data()
        data.setdefault("settings", {})[key] = value
        self.save_data(data)
        return value

    def log(self, message: str) -> None:
        self.app.log(f"{self.manifest.id}: {message}")
