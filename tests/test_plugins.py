"""The plugin host: manifests, discovery, enable / disable, what onload registers and what unload removes, events,
intervals, the CLI (`qap plugins …` and plugin commands) and the server's plugin routes. Everything runs against a
temp config dir (XDG_CONFIG_HOME), so the real ~/.config/qap is never read or written."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import cli, layout as L, plugins as PL, server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "plugins" / "build-log"

COUNTER = '''
from qap.plugins import Plugin, Setting

class Counter(Plugin):
    ticks = 0

    def onload(self):
        self.add_settings(Setting("step", "Step", 1), Setting("mode", "Mode", "a", choices=("a", "b")))
        self.add_command("bump", "Bump", self.bump, cli="counter bump",
                         args=[(["--by"], {"type": int, "default": 1})])
        self.add_command("list", "Taken word", self.bump, cli="list")  # `qap list` is qap's own: left out
        self.register_event("pass_built", lambda p: {"text": f"counter heard {p['subject']}"})
        self.register_route("GET", "hello", lambda body: {"hello": body.get("name", "world")})
        self.register_interval(0.05, self.tick)

    def tick(self):
        type(self).ticks += 1

    def bump(self, opts):
        return {"by": opts.by * self.settings["step"], "source": opts.source, "text": f"bumped {opts.by}"}
'''


def make_plugin(base: Path, pid: str, body: str = COUNTER, **manifest) -> Path:
    folder = base / pid
    folder.mkdir(parents=True)
    data = {"id": pid, "name": pid.title(), "version": "1.0.0", "minAppVersion": "0.1.0",
            "description": f"the {pid} test plugin", **manifest}
    (folder / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (folder / "main.py").write_text(body, encoding="utf-8")
    return folder


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base / "config")})
        self.env.start()
        self.config = self.base / "config" / "qap"
        self.root = self.base / "content"
        L.make_subject(self.root, "work/billing", title="Billing", qa_project="billing")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def app(self, mode="cli") -> PL.App:
        app = PL.App(self.root, mode=mode)
        app.tick = 0.01
        return app

    def q(self, *argv) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main([*argv, "--root", str(self.root), "--json"])
        return code, json.loads(out.getvalue() or "{}")


class Manifests(Base):
    def test_rules(self):
        good = make_plugin(self.base / "x", "fine-one")
        self.assertEqual(PL.Manifest.read(good).id, "fine-one")
        for pid, extra, message in (("Bad_Id", {}, "lowercase"), ("v", {"version": "1.0"}, "x.y.z"),
                                    ("w", {"description": ""}, "missing description")):
            folder = make_plugin(self.base / "y", pid, **extra)
            with self.assertRaisesRegex(PL.PluginError, message):
                PL.Manifest.read(folder)

    def test_folder_must_match_id_and_too_new_plugins_stay_off(self):
        plugins = self.config / "plugins"
        make_plugin(plugins, "counter")
        wrong = make_plugin(plugins, "named-wrong")
        data = json.loads((wrong / "manifest.json").read_text())
        data["id"] = "other"
        (wrong / "manifest.json").write_text(json.dumps(data))
        make_plugin(plugins, "future", minAppVersion="99.0.0")
        app = self.app()
        found = app.found()
        self.assertIn("git-storage", found)
        self.assertTrue(found["git-storage"].core)
        self.assertIn("folder must be named after its id", found["named-wrong"].error)
        with self.assertRaisesRegex(PL.PluginError, "needs qap 99.0.0"):
            app.enable("future")


class Lifecycle(Base):
    def setUp(self):
        super().setUp()
        make_plugin(self.config / "plugins", "counter")

    def test_community_plugins_start_off_core_ones_on(self):
        app = self.app()
        app.load_enabled()
        self.assertEqual(set(app.plugins), {"git-storage"})
        app.enable("counter")
        self.assertIn("counter:bump", app._commands)
        self.assertTrue(json.loads((self.config / "plugins.json").read_text())["enabled"]["counter"])
        fresh = self.app()
        fresh.load_enabled()
        self.assertEqual(set(fresh.plugins), {"git-storage", "counter"})
        fresh.disable("git-storage")
        self.assertNotIn("git-storage:sync", fresh._commands)

    def test_unload_removes_everything_onload_added(self):
        app = self.app("serve")
        app.enable("counter")
        self.assertTrue(app.route("counter", "GET", "hello"))
        self.assertEqual(len(app._handlers["pass_built"]), 1)
        time.sleep(0.15)
        self.assertGreater(app.plugins["counter"].ticks, 0)  # serve mode: the interval runs
        app.disable("counter")
        self.assertEqual((app._commands.get("counter:bump"), app.route("counter", "GET", "hello"),
                          app._handlers["pass_built"]), (None, None, []))
        time.sleep(0.05)  # a tick already running when the plugin went off may still land
        ticks = sys.modules["qap_plugin_counter"].Counter.ticks
        time.sleep(0.1)
        self.assertEqual(sys.modules["qap_plugin_counter"].Counter.ticks, ticks)  # the interval stopped

    def test_intervals_never_run_in_a_cli_process(self):
        app = self.app("cli")
        app.enable("counter")
        sys.modules["qap_plugin_counter"].Counter.ticks = 0
        time.sleep(0.1)
        self.assertEqual(sys.modules["qap_plugin_counter"].Counter.ticks, 0)

    def test_a_broken_plugin_never_breaks_qap(self):
        make_plugin(self.config / "plugins", "broken", body="from qap.plugins import Plugin\n"
                    "class Broken(Plugin):\n    def onload(self):\n        raise RuntimeError('boom')\n")
        make_plugin(self.config / "plugins", "loud", body="from qap.plugins import Plugin\n"
                    "class Loud(Plugin):\n    def onload(self):\n"
                    "        self.register_event('content_changed', lambda p: 1 / 0)\n")
        app = self.app()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(app.enable("broken"))
            app.enable("loud")
            results = app.emit("content_changed", {"action": "mkdir"})
        self.assertIn("boom", app.errors["broken"])
        self.assertNotIn("broken", app.plugins)
        self.assertEqual(results["loud"]["ok"], False)
        code, out = self.q("mkdir", "archive", "--title", "Archive")  # qap itself still works
        self.assertEqual((code, out["folder"]), (0, "archive"))

    def test_settings_are_typed_and_saved_per_plugin(self):
        app = self.app()
        plugin = app.enable("counter")
        self.assertEqual(plugin.settings, {"step": 1, "mode": "a"})
        self.assertEqual(plugin.set_setting("step", "3"), 3)
        with self.assertRaisesRegex(PL.PluginError, "one of a, b"):
            plugin.set_setting("mode", "c")
        with self.assertRaisesRegex(PL.PluginError, "no setting"):
            plugin.set_setting("nope", 1)
        data = json.loads((self.config / "plugins" / "counter" / "data.json").read_text())
        self.assertEqual(data["settings"], {"step": 3})


class Cli(Base):
    def test_plugin_commands_and_events_through_the_cli(self):
        make_plugin(self.config / "plugins", "counter")
        code, out = self.q("plugins", "enable", "counter")
        self.assertEqual(code, 0, out)
        code, out = self.q("counter", "bump", "--by", "4")
        self.assertEqual((code, out["by"], out["source"]), (0, 4, "cli"))
        code, out = self.q("plugins", "config", "counter", "step", "2")
        self.assertEqual(out["settings"][0]["value"], 2)
        code, out = self.q("counter", "bump", "--by", "4")
        self.assertEqual(out["by"], 8)
        code, out = self.q("list")  # still qap's own list: the plugin's `list` was refused
        self.assertIn("tree", out)
        src = self.root / "work/billing/QA-PASS-1.src.html"
        src.write_text('<!doctype html><html><head><meta name="qa-pass" content="1"><title>T</title></head><body>'
                       '<main><h1>Q&amp;A pass 1</h1></main><footer></footer></body></html>\n', encoding="utf-8")
        code, out = self.q("build", "billing")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["plugins"]["counter"]["text"], "counter heard work/billing")
        code, out = self.q("plugins", "list")
        mine = next(p for p in out["plugins"] if p["id"] == "counter")
        self.assertEqual([c["cli"] for c in mine["commands"]], ["qap counter bump", "qap list"])

    def test_install_example_enable_and_remove(self):
        code, out = self.q("plugins", "install", str(EXAMPLE))
        self.assertEqual((code, out["enabled"]), (0, False))
        code, out = self.q("plugins", "enable", "build-log")
        self.assertEqual(code, 0, out)
        self.q("mkdir", "archive", "--title", "Archive")
        self.q("mv", "work/billing", "archive")
        code, out = self.q("build-log", "show")
        self.assertEqual([e["event"] for e in out["entries"]], ["mkdir", "mv"])
        code, out = self.q("plugins", "remove", "build-log", "--yes")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.config / "plugins" / "build-log").exists())
        code, out = self.q("plugins", "remove", "git-storage")
        self.assertIn("core plugin", out["error"])


class ServerRoutes(Base):
    def setUp(self):
        super().setUp()
        make_plugin(self.config / "plugins", "counter", web={"main": "web/main.js"})
        web = self.config / "plugins" / "counter" / "web"
        web.mkdir()
        (web / "main.js").write_text("export function onload(app) {}\n", encoding="utf-8")
        self.application = self.app("serve")
        self.application.load_enabled()
        self.application.enable("counter")
        self.httpd = server.make_server(self.root, 0, self.application)
        self.httpd.RequestHandlerClass.log_message = lambda *a: None
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.application.unload_all()
        super().tearDown()

    def req(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"{}") if "json" in resp.headers["Content-Type"] else None
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def test_list_routes_settings_and_run(self):
        code, out = self.req("/api/plugins")
        ids = {p["id"]: p for p in out["plugins"]}
        self.assertEqual(ids["counter"]["web"], {"main": "/plugins/counter/web/main.js"})
        self.assertEqual(self.req("/plugins/counter/web/main.js")[0], 200)
        self.assertEqual(self.req("/plugins/counter/main.py")[0], 404)  # only the web/ folder is served
        self.assertEqual(self.req("/plugins/counter/web/../main.py")[0], 404)
        self.assertEqual(self.req("/api/plugins/counter/hello?name=qap")[1]["hello"], "qap")
        code, out = self.req("/api/plugins/counter/settings", {"step": 5})
        self.assertEqual((code, out["saved"]), (200, {"step": 5}))
        code, out = self.req("/api/plugins/counter/run/bump", {"by": 2, "ignored": 1})
        self.assertEqual((code, out["by"], out["source"]), (200, 10, "dashboard"))
        code, out = self.req("/api/plugins/counter/settings", {"mode": "z"})
        self.assertEqual(code, 400)

    def test_writes_are_guarded_and_enable_disable_live(self):
        code, _ = self.req("/api/plugins/counter/run/bump", {}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        code, out = self.req("/api/plugins/counter/disable", {})
        self.assertEqual(code, 200)
        self.assertEqual(self.req("/api/plugins/counter/hello")[0], 404)
        self.assertEqual(self.req("/plugins/counter/web/main.js")[0], 404)
        self.req("/api/plugins/counter/enable", {})
        self.assertEqual(self.req("/api/plugins/counter/hello")[0], 200)

    def test_dashboard_writes_fire_content_changed(self):
        heard = []
        self.application._handlers.setdefault("content_changed", []).append(("test", heard.append))
        self.req("/api/mkdir", {"parent": "", "title": "Archive"})
        self.assertEqual([(h["action"], h["source"]) for h in heard], [("mkdir", "dashboard")])


if __name__ == "__main__":
    unittest.main()
