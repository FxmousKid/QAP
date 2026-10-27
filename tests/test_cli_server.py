"""The CLI (--json, non-interactive) and the HTTP server (routes, guards, the write API) on a fixture."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import cli, layout as L, server  # noqa: E402


def run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, json.loads(out.getvalue() or "{}")


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, *argv):
        return run(*argv, "--root", str(self.root), "--json")

    def test_flow(self):
        code, out = self.q("new-subject", "work/billing", "--title", "Billing", "--icon", "money",
                           "--qa-project", "billing")
        self.assertEqual((code, out["subject"], out["next"]["n"]), (0, "work/billing", 1))
        code, out = self.q("carry", "billing")  # no pass yet: pass 1 from the template
        self.assertEqual(code, 0, out)
        src = Path(out["src"])
        self.assertEqual(src.name, "QA-PASS-1.src.html")
        text = src.read_text()
        self.assertIn('<meta name="qa-project" content="billing">', text)
        self.assertIn('<meta name="qa-pass" content="1">', text)
        code, out = self.q("next", "work/billing")
        self.assertEqual(out["n"], 2)
        code, out = self.q("mkdir", "archive", "--title", "Archive", "--icon", "📦")
        self.assertEqual(code, 0)
        code, out = self.q("mv", "work/billing", "archive")
        self.assertEqual(out["path"], "archive/billing")
        code, out = self.q("list")
        paths = [c["path"] for c in out["tree"]["children"]]
        self.assertEqual(paths, ["archive", "work"])
        code, out = self.q("where", "billing")
        self.assertEqual(out["dir"], str(self.root / "archive/billing"))
        code, out = self.q("icon", "archive", "nonsense")
        self.assertEqual((code, out["ok"]), (1, False))
        code, out = self.q("where")  # no subject, not a TTY: a clear error instead of a prompt
        self.assertEqual(code, 1)
        self.assertIn("give a subject", out["error"])

    def test_projects(self):
        self.q("new-subject", "db/interaction", "--title", "Interaction")
        self.q("new-subject", "authz/rbac", "--title", "RBAC")
        code, out = self.q("project")
        self.assertEqual((code, out["projects"]), (0, []))
        code, out = self.q("project", "new", "work", "--title", "Work", "--icon", "briefcase")
        self.assertEqual((code, out["project"]["default"], out["project"]["members"]), (0, True, ["authz", "db"]))
        code, out = self.q("project", "new", "personal", "--title", "Personal", "--icon", "🏡")
        self.assertFalse(out["project"]["default"])
        code, out = self.q("mkdir", "home", "--title", "Home", "--project", "personal")
        self.assertEqual(code, 0)
        code, out = self.q("project", "move", "db/interaction", "personal", "--yes")  # moved up, then in
        self.assertEqual((code, out["path"], out["project"], out["from"]), (0, "interaction", "personal", "db"))
        code, out = self.q("mv", "authz", "@personal", "--yes")  # mv to @project does the same
        self.assertEqual((code, out["from"]), (0, "@work"))
        code, out = self.q("list")
        self.assertEqual([(p["id"], p["members"]) for p in out["projects"]],
                         [("work", ["db"]), ("personal", ["authz", "home", "interaction"])])
        self.assertEqual({c["path"]: c["project"] for c in out["tree"]["children"]}["db"], "work")
        code, out = self.q("rename", "@personal", "Home life")
        self.assertEqual(out["title"], "Home life")
        code, out = self.q("project", "rm", "work", "--yes")
        self.assertEqual(code, 1)  # db is still in it
        self.assertIn("still holds db", out["error"])
        code, out = self.q("project", "set", "personal", "--default")
        self.assertTrue(out["project"]["default"])
        self.assertEqual(L.read_json(self.root / "db/folder.json")["project"], "work")  # pinned: it stays in work
        code, out = self.q("new-subject", "db/billing", "--project", "personal")
        self.assertEqual(code, 1)  # db belongs to work
        code, out = self.q("mkdir", "garden")  # a new family goes to the default project
        self.assertEqual(L.find_project(self.root, "personal")["members"], ["authz", "garden", "home", "interaction"])

    def test_an_unreadable_config_is_reported(self):
        cfg = Path(self.tmp.name) / "cfg"
        (cfg / "qap").mkdir(parents=True)
        (cfg / "qap" / "config.json").write_text("{not json", encoding="utf-8")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(cfg)}):
            code, out = run("config", "--json")
        self.assertEqual(code, 1)
        self.assertIn("cannot read", out["error"])

    def test_build_all_covers_the_whole_root_and_missing_pages(self):
        page = ('<!doctype html><html><head><meta name="qa-pass" content="{n}"><title>T</title></head><body><main>\n'
                '<h1>Q&amp;A pass {n}</h1>\n</main><footer></footer></body></html>\n')
        for path in ("work/billing", "home/roof"):
            self.q("new-subject", path, "--title", path.split("/")[1].title())
            for n in (1, 2):
                (self.root / path / f"QA-PASS-{n}.src.html").write_text(page.format(n=n), encoding="utf-8")
        code, out = self.q("build", "billing", "--pass", "1")
        self.assertEqual(code, 0, out)
        code, out = self.q("build", "--all")  # no subject: every subject; missing pages are built too
        self.assertEqual((code, out["subject"]), (0, ""), out)
        self.assertEqual(sorted(Path(r["html"]).relative_to(self.root).as_posix() for r in out["results"]),
                         ["home/roof/QA-PASS-1.html", "home/roof/QA-PASS-2.html",
                          "work/billing/QA-PASS-1.html", "work/billing/QA-PASS-2.html"])
        self.assertTrue(all((self.root / p / f"QA-PASS-{n}.html").is_file()
                            for p in ("work/billing", "home/roof") for n in (1, 2)))
        self.assertEqual(sum(r["reason"].startswith("built") for r in out["results"]), 3)  # missing: built anyway
        code, out = self.q("build", "--all")  # a page that exists is kept when its rebuild has check problems
        self.assertEqual({r["replaced"] for r in out["results"]}, {False})

    def test_config_reports_root(self):
        code, out = self.q("config")
        self.assertEqual((code, out["content_root"], out["content_root_from"]), (0, str(self.root), "--root"))


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        L.make_subject(self.root, "db/interaction", title="Interaction", qa_project="v3-interaction")
        (self.root / "db/interaction/QA-PASS-1.html").write_text("<h1>Q&amp;A pass 1</h1>", encoding="utf-8")
        self.httpd = server.make_server(self.root, 0)
        self.httpd.RequestHandlerClass.log_message = lambda *a: None
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_routes(self):
        code, body = self.req("/api/tree")
        tree = json.loads(body)["tree"]
        self.assertEqual(tree["children"][0]["children"][0]["passes"][0]["title"], "Q&A pass 1")
        self.assertEqual(self.req("/c/db/interaction/QA-PASS-1.html")[0], 200)
        self.assertEqual(self.req("/")[0], 200)
        self.assertEqual(self.req("/ui/app.js")[0], 200)
        self.assertEqual(self.req("/c/../../etc/passwd")[0], 404)
        self.assertEqual(self.req("/c/db/interaction/subject.json")[0], 200)

    def test_search_index(self):
        code, body = self.req("/api/search")
        data = json.loads(body)
        self.assertEqual((code, data["ok"], data["projects"]), (200, True, 0))
        self.assertEqual([i["kind"] for i in data["items"]], ["folder", "subject", "pass"])
        self.assertEqual(self.req("/ui/search.js")[0], 200)  # pass pages load it from here
        self.assertEqual(self.req("/ui/fuzzy.js")[0], 200)

    def test_project_actions(self):
        code, body = self.req("/api/project", {"title": "Work"})
        self.assertEqual((code, json.loads(body)["path"]), (200, "@work"))
        code, body = self.req("/api/project", {"title": "Personal", "icon": "home"})
        self.assertEqual(json.loads(body)["id"], "personal")
        code, body = self.req("/api/mkdir", {"parent": "@personal", "title": "Home"})
        self.assertEqual(json.loads(body)["path"], "home")
        self.assertEqual(L.read_json(self.root / "home/folder.json")["project"], "personal")
        code, body = self.req("/api/mv", {"src": "db", "dest": "@personal"})
        self.assertEqual((code, json.loads(body)["from"]), (200, "@work"))
        code, body = self.req("/api/mv", {"src": "db", "dest": "@work"})  # what Undo sends
        self.assertEqual(code, 200)
        code, body = self.req("/api/rename", {"path": "@personal", "title": "Home life"})
        self.assertEqual(json.loads(body)["title"], "Home life")
        tree = json.loads(self.req("/api/tree")[1])["tree"]
        self.assertEqual([(p["id"], p["members"]) for p in tree["projects"]], [("work", ["db"]), ("personal", ["home"])])
        self.assertEqual(self.req("/api/rmdir", {"path": "@work"})[0], 400)  # not empty
        code, body = self.req("/api/project", {"title": "Spare"})
        self.assertEqual(self.req("/api/rmdir", {"path": "@spare"})[0], 200)
        self.assertEqual(self.req("/api/project", {"title": "X"}, {"Origin": "http://evil.example"})[0], 403)

    def test_writes_are_guarded_and_work(self):
        self.assertEqual(self.req("/api/mkdir", {"title": "X"}, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/tree", headers={"Host": "evil.example"})[0], 421)
        code, body = self.req("/api/mkdir", {"parent": "", "title": "Work"})
        self.assertEqual((code, json.loads(body)["path"]), (200, "work"))
        code, body = self.req("/api/mkdir", {"parent": "", "title": "Work"})
        self.assertEqual(json.loads(body)["path"], "work-2")  # a free name, not an error
        code, body = self.req("/api/mv", {"src": "db/interaction", "dest": "work"})
        self.assertEqual(json.loads(body)["path"], "work/interaction")
        code, body = self.req("/api/mv", {"src": "work", "dest": "work/interaction"})
        self.assertEqual(code, 400)
        code, body = self.req("/api/icon", {"path": "work", "icon": "🧪", "color": "#0F8B8D"})
        self.assertEqual(json.loads(body)["icon"], "🧪")
        code, body = self.req("/api/rename", {"path": "work/interaction", "title": "Interaction v3"})
        self.assertEqual(L.read_json(self.root / "work/interaction/subject.json")["title"], "Interaction v3")


if __name__ == "__main__":
    unittest.main()
