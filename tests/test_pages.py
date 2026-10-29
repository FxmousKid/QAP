"""carry.py folds messages, check.py lints a built page, seed_first fills the template."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qap import skill  # noqa: E402


def _load(name: str):
    path = ROOT / "skill" / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"qa_pass_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


carry = _load("carry.py")
check = _load("check.py")

USER = """<div class="msg user" id="p1-1u" data-pass="1"><div class="who">Me</div>
  <p>Open one.</p>
  <div class="call"><p>Nested call.</p></div>
</div>"""
AI = """<div class="msg ai" id="p1-1a" data-pass="1" title="a > b and a literal </div>"><div class="who">AI</div>
  <p>Open two. <!-- </div> --> still this message.</p>
</div>"""
P2_USER = '<div class="msg user" id="p2-1u"><div class="who">Me</div><p>Leave me.</p></div>'
P2_AI = '<div class="msg ai" id="p2-1a"><div class="who">AI</div><p>Leave me too.</p></div>'


def source() -> str:
    return (
        "<!doctype html>\n<html><head>\n"
        '<meta name="qa-project" content="billing">\n'
        '<meta name="qa-pass" content="1">\n'
        "<title>T</title>\n</head><body><main>\n"
        '<h2 id="p1" title="a > b"><span class="n">01</span>First</h2>\n'
        '<span class="chip">open</span>\n'
        f"{USER}\n{AI}\n"
        '<h2 id="p2">Second</h2>\n'
        f"{P2_USER}\n{P2_AI}\n"
        "</main></body></html>\n"
    )


SOUND = """<!doctype html><html><head><title>T</title></head><body>
<button id="toc-toggle" type="button"></button>
<button id="stars-open" type="button"></button>
<button id="theme-toggle" type="button"></button>
<nav id="toc-list"></nav>
<main>
<h2 id="p1">First</h2>
<div class="msg user" id="p1-1u"><div class="who">Me</div><p>Hi.</p></div>
<div class="msg ai" id="p1-1a"><div class="who"><span class="ai-label">Claude</span></div><p>Hello.</p></div>
</main>
<footer><span id="env"></span></footer>
</body></html>
"""


class Carry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_carry(self, *extra: str) -> str:
        prev = self.dir / "QA-PASS-1.src.html"
        nxt = self.dir / "QA-PASS-2.src.html"
        prev.write_text(source(), encoding="utf-8")
        argv = ["carry.py", str(prev), str(nxt), "--pass", "2", *extra]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(carry.main(), 0)
        return nxt.read_text(encoding="utf-8")

    def test_open_messages_move_byte_for_byte_into_the_fold(self):
        text = self.run_carry()
        p1 = text.split('<h2 id="p2">', 1)[0]
        details = p1.split('<details class="earlier">', 1)[1].split("</details>", 1)[0]
        self.assertIn(USER + "\n" + AI, details)
        self.assertEqual(text.count(USER), 1)
        self.assertEqual(text.count(AI), 1)
        self.assertLess(p1.index('<span class="chip">open</span>'), p1.index('<details class="earlier">'))
        self.assertIn('id="p1-2u"', p1)
        self.assertIn('id="p1-2a"', p1)
        self.assertIn("{{TODO:the user's reply, verbatim}}", p1)
        self.assertIn("{{TODO:your answer}}", p1)
        self.assertIn('<meta name="qa-pass" content="2">', text)
        self.assertIn('title="a > b"', p1.split("<details", 1)[0])

    def test_a_comment_and_a_quoted_gt_do_not_end_a_message(self):
        text = self.run_carry()
        p1 = text.split('<h2 id="p2">', 1)[0]
        details = p1.split('<details class="earlier">', 1)[1].split("</details>", 1)[0]
        self.assertIn(AI, details)
        self.assertIn("still this message.", details)
        self.assertEqual(text.count("still this message."), 1)
        self.assertIn("Nested call.", details)
        bad = '<h2 id="p9">Nine</h2>\n<div class="msg user" id="p9-1u"><p>no close\n'
        with self.assertRaises(SystemExit) as caught:
            carry.carry_section(bad, "p9", 2, "claude|Claude|Opus 5.5")
        self.assertIn("unbalanced", str(caught.exception))

    def test_skip_keeps_the_round_open_and_stars_are_seeded(self):
        stars = self.dir / "stars.txt"
        stars.write_text("keep #p1-1a\nand p1-1u\n", encoding="utf-8")
        text = self.run_carry("--skip", "p2", "--stars", str(stars))
        p2 = text.split('<h2 id="p2">', 1)[1]
        self.assertNotIn("<details", p2)
        self.assertIn(P2_USER, p2)
        self.assertIn(P2_AI, p2)
        self.assertNotIn("p2-2u", text)
        self.assertIn("<details class=\"earlier\">", text.split('<h2 id="p2">', 1)[0])
        self.assertIn('<meta name="qa-stars-seed" content="p1-1a,p1-1u">', text)
        self.assertIn('<meta name="qa-pass" content="2">', text)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, html: str) -> tuple[int, str]:
        path = self.dir / "QA-PASS-1.html"
        path.write_text(html, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check.main(str(path))
        return code, buf.getvalue()

    def test_decision_codes_match_the_table(self):
        self.assertGreaterEqual(len(check.EXAMPLES), 10)
        for text, expected in check.EXAMPLES:
            self.assertEqual(check.decision_codes(text), list(expected), text)

    def test_problems_fail_and_a_sound_page_does_not(self):
        code, out = self.run_check(SOUND)
        self.assertEqual(code, 0, out)
        self.assertNotIn("PROBLEM", out)
        self.assertIn("warning", out)  # a page with no figure warns; a warning does not fail the check

        code, out = self.run_check(SOUND.replace(' id="p1-1u"', "", 1))
        self.assertEqual(code, 1)
        self.assertIn("without an id", out)

        code, out = self.run_check(SOUND.replace("<p>Hi.</p>", "<p>{{TODO:fill}}</p>", 1))
        self.assertEqual(code, 1)
        self.assertIn("placeholders", out)

        code, out = self.run_check(SOUND.replace("<p>Hi.</p>", '<p><a href="#missing">gone</a></p>', 1))
        self.assertEqual(code, 1)
        self.assertIn("#missing", out)


class Seed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "QA-PASS-1.src.html"

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_the_three_template_slots_are_filled(self):
        skill.seed_first(self.dest, "billing", 1)
        text = self.dest.read_text(encoding="utf-8")
        self.assertIn('<meta name="qa-project" content="billing">', text)
        self.assertIn("<title>billing \u2014 Q&amp;A pass 1</title>", text)
        self.assertIn(">billing \u00b7 conversation, not a spec</div>", text)
        self.assertIn('<meta name="qa-pass" content="1">', text)
        self.assertIn("pass 1 \u00b7", text)
        self.assertNotRegex(text, r"\bPROJECT\b")

        skill.seed_first(self.dest, 'a"b<c', 2)
        text = self.dest.read_text(encoding="utf-8")
        escaped = "a&quot;b&lt;c"
        self.assertIn(f'content="{escaped}"', text)
        self.assertIn(f"<title>{escaped} \u2014", text)
        self.assertIn(f">{escaped} \u00b7", text)
        self.assertNotIn('a"b<c', text)
        self.assertIn('<meta name="qa-pass" content="2">', text)

        skill.seed_first(self.dest, "bill&ing", 3)
        text = self.dest.read_text(encoding="utf-8")
        self.assertIn("bill&amp;ing", text)
        self.assertNotIn("bill&ing", text)

        from qap import config
        original = (config.skill_dir()[0] / "template" / "QA-PASS.src.html").read_text(encoding="utf-8")

        def planted(text: str) -> Path:
            root = self.dest.parent / "skill"
            (root / "template").mkdir(parents=True, exist_ok=True)
            (root / "template" / "QA-PASS.src.html").write_text(text, encoding="utf-8")
            return root

        with mock.patch("qap.skill.config.skill_dir", return_value=(planted("<html>no slots</html>"), "test")):
            with self.assertRaises(ValueError) as missing:
                skill.seed_first(self.dest, "billing", 1)
        self.assertIn('content="PROJECT"', str(missing.exception))

        with mock.patch("qap.skill.config.skill_dir",
                        return_value=(planted(original + "\n<!-- PROJECT -->\n"), "test")):
            with self.assertRaises(ValueError) as extra:
                skill.seed_first(self.dest, "billing", 1)
        self.assertIn("still contains PROJECT", str(extra.exception))


if __name__ == "__main__":
    unittest.main()
