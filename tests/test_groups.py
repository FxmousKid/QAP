"""Batches: the triage reading, qap split, the board's lanes, session events, the ledger and notes between groups."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import cli, groups as G, layout as L, server  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"

TRIAGE = """<!doctype html><html><head><meta name="qa-project" content="night-2-triage">
<meta name="qa-kind" content="triage"></head><body><main>
<h2 id="g-re" class="grp" data-lane="session" data-group="reanalysis"
    data-owns="MeetingListViewModel.kt; the analysis read policy" data-waits="">Re-analysis: what is current</h2>
<p class="goal">Every viewer sees the newest analysis's state.</p>
<h2 id="p4"><span class="n">04</span>A re-analysis shows the old summary</h2>
<h2 id="p11"><span class="n">11</span>A session in analysis opens</h2>
<h2 id="g-lists" class="grp" data-lane="session" data-group="phone-lists" data-owns="the list reconciliation"
    data-waits="reanalysis">Session lists on the phones</h2>
<p class="goal">The phones list the same sessions as the web.</p>
<h2 id="p6"><span class="n">06</span>A deleted session stays listed</h2>
<h2 id="g-fast" class="grp" data-lane="fast">Fast lane</h2>
<h2 id="p1"><span class="n">01</span>Analyses after the first one fail</h2>
<h2 id="g-info" class="grp" data-lane="info">Nothing to change</h2>
<h2 id="p9"><span class="n">09</span>The disk was full</h2>
<h2 id="need"><span class="n">10</span>What I need from you</h2>
</main></body></html>"""


def triage_read(html: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html)
    try:
        out = subprocess.run([sys.executable, str(SCRIPTS / "triage.py"), f.name], capture_output=True, text=True)
        return json.loads(out.stdout)
    finally:
        Path(f.name).unlink()


def check(html: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html)
    try:
        out = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), f.name], capture_output=True, text=True)
        return out.returncode, out.stdout
    finally:
        Path(f.name).unlink()


class Triage(unittest.TestCase):
    def test_topics_sit_under_their_group_in_page_order(self):
        data = triage_read(TRIAGE)
        self.assertEqual(data["problems"], [])
        self.assertEqual([(g["lane"], g["name"], [t["id"] for t in g["topics"]]) for g in data["groups"]],
                         [("session", "reanalysis", ["p4", "p11"]), ("session", "phone-lists", ["p6"]),
                          ("fast", "", ["p1"]), ("info", "", ["p9"])])
        self.assertEqual(data["groups"][0]["goal"], "Every viewer sees the newest analysis's state.")
        self.assertEqual(data["groups"][0]["owns"], ["MeetingListViewModel.kt", "the analysis read policy"])
        self.assertEqual(data["groups"][0]["topics"][0]["title"], "A re-analysis shows the old summary")

    def test_check_fails_a_triage_pass_with_a_topic_in_no_group_or_a_file_with_two_owners(self):
        loose = TRIAGE.replace('<main>', '<main><h2 id="p2"><span class="n">02</span>Loose</h2>', 1)
        code, out = check(loose)
        self.assertEqual(code, 1)
        self.assertIn("1 topic(s) in no group: ['p2']", out)
        shared = TRIAGE.replace('data-owns="the list reconciliation"', 'data-owns="MeetingListViewModel.kt"', 1)
        code, out = check(shared)
        self.assertEqual(code, 1)
        self.assertIn("'MeetingListViewModel.kt' is owned by two groups (reanalysis and phone-lists)", out)
        waits = TRIAGE.replace('data-waits="reanalysis"', 'data-waits="nobody"', 1)
        self.assertIn("phone-lists waits for 'nobody'", check(waits)[1])

    def test_a_triage_pass_with_fewer_than_two_session_groups_is_one_ordinary_pass(self):
        one = TRIAGE.replace('data-lane="session" data-group="phone-lists"', 'data-lane="fast" data-group=""', 1)
        problems = " ".join(triage_read(one)["problems"])
        self.assertIn("1 session group(s): a batch is for at least two independent problems", problems)
        self.assertEqual(check(one)[0], 1)

    def test_groups_that_wait_for_each_other_or_take_a_reserved_name_are_refused(self):
        circle = TRIAGE.replace('data-waits=""', 'data-waits="phone-lists"', 1)
        self.assertIn("the groups wait for each other in a circle", " ".join(triage_read(circle)["problems"]))
        named = TRIAGE.replace('data-group="phone-lists"', 'data-group="triage"', 1)
        self.assertIn("other than img, node_modules, triage", " ".join(triage_read(named)["problems"]))

    def test_a_topic_after_a_section_that_is_not_a_topic_belongs_to_no_group(self):
        late = TRIAGE.replace("</main>", '<h2 id="p12"><span class="n">12</span>Late topic</h2></main>', 1)
        self.assertEqual(triage_read(late)["loose"], ["p12"])

    def test_an_ordinary_pass_is_not_held_to_the_triage_rules(self):
        plain = TRIAGE.replace('<meta name="qa-kind" content="triage">', "", 1)
        plain = plain.replace('<main>', '<main><h2 id="p2"><span class="n">02</span>Loose</h2>', 1)
        self.assertEqual(triage_read(plain)["problems"], [])


class Batch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.root.mkdir()
        self.batch = G.make_batch(self.root, "v3/night-2", title="Night 2")["batch"]
        (self.root / self.batch / "triage" / "QA-PASS-1.html").write_text(TRIAGE, encoding="utf-8")
        G.decide(self.root, f"{self.batch}/triage", "No dedicated RPC for a re-analysis", why="overkill",
                 who="Sam", where="Slack, 1 Nov")

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_batch_starts_its_triage_pass_from_the_triage_template(self):
        src = (self.root / self.batch / "triage" / "QA-PASS-1.src.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="qa-kind" content="triage">', src)
        self.assertIn('<meta name="qa-project" content="night-2-triage">', src)

    def test_split_makes_one_subject_per_session_group_and_keeps_what_a_session_wrote(self):
        out = G.split(self.root, self.batch)
        self.assertEqual([g["group"] for g in out["groups"]], ["v3/night-2/reanalysis", "v3/night-2/phone-lists"])
        brief = (self.root / "v3/night-2/reanalysis/brief.md").read_text(encoding="utf-8")
        self.assertIn("lanes/group-session.md", brief)
        self.assertIn("No dedicated RPC for a re-analysis — Sam, Slack, 1 Nov", brief)
        self.assertIn("Do not touch: the list reconciliation (owned by phone-lists)", brief)
        self.assertEqual(G.status(self.root, "v3/night-2/phone-lists")["phase"], "queued")
        # The waiting group is not offered: its owner's PR has not merged.
        self.assertEqual(out["start_now"], ["v3/night-2/reanalysis"])
        self.assertEqual(out["first_prompts"]["v3/night-2/reanalysis"],
                         "You are the session of group v3/night-2/reanalysis (QAP). Read "
                         f"{self.root / 'v3/night-2/reanalysis/brief.md'}.")
        G.set_phase(self.root, "v3/night-2/reanalysis", "plan_agreed")
        (self.root / "v3/night-2/reanalysis/brief.md").write_text("the session's own brief", encoding="utf-8")
        again = G.split(self.root, self.batch)
        self.assertEqual([g["created"] for g in again["groups"]], [False, False])
        self.assertEqual(G.status(self.root, "v3/night-2/reanalysis")["phase"], "plan_agreed")
        self.assertEqual((self.root / "v3/night-2/reanalysis/brief.md").read_text(), "the session's own brief")

    def test_split_refuses_a_triage_pass_with_problems(self):
        page = self.root / self.batch / "triage" / "QA-PASS-1.html"
        page.write_text(TRIAGE.replace('data-group="phone-lists"', 'data-group="Phone Lists"'), encoding="utf-8")
        with self.assertRaises(L.LayoutError):
            G.split(self.root, self.batch)

    def test_the_board_puts_needs_you_first_and_a_hook_event_moves_a_group(self):
        G.split(self.root, self.batch)
        g = "v3/night-2/reanalysis"
        G.record(self.root, g, "spawned", app_id="local_1")
        G.record(self.root, g, "started", session_id="s1")
        self.assertEqual(G.board(self.root, self.batch)["lanes"]["working"], ["reanalysis"])
        G.record(self.root, g, "waiting", text="Round 1 is written.\n\nOne question: B1 or B2?")
        view = G.board(self.root, self.batch)
        self.assertEqual(view["lanes"]["needs_you"], ["reanalysis"])
        self.assertEqual(view["lanes"]["waits"], ["phone-lists"])
        entry = view["groups"][0]
        self.assertEqual((entry["session"]["question"], entry["session"]["app_id"], entry["phase"]),
                         ("Round 1 is written.\n\nOne question: B1 or B2?", "local_1", "planning"))
        # the tile's badge: the items of the latest round's "What I need from you"
        (self.root / g / "QA-PASS-1.html").write_text(
            '<h2 id="need">What I need from you</h2><ol><li id="need-1">A</li><li id="need-2">B</li></ol><ol><li>x</li></ol>',
            encoding="utf-8")
        self.assertEqual(G.board(self.root, self.batch)["groups"][0]["decisions"], 2)
        G.record(self.root, g, "working")  # a note started a turn: it keeps the question once it waits again
        G.record(self.root, g, "waiting")
        self.assertEqual(G.status(self.root, g)["session"]["question"], "Round 1 is written.\n\nOne question: B1 or B2?")
        G.record(self.root, g, "answered")
        self.assertEqual(G.board(self.root, self.batch)["lanes"]["working"], ["reanalysis"])
        G.set_phase(self.root, g, "merged", pr="https://example.test/pr/1")
        view = G.board(self.root, self.batch)
        self.assertEqual((view["lanes"]["done"], view["lanes"]["ready"]), (["reanalysis"], ["phone-lists"]))
        self.assertEqual([e["kind"] for e in G.events(self.root, g)],
                         ["spawned", "started", "waiting", "working", "waiting", "answered", "phase"])

    def test_the_ledger_is_every_decision_of_the_family_and_an_entry_is_never_rewritten(self):
        G.split(self.root, self.batch)
        first = G.decide(self.root, "v3/night-2/reanalysis", "The web shows « Analyse en cours »", who="the user")
        second = G.decide(self.root, "v3/night-2/reanalysis", "No backfill heuristic", who="Sam")
        self.assertEqual((first["id"], second["id"]), ("reanalysis-1", "reanalysis-2"))
        rules = [d["rule"] for d in G.ledger(self.root, "v3")["decisions"]]
        self.assertEqual(sorted(rules), sorted(["No dedicated RPC for a re-analysis",
                                                "The web shows « Analyse en cours »", "No backfill heuristic"]))

    def test_a_note_lands_in_the_other_groups_inbox_and_never_outside_the_batch(self):
        G.split(self.root, self.batch)
        G.tell(self.root, "v3/night-2/reanalysis", "phone-lists", "MeetingListViewModel.kt changes its API")
        notes = G.inbox(self.root, "v3/night-2/phone-lists")
        self.assertEqual([(n["id"], n["from"]) for n in notes], [(1, "v3/night-2/reanalysis")])
        self.assertEqual(G.inbox(self.root, "v3/night-2/phone-lists", after=1), [])
        outside = Path(self.tmp.name) / "outside"
        L.write_json((outside.mkdir() or outside) / "subject.json", {})
        for to in ("../../../outside", str(outside), "triage"):
            with self.assertRaises((L.LayoutError, ValueError)):
                G.tell(self.root, "v3/night-2/reanalysis", to, "hello")
        self.assertFalse((outside / "inbox.jsonl").exists())

    def test_the_brief_keeps_the_case_of_what_another_group_owns_and_the_ledger_counts_past_nine(self):
        G.split(self.root, self.batch)
        brief = (self.root / "v3/night-2/phone-lists/brief.md").read_text(encoding="utf-8")
        self.assertIn("Do not touch: MeetingListViewModel.kt (owned by reanalysis)", brief)
        for i in range(1, 12):
            G.decide(self.root, "v3/night-2/reanalysis", f"rule {i}")
        ids = [d["id"] for d in G.ledger(self.root, "v3")["decisions"] if d["by"].endswith("reanalysis")]
        self.assertEqual(ids[8:11], ["reanalysis-9", "reanalysis-10", "reanalysis-11"])

    def test_a_new_batch_is_the_folder_named_never_a_subject_or_another_folder(self):
        L.make_subject(self.root, "v3/night", title="Night")
        L.make_folder(self.root, "v3/night-old", title="Old nights")
        with self.assertRaises(L.LayoutError):
            G.make_batch(self.root, "v3/night")
        self.assertFalse((self.root / "v3/night-old/batch.json").exists())


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([*argv, "--root", str(self.root), "--json"])
        return code, json.loads(out.getvalue() or "{}")

    def test_the_cli_runs_a_batch_from_the_triage_pass_to_the_board(self):
        code, out = self.q("new-batch", "v3/night-2", "--title", "Night 2")
        self.assertEqual(code, 0, out)
        (self.root / "v3/night-2/triage/QA-PASS-1.html").write_text(TRIAGE, encoding="utf-8")
        code, out = self.q("split", "night-2")
        self.assertEqual((code, out["start_now"]), (0, ["v3/night-2/reanalysis"]))
        code, out = self.q("event", "v3/night-2/reanalysis", "waiting", "--text", "B1 or B2?")
        self.assertEqual(out["session"]["state"], "waiting")
        code, out = self.q("status", "reanalysis", "--phase", "plan_agreed", "--note", "B1")
        self.assertEqual((code, out["phase"]), (0, "plan_agreed"))
        code, out = self.q("board", "night-2")
        self.assertEqual(out["lanes"]["needs_you"], ["reanalysis"])
        code, out = self.q("board")
        self.assertEqual([b["path"] for b in out["batches"]], ["v3/night-2"])

    def test_a_link_to_a_pass_finds_its_subject_its_pass_and_its_batch(self):
        self.q("new-batch", "v3/night-2", "--title", "Night 2")
        page = self.root / "v3/night-2/triage/QA-PASS-1.html"
        page.write_text(TRIAGE, encoding="utf-8")
        links = {
            "http://127.0.0.1:8750/#/v3/night-2/triage?pass=1": "QA-PASS-1.html",
            "http://127.0.0.1:8750/c/v3/night-2/triage/QA-PASS-1.html": "QA-PASS-1.html",
            "http://127.0.0.1:8750/ui/board.html#v3/night-2": None,
            page.as_uri(): "QA-PASS-1.html",
            str(page): "QA-PASS-1.html",
            "https://share.example/u/12/v3/night-2/triage/QA-PASS-1.html": "QA-PASS-1.html",
        }
        for link, file in links.items():
            code, out = self.q("where", link)
            self.assertEqual((code, out["subject"]), (0, "v3/night-2/triage"), link)
            self.assertEqual((out["pass"] or {}).get("file"), file, link)
            # Before the split: the groups the triage pass proposes, at the paths split gives them.
            self.assertEqual([g["path"] for g in out["batch"]["groups"]],
                             ["v3/night-2/reanalysis", "v3/night-2/phone-lists"], link)
            self.assertFalse(out["batch"]["split"])
        self.q("split", "night-2")
        code, out = self.q("where", "http://127.0.0.1:8750/#/v3/night-2/reanalysis")
        self.assertEqual((code, out["subject"], out["batch"]["split"]), (0, "v3/night-2/reanalysis", True))
        self.assertTrue(out["batch"]["groups"][0]["brief"].endswith("v3/night-2/reanalysis/brief.md"))
        code, out = self.q("where", "http://127.0.0.1:8750/#/nowhere/at-all")
        self.assertNotEqual(code, 0)


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.root.mkdir()
        batch = G.make_batch(self.root, "v3/night-2", title="Night 2")["batch"]
        (self.root / batch / "triage" / "QA-PASS-1.html").write_text(TRIAGE, encoding="utf-8")
        G.split(self.root, batch)
        self.httpd = server.make_server(self.root, 0)
        self.httpd.RequestHandlerClass.log_message = lambda *a: None
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_a_hook_event_posted_without_an_origin_moves_the_group_on_the_board(self):
        code, out = self.req("/api/events", {"group": "v3/night-2/reanalysis", "kind": "waiting", "text": "B1 or B2?"})
        self.assertEqual((code, out["session"]["state"]), (200, "waiting"))
        code, out = self.req("/api/board?path=v3/night-2")
        self.assertEqual((code, out["lanes"]["needs_you"]), (200, ["reanalysis"]))
        code, out = self.req("/api/group?path=v3/night-2/reanalysis")
        self.assertEqual([e["kind"] for e in out["events"]], ["waiting"])
        code, out = self.req("/api/events", {"group": "v3/night-2/reanalysis", "kind": "nonsense"})
        self.assertEqual(code, 400)
        code, out = self.req("/api/tell", {"from": "v3/night-2/reanalysis", "to": "phone-lists", "text": "rebase"})
        self.assertEqual((code, out["to"]), (200, "v3/night-2/phone-lists"))
        code, out = self.req("/api/batches")
        self.assertEqual([b["path"] for b in out["batches"]], ["v3/night-2"])


if __name__ == "__main__":
    unittest.main()
