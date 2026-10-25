"""Layout functions on a fixture tree in a temp dir: parsing, the tree, resolve, and every mutation."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import layout as L, passes as P  # noqa: E402

PAGE = '<!doctype html><html><head><meta name="qa-project" content="{p}"><title>T</title></head>' \
       '<body><h1>Q&amp;A pass {n} — {t}</h1></body></html>'


def page(path: Path, n: int, project: str = "proj", title: str = "topic") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.format(p=project, n=n, t=title), encoding="utf-8")
    return path


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "content"
        r = self.root
        # db/ (folder.json, order 1) holds two subjects; authz/rbac has 3 old-format passes; misc/ is implicit
        (r / "db").mkdir(parents=True)
        L.write_json(r / "db" / "folder.json", {"title": "DB migration", "icon": "🗄️", "order": 1})
        for name, project in (("interaction", "v3-interaction"), ("signal", "v3-signal")):
            (r / "db" / name).mkdir(parents=True)
            L.write_json(r / "db" / name / "subject.json", {"title": name.title(), "icon": "💬",
                                                             "qa_project": project, "sources": []})
        for n in (1, 2, 3):
            page(r / "db/interaction" / f"QA-PASS-{n}.html", n, "v3-interaction")
            (r / "db/interaction" / f"QA-PASS-{n}.src.html").write_text(
                PAGE.format(p="v3-interaction", n=n, t="src"), encoding="utf-8")
        (r / "db/interaction/QA-PASS-1.msg.src.html").write_text("x", encoding="utf-8")
        (r / "db/interaction/notes.md").write_text("not a pass", encoding="utf-8")
        page(r / "db/signal/QA-PASS-1.html", 1, "v3-signal")
        (r / "authz/rbac").mkdir(parents=True)
        L.write_json(r / "authz" / "folder.json", {"title": "Authorization", "order": 2})
        L.write_json(r / "authz/rbac/subject.json", {"title": "RBAC", "icon": "🔑", "qa_project": None,
                                                     "sources": []})
        for n in (1, 2, 10):
            page(r / "authz/rbac" / f"QA-PASS-{n}.html", n, "")
        page(r / "authz/rbac/QA-PASS-11-org-units.html", 11, "")
        (r / "authz/rbac/drawio-tables.html").write_text("<h1>not a pass</h1>", encoding="utf-8")
        page(r / "misc/loose/QA-PASS-1.html", 1, "loose")  # no subject.json: an implicit subject

    def tearDown(self):
        self.tmp.cleanup()


class Passes(unittest.TestCase):
    def test_parse_name(self):
        self.assertEqual(P.parse_name("QA-PASS-3.src.html"), {"n": 3, "tag": "", "ext": "src.html"})
        self.assertEqual(P.parse_name("QA-PASS-3.html"), {"n": 3, "tag": "", "ext": "html"})
        self.assertEqual(P.parse_name("QA-PASS-1.msg.src.html")["tag"], ".msg")
        self.assertEqual(P.parse_name("QA-PASS-42-org-units.html")["n"], 42)
        self.assertEqual(P.parse_name("QA-PASS.md"), {"n": None, "tag": "", "ext": "md"})
        self.assertIsNone(P.parse_name("drawio-tables.html"))
        self.assertIsNone(P.parse_name("QA-PASS-1.png"))


class Reading(Fixture):
    def test_list_passes_order_pairs_and_titles(self):
        ps = P.list_passes(self.root / "authz/rbac")
        self.assertEqual([p["label"] for p in ps], ["1", "2", "10", "11-org-units"])
        self.assertEqual(ps[0]["title"], "Q&A pass 1 — topic")
        inter = P.list_passes(self.root / "db/interaction")
        self.assertEqual([(p["file"], p["src"]) for p in inter],
                         [(f"QA-PASS-{n}.html", f"QA-PASS-{n}.src.html") for n in (1, 2, 3)])

    def test_next_pass(self):
        nxt = P.next_pass(self.root / "db/interaction")
        self.assertEqual(nxt["n"], 4)
        self.assertTrue(nxt["carry_from"].endswith("QA-PASS-3.src.html"))
        self.assertEqual(P.next_pass(self.root / "authz/rbac")["n"], 12)
        self.assertIsNone(P.next_pass(self.root / "authz/rbac")["carry_from"])

    def test_tree_kinds_order_and_counts(self):
        t = L.tree(self.root)
        self.assertEqual([c["path"] for c in t["children"]], ["db", "authz", "misc"])
        db = t["children"][0]
        self.assertEqual((db["kind"], db["title"], db["subjects"]), ("folder", "DB migration", 2))
        rbac = t["children"][1]["children"][0]
        self.assertEqual((rbac["kind"], rbac["count"], rbac["latest"], rbac["qa_project"]),
                         ("subject", 4, "11-org-units", ""))
        loose = t["children"][2]["children"][0]
        self.assertTrue(loose["implicit"])
        self.assertEqual(loose["qa_project"], "loose")

    def test_order_list_in_parent(self):
        L.write_json(self.root / "db/folder.json", {"title": "DB", "order": ["signal", "interaction"]})
        db = L.resolve(self.root, "db", "folder")
        self.assertEqual([c["name"] for c in db["children"]], ["signal", "interaction"])

    def test_resolve(self):
        self.assertEqual(L.resolve(self.root, "db/interaction")["path"], "db/interaction")
        self.assertEqual(L.resolve(self.root, "interaction")["path"], "db/interaction")
        self.assertEqual(L.resolve(self.root, "v3-signal")["path"], "db/signal")
        self.assertEqual(L.resolve(self.root, "rbac", "subject")["path"], "authz/rbac")
        with self.assertRaises(L.LayoutError):
            L.resolve(self.root, "nothing-like-this")
        with self.assertRaises(L.LayoutError):
            L.resolve(self.root, "db", "subject")

    def test_clean_rel(self):
        self.assertEqual(L.clean_rel("/db//interaction/"), "db/interaction")
        for bad in ("../x", "db/../..", ".git", "db/img", "a/.hidden"):
            with self.assertRaises(L.LayoutError):
                L.clean_rel(bad)


class Writing(Fixture):
    def test_make_folder_and_subject(self):
        L.make_folder(self.root, "work/billing", title="Billing", icon="money")
        self.assertEqual(L.read_json(self.root / "work/billing/folder.json"), {"title": "Billing", "icon": "money"})
        node = L.make_subject(self.root, "work/billing/invoices", title="Invoices", qa_project="inv")
        self.assertEqual(node["path"], "work/billing/invoices")
        meta = L.read_json(self.root / "work/billing/invoices/subject.json")
        self.assertEqual((meta["title"], meta["qa_project"], meta["sources"]), ("Invoices", "inv", []))
        self.assertTrue((self.root / "work/billing/invoices/img").is_dir())
        with self.assertRaises(L.LayoutError):
            L.make_subject(self.root, "db/interaction/nested")
        with self.assertRaises(L.LayoutError):
            L.make_folder(self.root, "db/interaction/inside")
        with self.assertRaises(L.LayoutError):
            L.make_folder(self.root, "work")

    def test_remove_folder_only_when_empty(self):
        L.make_folder(self.root, "tmp-folder", title="Tmp")
        with self.assertRaises(L.LayoutError):
            L.remove_folder(self.root, "db")  # holds subjects
        with self.assertRaises(L.LayoutError):
            L.remove_folder(self.root, "db/interaction")  # a subject
        L.remove_folder(self.root, "tmp-folder")
        self.assertFalse((self.root / "tmp-folder").exists())

    def test_set_meta(self):
        L.set_meta(self.root, "db", title="DB v3", icon="database", color="#123456")
        self.assertEqual(L.read_json(self.root / "db/folder.json")["title"], "DB v3")
        L.set_meta(self.root, "db/signal", icon="")
        self.assertNotIn("icon", L.read_json(self.root / "db/signal/subject.json"))
        with self.assertRaises(L.LayoutError):
            L.set_meta(self.root, "db/signal", order=3)

    def test_move_into_folder_rename_and_refusals(self):
        L.make_folder(self.root, "work")
        res = L.move(self.root, "db/signal", "work")
        self.assertEqual(res["path"], "work/signal")
        self.assertTrue((self.root / "work/signal/QA-PASS-1.html").is_file())
        res = L.move(self.root, "work/signal", "work/signal-v3")  # a new path: move and rename
        self.assertEqual(res["path"], "work/signal-v3")
        with self.assertRaises(L.LayoutError):
            L.move(self.root, "work", "")  # already at the top
        with self.assertRaises(L.LayoutError):
            L.move(self.root, "db", "db/interaction")  # into a subject
        L.make_folder(self.root, "db/sub")
        with self.assertRaises(L.LayoutError):
            L.move(self.root, "db", "db/sub")  # into itself
        with self.assertRaises(L.LayoutError):
            L.move(self.root, "authz/rbac", "nowhere/deep/x")

    def test_move_updates_order_lists(self):
        L.write_json(self.root / "db/folder.json", {"title": "DB", "order": ["signal", "interaction"]})
        L.make_folder(self.root, "work")
        L.write_json(self.root / "work/folder.json", {"order": []})
        L.move(self.root, "db/signal", "work")
        self.assertEqual(L.read_json(self.root / "db/folder.json")["order"], ["interaction"])
        self.assertEqual(L.read_json(self.root / "work/folder.json")["order"], ["signal"])

    def test_move_relinks_old_locations(self):
        # an old choices/ folder that became a symlink, and an old folder holding per-file symlinks
        old = self.base / "old"
        old.mkdir()
        os.symlink(self.root / "db/interaction", old / "choices")
        (old / "rbac-choices").mkdir()
        os.symlink(self.root / "authz/rbac/QA-PASS-1.html", old / "rbac-choices/QA-PASS-1.html")
        (old / "rbac-choices/README.md").write_text("stays", encoding="utf-8")
        L.set_meta(self.root, "db/interaction", title="Interaction")
        meta = L.read_json(self.root / "db/interaction/subject.json")
        meta["sources"] = [str(old / "choices")]
        L.write_json(self.root / "db/interaction/subject.json", meta)
        meta = L.read_json(self.root / "authz/rbac/subject.json")
        meta["sources"] = [str(old / "rbac-choices")]
        L.write_json(self.root / "authz/rbac/subject.json", meta)
        L.make_folder(self.root, "work")
        res = L.move(self.root, "db", "work")
        self.assertEqual(len(res["relinked"]), 1)
        self.assertEqual(os.readlink(old / "choices"), str(self.root / "work/db/interaction"))
        self.assertTrue((old / "choices" / "QA-PASS-3.html").is_file())
        res = L.move(self.root, "authz", "work")
        self.assertEqual(os.readlink(old / "rbac-choices/QA-PASS-1.html"),
                         str(self.root / "work/authz/rbac/QA-PASS-1.html"))
        self.assertTrue((old / "rbac-choices/QA-PASS-1.html").is_file())

    def test_place_folder_leaves_a_link(self):
        old = self.base / "elsewhere/choices"
        page(old / "QA-PASS-1.html", 1, "ext")
        (old / "QA-PASS-1.src.html").write_text("src {{IMG:a.png}}", encoding="utf-8")
        (old / "img").mkdir()
        (old / "img/a.png").write_bytes(b"png")
        res = L.place(self.root, old, "coach/extension", create=True, title="Extension")
        self.assertTrue(old.is_symlink())
        self.assertEqual(Path(os.readlink(old)), self.root / "coach/extension")
        self.assertTrue((self.root / "coach/extension/img/a.png").is_file())
        meta = L.read_json(self.root / "coach/extension/subject.json")
        self.assertEqual((meta["title"], meta["qa_project"], meta["sources"]), ("Extension", "ext", [str(old)]))
        self.assertEqual(len(res["moved"]), 3)

    def test_place_file_with_pair_images_and_renumber(self):
        src_dir = self.base / "draft"
        page(src_dir / "QA-PASS-1.html", 1)
        (src_dir / "QA-PASS-1.src.html").write_text('<meta name="qa-pass" content="1"> {{IMG:c.png}}',
                                                    encoding="utf-8")
        (src_dir / "img").mkdir()
        (src_dir / "img/c.png").write_bytes(b"c")
        with self.assertRaises(L.LayoutError):
            L.place(self.root, src_dir / "QA-PASS-1.src.html", "db/interaction")  # number taken
        res = L.place(self.root, src_dir / "QA-PASS-1.src.html", "db/interaction", as_n=4)
        d = self.root / "db/interaction"
        self.assertEqual(sorted(Path(m).name for m in res["moved"]), ["QA-PASS-4.html", "QA-PASS-4.src.html"])
        self.assertIn('content="4"', (d / "QA-PASS-4.src.html").read_text())
        self.assertTrue((d / "img/c.png").is_file())
        self.assertTrue((src_dir / "img/c.png").is_file())  # images are copied, others may use them
        self.assertEqual(res["links"], [])
        with self.assertRaises(L.LayoutError):
            L.place(self.root, src_dir / "notes.txt", "db/interaction")

    def test_place_needs_an_existing_subject_unless_create(self):
        f = page(self.base / "x/QA-PASS-1.html", 1)
        with self.assertRaises(L.LayoutError):
            L.place(self.root, f, "nowhere/new")


if __name__ == "__main__":
    unittest.main()
