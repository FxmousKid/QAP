"""git-storage end to end, against LOCAL bare repositories in a temp dir (file:// remotes): set up, restore, the
build / startup / interval triggers, a conflict (stop, show, nothing pushed, resolve), a content root nested in
another repository, an unreachable remote, the dashboard route. Git runs with a throwaway global config
(GIT_CONFIG_GLOBAL), so your identity, signing and hooks are never used and nothing leaves the temp dir."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import cli, layout as L, plugins as PL, server  # noqa: E402

STORE = Path(__file__).resolve().parents[1] / "src/qap/core_plugins/git-storage/store.py"
SOURCE = ('<!doctype html><html><head><meta name="qa-pass" content="{n}"><meta name="qa-project" content="billing">'
          '<title>T</title></head><body><main>\n<h1>Q&amp;A pass {n}</h1>\n<p>{text}</p>\n</main><footer></footer>'
          '</body></html>\n')


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class GitStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        gitconfig = self.base / "gitconfig"
        gitconfig.write_text("[user]\n\tname = QAP Test\n\temail = test@example.com\n"
                             "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
                                                "XDG_CONFIG_HOME": str(self.base / "config")})
        self.env.start()
        self.remote = self.base / "backup.git"
        git(self.base, "init", "--quiet", "--bare", str(self.remote))
        self.url = self.remote.as_uri()  # file:///…/backup.git
        self.a = self.machine("a")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def machine(self, name: str, with_subject: bool = True) -> Path:
        root = self.base / name
        root.mkdir()
        if with_subject:
            L.make_subject(root, "work/billing", title="Billing", qa_project="billing")
            (root / "work/billing/QA-PASS-1.src.html").write_text(SOURCE.format(n=1, text="first"), encoding="utf-8")
        return root

    def q(self, root: Path, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main([*argv, "--root", str(root), "--json"])
        return code, json.loads(out.getvalue() or "{}")

    def remote_log(self) -> list[str]:
        return git(self.remote, "log", "--format=%s", "main").splitlines()

    def plugin(self, root: Path, mode: str = "cli") -> PL.Plugin:
        app = PL.App(root, mode=mode)
        app.load_enabled()
        return app.get("git-storage")

    # ------------------------------------------------------------------ set up, restore, triggers
    def test_init_pushes_everything_and_restore_fills_an_empty_root(self):
        code, out = self.q(self.a, "storage", "git", "init", "--remote", self.url)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.a / ".gitignore").is_file())
        self.assertEqual(len(self.remote_log()), 1)
        self.assertIn("work/billing", self.remote_log()[0])
        files = git(self.remote, "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertEqual(sorted(files), [".gitignore", "work/billing/QA-PASS-1.src.html", "work/billing/subject.json"])

        b = self.machine("b", with_subject=False)
        code, out = self.q(b, "storage", "git", "init", "--remote", self.url)
        self.assertEqual((code, out.get("restored")), (0, True), out)
        self.assertEqual((b / "work/billing/QA-PASS-1.src.html").read_text(), SOURCE.format(n=1, text="first"))
        code, out = self.q(b, "list")
        self.assertEqual(out["tree"]["children"][0]["children"][0]["title"], "Billing")

    def test_build_startup_and_interval_sync(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        (self.a / "work/billing/QA-PASS-1.src.html").write_text(SOURCE.format(n=1, text="edited"), encoding="utf-8")
        code, out = self.q(self.a, "build", "billing")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["plugins"]["git-storage"]["ok"], out)
        self.assertEqual(self.remote_log()[0], "qap build: work/billing (2 files, " +
                         self.remote_log()[0].split(", ")[-1])  # the source and the built page
        self.assertIn("QA-PASS-1.html", git(self.remote, "ls-tree", "-r", "--name-only", "main"))

        # another machine pushes; "startup" (qap serve) brings it in
        b = self.base / "b"
        git(self.base, "clone", "--quiet", self.url, str(b))
        (b / "work/billing/notes.md").write_text("from b\n", encoding="utf-8")
        git(b, "add", "-A")
        git(b, "commit", "--quiet", "-m", "from b")
        git(b, "push", "--quiet")
        plugin = self.plugin(self.a, "serve")
        with contextlib.redirect_stderr(io.StringIO()):  # both log a line, as under `qap serve`
            plugin.on_startup({})
        self.assertEqual((self.a / "work/billing/notes.md").read_text(), "from b\n")

        # the interval: commits and pushes what changed since
        L.make_folder(self.a, "archive", title="Archive")
        with contextlib.redirect_stderr(io.StringIO()):
            plugin.on_interval()
        self.assertTrue(self.remote_log()[0].startswith("qap interval: archive"))
        plugin.app.unload_all()

    def test_message_template_and_no_push(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        self.q(self.a, "plugins", "config", "git-storage", "commit_message", "backup {{numFiles}} on {{trigger}}")
        self.q(self.a, "plugins", "config", "git-storage", "push", "false")
        L.make_folder(self.a, "archive", title="Archive")
        code, out = self.q(self.a, "storage", "git", "sync")
        self.assertEqual((code, out["pushed"]), (0, 0), out)
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), "backup 1 on manual")
        self.assertEqual(len(self.remote_log()), 1)  # nothing left the machine
        code, out = self.q(self.a, "storage", "git", "status")
        self.assertEqual((out["ahead"], out["changed"]), (1, 0))

    # ------------------------------------------------------------------ conflicts: stop, show, resolve
    def test_conflict_stops_shows_and_resolves(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        b = self.machine("b", with_subject=False)
        self.q(b, "storage", "git", "init", "--remote", self.url)
        page = "work/billing/QA-PASS-1.src.html"
        (self.a / page).write_text(SOURCE.format(n=1, text="from a"), encoding="utf-8")
        (b / page).write_text(SOURCE.format(n=1, text="from b"), encoding="utf-8")
        self.assertEqual(self.q(self.a, "storage", "git", "sync")[0], 0)
        remote_head = git(self.remote, "rev-parse", "main")

        code, out = self.q(b, "storage", "git", "sync")
        self.assertEqual(code, 1)
        self.assertEqual(out["conflict"]["files"], [page])
        self.assertEqual(git(self.remote, "rev-parse", "main"), remote_head)  # nothing pushed
        self.assertIn("from b", (b / page).read_text())
        self.assertNotIn("<<<<<<<", (b / page).read_text())  # the merge was undone: no markers in a pass
        self.assertEqual(git(b, "status", "--porcelain"), "")
        self.assertFalse((b / ".git/MERGE_HEAD").exists())

        # automatic syncs are paused while the conflict stands
        result = self.plugin(b).on_build({"subject": "work/billing", "ok": True})
        self.assertEqual(result["skipped"], "conflict")
        code, out = self.q(b, "storage", "git", "status")
        self.assertEqual(out["conflict"]["files"], [page])

        code, out = self.q(b, "storage", "git", "resolve", "--theirs")
        self.assertEqual(code, 0, out)
        self.assertIn("from a", (b / page).read_text())
        mine = out["other"]
        self.assertIn("from b", git(b, "show", f"{mine}:{page}"))  # the side not kept stays in history
        self.assertIsNone(self.q(b, "storage", "git", "status")[1]["conflict"])
        self.assertEqual(self.q(self.a, "storage", "git", "sync")[0], 0)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), git(self.remote, "rev-parse", "main"))

    def test_rebase_method_and_keep_mine(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        b = self.machine("b", with_subject=False)
        self.q(b, "storage", "git", "init", "--remote", self.url)
        self.q(b, "plugins", "config", "git-storage", "sync_method", "rebase")
        (self.a / "work/billing/a.md").write_text("a\n", encoding="utf-8")
        (b / "work/billing/b.md").write_text("b\n", encoding="utf-8")
        self.q(self.a, "storage", "git", "sync")
        code, out = self.q(b, "storage", "git", "sync")
        self.assertEqual((code, out["pulled"], out["pushed"]), (0, 1, 1), out)
        self.assertEqual(git(b, "log", "--format=%P", "-1").count(" "), 0)  # linear: no merge commit
        page = "work/billing/QA-PASS-1.src.html"
        (self.a / page).write_text(SOURCE.format(n=1, text="from a"), encoding="utf-8")
        (b / page).write_text(SOURCE.format(n=1, text="from b"), encoding="utf-8")
        self.q(self.a, "storage", "git", "sync")
        self.assertEqual(self.q(b, "storage", "git", "sync")[0], 1)
        self.assertFalse((b / ".git/rebase-merge").exists())
        code, out = self.q(b, "storage", "git", "resolve", "--mine")
        self.assertEqual(code, 0, out)
        self.assertIn("from b", git(self.remote, "show", f"main:{page}"))

    # ------------------------------------------------------------------ edges
    def test_a_content_root_inside_another_repository(self):
        parent = self.base / "parent"
        parent.mkdir()
        git(parent, "init", "--quiet")
        (parent / "README").write_text("parent\n", encoding="utf-8")
        root = parent / "contents"
        L.make_subject(root, "x/y", title="Y")
        code, out = self.q(root, "storage", "git", "status")
        self.assertFalse(out["repo"])
        self.assertEqual(out["parent_repo"], str(parent))
        code, out = self.q(root, "storage", "git", "init", "--remote", self.url)
        self.assertEqual(code, 0, out)
        self.assertTrue(any("add 'contents/'" in n for n in out["notes"]))
        self.assertEqual(git(parent, "status", "--porcelain"), "?? README\n?? contents/".strip())
        self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=parent, capture_output=True).returncode, 128)

    def test_unreachable_remote_and_a_different_remote(self):
        missing = (self.base / "nowhere.git").as_uri()
        code, out = self.q(self.a, "storage", "git", "init", "--remote", missing)
        self.assertEqual(code, 1)
        self.assertIn("out of reach", out["text"])
        L.make_folder(self.a, "archive", title="Archive")
        code, out = self.q(self.a, "storage", "git", "sync")
        self.assertEqual(code, 1)
        self.assertTrue(out["committed"], out)  # committed here: nothing lost while offline
        code, out = self.q(self.a, "storage", "git", "init", "--remote", self.url)
        self.assertEqual(code, 1)
        self.assertIn("already points at", out["error"])
        self.assertEqual(git(self.a, "remote", "get-url", "origin"), missing)  # qap never rewrites a remote

    def test_not_set_up_means_inert(self):
        self.assertIsNone(self.plugin(self.a).on_build({"subject": "work/billing", "ok": True}))
        code, out = self.q(self.a, "storage", "git", "sync")
        self.assertEqual(code, 1)
        self.assertIn("not backed up with git yet", out["error"])
        self.assertFalse((self.a / ".git").exists())

    def test_status_warns_about_links_out_of_the_root(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        outside = self.base / "elsewhere.md"
        outside.write_text("x\n", encoding="utf-8")
        (self.a / "work/billing/linked.md").symlink_to(outside)
        code, out = self.q(self.a, "storage", "git", "status")
        self.assertTrue(any("symlink" in w for w in out["warnings"]), out["warnings"])

    def test_dashboard_route_and_run(self):
        self.q(self.a, "storage", "git", "init", "--remote", self.url)
        app = PL.App(self.a, mode="serve")
        app.load_enabled()
        httpd = server.make_server(self.a, 0, app)
        httpd.RequestHandlerClass.log_message = lambda *a: None
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/plugins/git-storage/status") as r:
                status = json.loads(r.read())
            self.assertEqual((status["initialized"], status["upstream"], status["ahead"]), (True, "origin/main", 0))
            L.make_folder(self.a, "archive", title="Archive")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/plugins/git-storage/run/sync", data=b"{}",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                out = json.loads(r.read())
            self.assertEqual((out["ok"], out["pushed"]), (True, 1), out)
        finally:
            httpd.shutdown()
            httpd.server_close()
            app.unload_all()

    def test_never_force_pushes(self):
        code = STORE.read_text(encoding="utf-8")
        self.assertNotIn("--force", code)
        self.assertNotIn('"-f"', code)
        self.assertNotIn("+HEAD", code)


if __name__ == "__main__":
    unittest.main()
