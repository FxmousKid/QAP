"""The CLI (--json, non-interactive) and the HTTP server (routes, guards, the write API) on a fixture."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

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
