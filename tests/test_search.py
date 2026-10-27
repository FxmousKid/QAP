"""Search: the index the server builds (qap.search) and the ranking the browser runs on it (web/fuzzy.js, run
with node; skipped when node is missing)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import layout as L, search  # noqa: E402

FUZZY = Path(__file__).resolve().parents[1] / "src" / "qap" / "web" / "fuzzy.js"
NODE = shutil.which("node")


def page(n: int, h1: str, sections: str = "") -> str:
    return (f'<!doctype html><html><head><meta name="qa-project" content="p"><title>T</title></head><body><main>'
            f'<header><div class="kicker">billing · conversation, not a spec</div><h1>Q&amp;A pass {n} — {h1}</h1>'
            f'</header>{sections}</main></body></html>')


class Index(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        L.make_folder(self.root, "pay", title="Payments", icon="money")
        L.make_subject(self.root, "pay/retries", title="Payment retries", icon="chart", qa_project="demo-retries")
        d = self.root / "pay/retries"
        (d / "QA-PASS-1.html").write_text(page(1, "how often to retry"), encoding="utf-8")
        (d / "QA-PASS-2.src.html").write_text(page(2, "the schedule", '<h2 id="p1"><span class="n">01</span>'
                                                                   "Stop after the third retry</h2>"), encoding="utf-8")
        (d / "QA-PASS-2.html").write_text(page(2, "the schedule"), encoding="utf-8")  # sections come from the source
        L.make_subject(self.root, "loose", title="Loose subject")

    def tearDown(self):
        self.tmp.cleanup()

    def test_items_without_projects(self):
        data = search.build(self.root)
        kinds = [(i["kind"], i["key"]) for i in data["items"]]
        self.assertEqual(kinds, [("folder", "pay"), ("subject", "pay/retries"), ("pass", "pay/retries#1"),
                                 ("pass", "pay/retries#2"), ("subject", "loose")])
        self.assertEqual(data["projects"], 0)
        p2 = data["items"][3]
        self.assertEqual((p2["title"], p2["label"], p2["latest"], p2["href"]),
                         ("The schedule", "2", True, "#/pay/retries?pass=2"))
        self.assertEqual(p2["crumbs"], ["Payments", "Payment retries"])
        self.assertEqual(p2["sections"], [{"id": "p1", "num": "01", "title": "Stop after the third retry"}])
        self.assertEqual(p2["kicker"], "billing · conversation, not a spec")
        self.assertEqual((p2["icon"], p2["name"]), ("chart", "retries"))  # the subject's box

    def test_items_with_projects(self):
        L.make_project(self.root, "work", title="Work")
        L.make_project(self.root, "personal", title="Personal")
        L.assign_project(self.root, "loose", "personal")
        items = {i["key"]: i for i in search.build(self.root)["items"]}
        self.assertEqual((items["@work"]["kind"], items["@work"]["href"], items["@work"]["count"]), ("project", "#/@work", 1))
        self.assertEqual(items["pay"]["crumbs"], ["Work"])
        self.assertEqual(items["pay/retries#1"]["crumbs"], ["Work", "Payments", "Payment retries"])
        self.assertEqual((items["loose"]["crumbs"], items["loose"]["project"]), (["Personal"], "personal"))

    def test_pass_title_prefix(self):
        self.assertEqual(search.pass_title("Q&A pass 12 — the plan, costed"), "The plan, costed")
        self.assertEqual(search.pass_title("Q&A pass 42-org-units: org units"), "Org units")
        self.assertEqual(search.pass_title("A title without the prefix"), "A title without the prefix")
        self.assertEqual(search.pass_title(""), "")


@unittest.skipUnless(NODE, "node is not installed")
class Ranking(unittest.TestCase):
    """fuzzy.js, the browser's ranking, on fixed items."""

    ITEMS = [
        {"kind": "project", "title": "Work", "name": "work", "crumbs": []},
        {"kind": "folder", "title": "Data Warehouse", "name": "warehouse", "crumbs": ["Work"]},
        {"kind": "folder", "title": "DB migration v3", "name": "db-migration-v3", "crumbs": ["Work"]},
        {"kind": "subject", "title": "INV-204 numbering", "name": "inv204-numbering", "qa_project": "inv204",
         "crumbs": ["Work", "Data Warehouse"]},
        {"kind": "subject", "title": "Payment retries", "name": "payment-retries", "crumbs": ["Work", "Payments"]},
        {"kind": "subject", "title": "Équipe commerciale", "name": "equipe", "crumbs": ["Work"]},
        {"kind": "pass", "title": "The indexing plan", "label": "3", "latest": True,
         "crumbs": ["Work", "Data Warehouse", "INV-204 numbering"],
         "sections": [{"id": "p5", "num": "05", "title": "We go with the Flex tier"}]},
        {"kind": "pass", "title": "Dates", "label": "13", "crumbs": ["Work", "Data Warehouse", "INV-204 numbering"],
         "sections": [{"id": "p1", "num": "01", "title": "Measured on 2026-10-03"}]},
    ]

    def rank(self, *queries: str) -> dict:
        script = f"""
import {{ prepare, search }} from {json.dumps(FUZZY.as_uri())};
const items = prepare({json.dumps(self.ITEMS)});
const out = {{}};
for (const q of {json.dumps(list(queries))}) {{
  out[q] = search(items, q, Date.parse("2026-10-28")).map((r) => ({{
    title: r.item.title, kind: r.item.kind,
    section: (r.hits.find((h) => h.field.key === "section") || {{ field: {{}} }}).field.text || null }}));
}}
console.log(JSON.stringify(out));
"""
        res = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def titles(self, rows):
        return [r["title"] for r in rows]

    def test_ranking(self):
        r = self.rank("warehouse", "inv 204", "inv204", "flex", "migartion", "dbmig", "retry", "equipe", "3", "wrk",
                      "zzqx", "data warehuose")
        self.assertEqual(r["warehouse"][0]["title"], "Data Warehouse")
        self.assertEqual(self.titles(r["inv 204"])[:2], ["INV-204 numbering", "The indexing plan"])
        self.assertEqual(r["inv204"][0]["title"], "INV-204 numbering")  # separators do not matter
        self.assertEqual((r["flex"][0]["title"], r["flex"][0]["section"]), ("The indexing plan", "We go with the Flex tier"))
        self.assertEqual(r["migartion"][0]["title"], "DB migration v3")  # one swapped pair of letters
        self.assertEqual(r["dbmig"][0]["title"], "DB migration v3")
        self.assertEqual(r["retry"][0]["title"], "Payment retries")  # a plural
        self.assertEqual(r["equipe"][0]["title"], "Équipe commerciale")  # accents
        self.assertEqual(r["3"][0]["title"], "The indexing plan")  # pass 3 first ("v3" holds a 3 too)
        self.assertNotIn("Dates", self.titles(r["3"]))  # a whole number: not pass 13, not 2026-10-03
        self.assertEqual(r["wrk"][0]["kind"], "project")
        self.assertEqual(r["zzqx"], [])
        self.assertEqual(r["data warehuose"][0]["title"], "Data Warehouse")  # every word must match, typos allowed


if __name__ == "__main__":
    unittest.main()
