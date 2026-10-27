"""Plugins: small, Obsidian-style. A plugin is a folder with a manifest.json and a Python main module whose
Plugin subclass registers what it adds in onload(); everything it registered is removed again on unload.

    <plugin folder>/
      manifest.json      {id, name, version, minAppVersion, description, author, main?, web?}
      main.py            class MyPlugin(Plugin): def onload(self): self.add_command(...)
      web/main.js        optional dashboard part: export function onload(app) {...}

Where plugins come from, first match per id wins:
  core       src/qap/core_plugins/<id>/            shipped with qap, enabled unless you disable them
  community  ~/.config/qap/plugins/<id>/          installed with `qap plugins install`, off until enabled

What a plugin can register (all removed on unload):
  add_command(id, name, callback, cli=("storage", "git", "sync"), args=[...])   a CLI command + a dashboard command
  register_route("GET" | "POST", "status", handler)                             /api/plugins/<id>/status
  register_event("pass_built" | "content_changed" | "startup" | "shutdown", handler)
  register_interval(seconds, fn)                                                 only while `qap serve` runs
  add_settings(Setting(...), ...)                                                its settings tab (CLI + dashboard)

Settings and other per-machine data live in ~/.config/qap/plugins/<id>/data.json; the enabled list in
~/.config/qap/plugins.json. Nothing of a plugin lives in the content root: pulled content never runs code.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from . import __version__, config

CORE_DIR = Path(__file__).resolve().parent / "core_plugins"
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
        if needs_input is None:
            needs_input = any(not flags[0].startswith("-") or kw.get("required") for flags, kw in args)
        cmd = Command(self.manifest.id, id, name, callback, words, args, dashboard, needs_input)
        self.app._commands[cmd.full_id] = cmd
        self.register(lambda: self.app._commands.pop(cmd.full_id, None))
        return cmd

    def register_route(self, method: str, path: str, handler: Callable[[dict], dict]) -> None:
        """handler(body) -> dict, served at /api/plugins/<id>/<path>. GET gets the query string as body.
        POSTs pass the same guards as the dashboard's own writes (this origin only, JSON body)."""
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
                period = seconds() if callable(seconds) else seconds
                if period and time.monotonic() - last >= period:
                    last = time.monotonic()
                    self.app._safely(self.manifest.id, "interval", fn)

        thread = threading.Thread(target=loop, name=f"qap-plugin-{self.manifest.id}", daemon=True)
        thread.start()
        self.register(stop.set)

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


# ---------------------------------------------------------------------------- the host

@dataclass
class Found:
    """A plugin folder on disk, loaded or not."""
    manifest: Manifest | None
    folder: Path
    core: bool
    error: str = ""


class App:
    """What plugins see as self.app: the content root, the mode, events, and the other plugins.

    mode is "cli" (one command, then exit) or "serve" (the dashboard server: intervals run)."""

    def __init__(self, root: Path | None = None, mode: str = "cli", config_dir: Path | None = None,
                 core_dir: Path | None = None):
        self._root = root
        self.mode = mode
        self.config_dir = config_dir or config.config_path().parent
        self.core_dir = core_dir or CORE_DIR
        self.tick = 5.0  # how often interval threads look at the clock
        self.plugins: dict[str, Plugin] = {}
        self.errors: dict[str, str] = {}
        self._commands: dict[str, Command] = {}
        self._routes: dict[tuple[str, str, str], Callable] = {}
        self._handlers: dict[str, list] = {}
        self._lock = threading.RLock()
        self.version = __version__

    # -- the content root: resolved on first use (the CLI sets it once --root is parsed)
    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = config.content_root()[0]
        return self._root

    def set_root(self, root: Path) -> None:
        self._root = root

    def log(self, message: str) -> None:
        print(f"qap: {message}", file=sys.stderr, flush=True)

    # -- discovery and the enabled list
    def found(self) -> dict[str, Found]:
        out: dict[str, Found] = {}
        for base, core in ((self.core_dir, True), (self.config_dir / "plugins", False)):
            if not base.is_dir():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
                if not (folder / "manifest.json").is_file():
                    continue  # e.g. the data folder of a core plugin
                try:
                    m = Manifest.read(folder)
                except PluginError as e:
                    out.setdefault(folder.name, Found(None, folder, core, str(e)))
                    continue
                if not core and m.id != folder.name:
                    out.setdefault(folder.name, Found(None, folder, core,
                                                      f"its folder must be named after its id ({m.id})"))
                    continue
                if m.id in out:
                    continue  # a core plugin keeps its id
                out[m.id] = Found(m, folder, core)
        return out

    def _state_path(self) -> Path:
        return self.config_dir / "plugins.json"

    def _state(self) -> dict:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data.get("enabled", {}) if isinstance(data, dict) and isinstance(data.get("enabled"), dict) else {}

    def is_enabled(self, pid: str, found: Found) -> bool:
        return bool(self._state().get(pid, found.core))  # core plugins default on, community ones off

    def _save_enabled(self, pid: str, on: bool) -> None:
        state = self._state()
        state[pid] = on
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_path()
        tmp = path.with_name("plugins.json.tmp")
        tmp.write_text(json.dumps({"enabled": state}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def compatible(m: Manifest) -> bool:
        return version_tuple(m.min_app_version) <= version_tuple(__version__)

    # -- loading
    def load_enabled(self) -> None:
        for pid, f in self.found().items():
            if f.manifest and self.is_enabled(pid, f):
                self.load(pid, f)

    def load(self, pid: str, f: Found | None = None) -> Plugin | None:
        with self._lock:
            if pid in self.plugins:
                return self.plugins[pid]
            f = f or self.found().get(pid)
            if not f or not f.manifest:
                raise PluginError(f"no plugin {pid!r} (see `qap plugins list`)")
            if not self.compatible(f.manifest):
                self.errors[pid] = f"needs qap {f.manifest.min_app_version} or later (this is {__version__})"
                return None
            try:
                cls = self._import(f)
                plugin = cls(self, f.manifest, f.folder, f.core)
                self.plugins[pid] = plugin
                plugin.onload()
            except Exception as e:  # a broken plugin must never break qap
                self.errors[pid] = f"{type(e).__name__}: {e}"
                self.log(f"plugin {pid} failed to load: {e}")
                if pid in self.plugins:
                    self._cleanup(self.plugins.pop(pid))
                return None
            self.errors.pop(pid, None)
            return plugin

    def _import(self, f: Found) -> type:
        m = f.manifest
        main = (f.folder / m.main).resolve()
        if f.folder.resolve() not in main.parents or not main.is_file():
            raise PluginError(f"main module {m.main!r} not found in {f.folder}")
        name = "qap_plugin_" + m.id.replace("-", "_")
        spec = importlib.util.spec_from_file_location(name, main, submodule_search_locations=[str(f.folder)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # lets the plugin import its own files: from .helpers import x
        spec.loader.exec_module(module)
        classes = [v for v in vars(module).values()
                   if isinstance(v, type) and issubclass(v, Plugin) and v is not Plugin and v.__module__ == name]
        if len(classes) != 1:
            raise PluginError(f"{main} must define exactly one Plugin subclass (found {len(classes)})")
        return classes[0]

    def _cleanup(self, plugin: Plugin) -> None:
        for undo in reversed(plugin._cleanups):
            try:
                undo()
            except Exception:
                pass
        plugin._cleanups.clear()

    def unload(self, pid: str) -> None:
        with self._lock:
            plugin = self.plugins.pop(pid, None)
            if not plugin:
                return
            self._safely(pid, "onunload", plugin.onunload)
            self._cleanup(plugin)

    def unload_all(self) -> None:
        for pid in list(self.plugins):
            self.unload(pid)

    def enable(self, pid: str) -> Plugin | None:
        f = self.found().get(pid)
        if not f or not f.manifest:
            raise PluginError(f"no plugin {pid!r}" + (f": {f.error}" if f and f.error else " (see `qap plugins list`)"))
        if not self.compatible(f.manifest):
            raise PluginError(f"{pid} needs qap {f.manifest.min_app_version} or later (this is {__version__})")
        self._save_enabled(pid, True)
        return self.load(pid, f)

    def disable(self, pid: str) -> None:
        if pid not in self.found():
            raise PluginError(f"no plugin {pid!r} (see `qap plugins list`)")
        self._save_enabled(pid, False)
        self.unload(pid)

    def get(self, pid: str) -> Plugin:
        if pid not in self.plugins:
            raise PluginError(f"plugin {pid!r} is not enabled (`qap plugins enable {pid}`)")
        return self.plugins[pid]

    # -- events, commands, routes
    def _safely(self, pid: str, what: str, fn: Callable, *args) -> Any:
        try:
            return fn(*args)
        except Exception as e:
            self.log(f"plugin {pid}: {what} failed: {type(e).__name__}: {e}")
            if os.environ.get("QAP_DEBUG"):
                traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def emit(self, event: str, payload: dict | None = None) -> dict[str, dict]:
        """Call every handler of `event`; returns {plugin id: what its handler returned} (None left out).
        A handler that raises is logged and reported as {"ok": False, "error": ...}; the others still run."""
        payload = {"root": str(self.root), "mode": self.mode, **(payload or {})}
        results = {}
        for pid, handler in list(self._handlers.get(event, [])):
            out = self._safely(pid, f"{event} handler", handler, payload)
            if out is not None:
                results[pid] = out
        return results

    def commands(self) -> list[Command]:
        return list(self._commands.values())  # in the order the plugins added them

    def run_command(self, full_id: str, values: dict | None = None, source: str = "cli",
                    json_out: bool = False, interactive: bool = False) -> dict:
        cmd = self._commands.get(full_id)
        if not cmd:
            raise PluginError(f"no command {full_id!r}")
        if source == "dashboard" and not cmd.dashboard:
            raise PluginError(f"{full_id} runs from the CLI only")
        opts = {**cmd.defaults(), **(values or {})}
        result = cmd.callback(SimpleNamespace(**opts, source=source, json=json_out, interactive=interactive))
        return {"ok": True, **(result or {})}

    def route(self, pid: str, method: str, path: str) -> Callable | None:
        return self._routes.get((pid, method, path))

    # -- what `qap plugins list` and GET /api/plugins show
    def describe(self) -> list[dict]:
        out = []
        for pid, f in sorted(self.found().items(), key=lambda kv: (not kv[1].core, kv[0])):
            m = f.manifest
            plugin = self.plugins.get(pid)
            item = {"id": pid, "core": f.core, "folder": str(f.folder), "loaded": plugin is not None,
                    "enabled": bool(m) and self.is_enabled(pid, f), "error": f.error or self.errors.get(pid, "")}
            if m:
                item.update(name=m.name, version=m.version, minAppVersion=m.min_app_version,
                            description=m.description, author=m.author, authorUrl=m.author_url,
                            compatible=self.compatible(m))
                web = {k: f"/plugins/{pid}/{v}" for k, v in m.web.items()} if plugin else {}
                item["web"] = web
            if plugin:
                values = plugin.settings
                item["settings"] = [s.describe(values[k]) for k, s in plugin._settings.items()]
                item["commands"] = [{"id": c.id, "name": c.name, "cli": "qap " + " ".join(c.cli),
                                     "dashboard": c.dashboard, "needs_input": c.needs_input}
                                    for c in self.commands() if c.plugin == pid]
            out.append(item)
        return out

    # -- install / remove community plugins
    def install(self, source: str, link: bool = False) -> Found:
        """Copy (or with link=True symlink) a plugin folder, or clone a git URL, into ~/.config/qap/plugins.
        The plugin stays disabled until `qap plugins enable <id>`."""
        target_base = self.config_dir / "plugins"
        target_base.mkdir(parents=True, exist_ok=True)
        local = Path(source).expanduser()
        if local.is_dir():
            m = Manifest.read(local)
            dest = target_base / m.id
            if dest.exists() or dest.is_symlink():
                raise PluginError(f"{m.id} is already installed at {dest} (`qap plugins remove {m.id}` first)")
            if m.id in self.found() and self.found()[m.id].core:
                raise PluginError(f"{m.id} is the id of a core plugin")
            if link:
                dest.symlink_to(local.resolve(), target_is_directory=True)
            else:
                shutil.copytree(local, dest, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            return Found(m, dest, False)
        if link:
            raise PluginError("--link needs a local folder")
        tmp = target_base / f".clone-{os.getpid()}"
        proc = subprocess.run(["git", "clone", "--depth", "1", "--quiet", source, str(tmp)],
                              capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if proc.returncode:
            shutil.rmtree(tmp, ignore_errors=True)
            raise PluginError(f"git clone {source} failed: {proc.stderr.strip()}")
        try:
            m = Manifest.read(tmp)
            dest = target_base / m.id
            if dest.exists() or (m.id in self.found() and self.found()[m.id].core):
                raise PluginError(f"{m.id} is already installed (or is a core plugin)")
            tmp.rename(dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return Found(m, dest, False)

    def remove(self, pid: str) -> Path:
        f = self.found().get(pid)
        if not f:
            raise PluginError(f"no plugin {pid!r}")
        if f.core:
            raise PluginError(f"{pid} is a core plugin: disable it instead (`qap plugins disable {pid}`)")
        self.unload(pid)
        if f.folder.is_symlink():
            f.folder.unlink()
        else:
            shutil.rmtree(f.folder)
        state = self._state()
        if pid in state:
            state.pop(pid)
            self._state_path().write_text(json.dumps({"enabled": state}, indent=2) + "\n", encoding="utf-8")
        return f.folder
