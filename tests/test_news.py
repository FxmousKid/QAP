"""build.py: what moved since the last pass is stamped on each subject's h2 of the built page."""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "scripts" / "build.py"
_spec = importlib.util.spec_from_file_location("qa_pass_build_news", SCRIPT)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def msg(sid: str, n: int, kind: str, body: str = "<p>text</p>") -> str:
    return (f'<div class="msg {kind}" id="{sid}-{n}{kind[0]}" data-pass="{n}"><div class="who">x</div>'
            f'{body}</div>\n')


DECISION_S = '<div class="call violet" id="dec-s"><h4>Decision S: where a chart\'s numbers come from</h4><p>S1</p></div>'
DECISION_E1 = '<div class="call violet"><h4>Decision <b>E1-how</b>: lifting the limit</h4></div>'
PLAIN_CALL = '<div class="call"><h4>Decision Z: only a note, not violet</h4></div>'

# Pass 5: subject 1 unchanged since pass 3 (in a fold), subject 2 a new round asking S, subject 3 opened in this
# pass and asking R (its user message has no data-pass: the id says 5), subject 4 an old decision box of pass 4.
SOURCE = (
    '<html><head><meta name="qa-pass" content="5"></head><body><main>\n'
    '<h2 id="p1"><span class="n">01</span>Old</h2>\n<details class="earlier"><summary>Earlier</summary>\n'
    + msg("p1", 2, "user") + msg("p1", 3, "ai") + "</details>\n"
    '<h2 id="p2"><span class="n">02</span>Round</h2>\n<details class="earlier"><summary>Earlier</summary>\n'
    + msg("p2", 4, "ai", DECISION_S.replace("S:", "Q:")) + "</details>\n"
    + msg("p2", 5, "user") + msg("p2", 5, "ai", f"<p>a</p>{DECISION_S}{PLAIN_CALL}")
    + '<h2 id="p3"><span class="n">03</span>New</h2>\n'
    '<div class="msg user" id="p3-5u"><div class="who">Me</div><p>new topic</p></div>\n'
    + msg("p3", 5, "ai", '<div class="call violet"><h4>Decision R: how to rebuild</h4></div>' + DECISION_E1)
    + '<h2 id="p4"><span class="n">04</span>Skipped</h2>\n' + msg("p4", 4, "ai", DECISION_S)
    + '<h2 id="need"><span class="n">05</span>What I need from you</h2>\n<ol><li>R</li><li>S</li><li>K</li></ol>\n'
    "</main></body></html>"
)


def h2(html: str, sid: str) -> str:
    return re.search(rf'<h2 id="{sid}"[^>]*>', html).group(0)


class WhatMoved(unittest.TestCase):
    def test_new_subject_new_round_and_unchanged_since(self):
        out, counts = build.stamp_news(SOURCE, 5)
        self.assertEqual(h2(out, "p1"), '<h2 id="p1" data-since="3">')
        self.assertEqual(h2(out, "p2"), '<h2 id="p2" data-new="round" data-since="5" data-asks="S">')
        self.assertEqual(h2(out, "p3"), '<h2 id="p3" data-new="subject" data-since="5" data-asks="R E1">')
        self.assertEqual(h2(out, "p4"), '<h2 id="p4" data-since="4">')
        self.assertEqual(h2(out, "need"), '<h2 id="need" data-items="3">')
        self.assertEqual((counts["subject"], counts["round"], counts["unchanged"], counts["asks"]), (1, 1, 2, 2))

    def test_only_the_marks_change_and_a_built_page_builds_the_same(self):
        out, _ = build.stamp_news(SOURCE, 5)
        self.assertEqual(build.NEWS_ATTR.sub("", out), SOURCE)
        self.assertEqual(build.stamp_news(out, 5)[0], out)

    def test_pass_one_and_an_unknown_pass_get_nothing(self):
        for current in (1, None):
            out, counts = build.stamp_news(SOURCE, current)
            self.assertEqual(out, SOURCE)
            self.assertFalse(counts)

    def test_build_stamps_the_page_but_never_the_source(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "QA-PASS-5.src.html"
            src.write_text(SOURCE, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                build.build(src, Path(tmp) / "QA-PASS-5.html")
            self.assertEqual(src.read_text(encoding="utf-8"), SOURCE)
            self.assertIn('data-new="subject"', (Path(tmp) / "QA-PASS-5.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
