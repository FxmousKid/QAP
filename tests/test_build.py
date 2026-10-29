"""build.py: "need item N" links to the need list of the pass the message belongs to, not always this page's."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "scripts" / "build.py"
_spec = importlib.util.spec_from_file_location("qa_pass_build", SCRIPT)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def need_list(count: int) -> str:
    items = "".join(f'<li id="need-{n}">item {n} of this pass</li>' for n in range(1, count + 1))
    return f'<h2 id="need">What I need from you</h2>\n<ol>{items}</ol>\n'


def page(n: int, body: str, need: str) -> str:
    return (f'<!doctype html><html><head><meta name="qa-pass" content="{n}"><title>T</title></head><body><main>\n'
            f'{body}\n{need}</main><footer></footer></body></html>')


# Pass 4 of a subject: subject 1 has a fold with pass-3 messages (the AI's, and the user's reply to pass 2); subject
# 2 was skipped, so its pass-3 answer is still open; subject 3 has this pass's messages and a pass-0 chat message.
SOURCE = page(4, """
<p class="lede">Read need item 2 first.</p>
<h2 id="p1"><span class="n">01</span>First</h2>
<details class="earlier"><summary>Earlier in this thread</summary>
<div class="msg user" id="p1-3u" data-pass="3"><div class="who">Me</div>
  <p>"A detail choice (need item 12)." : ok</p>
</div>
<div class="msg ai" id="p1-3a" data-pass="3"><div class="who">AI</div>
  <p>Two new findings need you (need items 1 and 11). See subject 02.</p>
  <div class="call"><p>Nested in a box: need item 1.</p></div>
  <p>After the box, still pass 3: need item 3.</p>
</div>
</details>
<div class="msg user" id="p1-4u" data-pass="4"><div class="who">Me</div>
  <p>Already linked by hand: <a href="QA-PASS-3.html#need-1">need item 1</a>.</p>
</div>
<div class="msg ai" id="p1-4a" data-pass="4"><div class="who">AI</div>
  <p>This pass: need item 2.</p>
</div>
<h2 id="p2"><span class="n">02</span>Skipped</h2>
<div class="msg ai" id="p2-3a"><div class="who">AI</div><p>Pass 3, open (no data-pass, from the id): need item 3.</p></div>
<h2 id="p3"><span class="n">03</span>Third</h2>
<details class="earlier"><summary>Earlier in this thread</summary>
<div class="msg ai" id="p3-0a" data-pass="0"><div class="who">AI</div><p>In the chat: need item 1.</p></div>
<div class="msg ai" id="p3-2a" data-pass="2"><div class="who">AI</div><p>Pass 2 had only 14 items: need item 15.</p></div>
</details>
<div class="msg ai" id="p3-4a" data-pass="4"><div class="who">AI</div><p>Back to this pass: need items 1 and 2.</p></div>
""", need_list(2))


class NeedItemsOfEarlierPasses(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.subject = Path(self.tmp.name) / "subject"
        self.subject.mkdir()
        (self.subject / "QA-PASS-2.html").write_text(page(2, "", need_list(14)), encoding="utf-8")
        (self.subject / "QA-PASS-3.html").write_text(page(3, "", need_list(12)), encoding="utf-8")
        self.src = self.subject / "QA-PASS-4.src.html"
        self.src.write_text(SOURCE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def built(self) -> tuple[str, list[str]]:
        html, _, unresolved = build.link_references(build.number_need_items(SOURCE), self.src)
        return html, unresolved

    def test_an_earlier_ai_message_links_to_its_own_pass(self):
        html, _ = self.built()
        self.assertIn('(<a href="QA-PASS-3.html#need-1">need items 1</a> and '
                      '<a href="QA-PASS-3.html#need-11">11</a>)', html)
        self.assertIn('Nested in a box: <a href="QA-PASS-3.html#need-1">need item 1</a>', html)
        self.assertIn('still pass 3: <a href="QA-PASS-3.html#need-3">need item 3</a>', html)
        self.assertIn('See <a href="#p2">subject 02</a>', html)  # subjects keep their ids: this page

    def test_an_earlier_user_message_links_to_the_page_it_answered(self):
        html, _ = self.built()
        self.assertIn('"A detail choice (<a href="QA-PASS-2.html#need-12">need item 12</a>)."', html)

    def test_a_skipped_subjects_open_round_links_to_its_pass(self):
        html, _ = self.built()
        self.assertIn('from the id): <a href="QA-PASS-3.html#need-3">need item 3</a>', html)

    def test_this_pass_and_text_outside_messages_keep_the_local_list(self):
        html, _ = self.built()
        self.assertIn('Read <a href="#need-2">need item 2</a> first.', html)
        self.assertIn('This pass: <a href="#need-2">need item 2</a>.', html)
        self.assertIn('<a href="#need-1">need items 1</a> and <a href="#need-2">2</a>', html)
        self.assertIn('<a href="QA-PASS-3.html#need-1">need item 1</a>.</p>', html)  # a hand link stays as is

    def test_no_link_without_a_target(self):
        html, unresolved = self.built()
        self.assertIn("In the chat: need item 1.", html)
        self.assertIn("only 14 items: need item 15.", html)
        self.assertEqual(sorted(unresolved), ["need item 1 (the chat before pass 1)",
                                              "need item 15 (QA-PASS-2.html)"])
        (self.subject / "QA-PASS-3.html").unlink()  # the earlier page is not built: no link rather than a dead one
        html, unresolved = self.built()
        self.assertIn("(need items 1 and 11)", html)
        self.assertIn("need items 11 (QA-PASS-3.html)", unresolved)

    def test_build_writes_elsewhere_and_builds_the_same_twice(self):
        # qap build --all builds into a temp dir: the earlier pages are found next to the source, not the output.
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "QA-PASS-4.html"
            again = Path(out_dir) / "again.html"
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(build.build(self.src, out), 0)
                self.assertEqual(build.build(out, again), 0)
            self.assertIn("(6 to an earlier pass's page)", printed.getvalue())
            first = out.read_text(encoding="utf-8")
            self.assertIn('<a href="QA-PASS-3.html#need-11">11</a>', first)
            self.assertEqual(again.read_text(encoding="utf-8"), first)

    def test_a_comment_a_pre_and_a_quoted_gt_are_not_linked(self):
        html = page(4, """
<h2 id="p5"><span class="n">05</span>Five</h2>
<!-- subject 05 and need item 1 -->
<pre>subject 05
need item 1</pre>
<p><code>need item 1</code> <span title="need item 9 > still the attribute">see subject 05</span>.</p>
<div class="msg ai" id="p5-3a" data-pass="3" title="a > b"><div class="who">AI</div>
  <p>From pass 3: need item 1.</p>
</div>
""", need_list(2))
        out, _, _ = build.link_references(build.number_need_items(html), self.src)
        self.assertIn("<!-- subject 05 and need item 1 -->", out)
        self.assertIn("<pre>subject 05\nneed item 1</pre>", out)
        self.assertIn("<code>need item 1</code>", out)
        self.assertIn('title="need item 9 > still the attribute"', out)
        self.assertIn('title="a > b"', out)
        self.assertEqual(out.count('href="#p5"'), 1)
        self.assertIn('see <a href="#p5">subject 05</a>', out)
        self.assertEqual(out.count("QA-PASS-3.html#need-1"), 1)
        self.assertIn('From pass 3: <a href="QA-PASS-3.html#need-1">need item 1</a>.', out)
        self.assertNotIn('href="#need-1"', out)

    def test_without_a_pass_number_every_reference_is_local(self):
        html, _, _ = build.link_references(build.number_need_items(SOURCE.replace(
            '<meta name="qa-pass" content="4">', "")), None)
        self.assertIn('need items 1</a> and <a href="#need-2">', html)
        self.assertNotIn("QA-PASS-3.html#need-3", html)


if __name__ == "__main__":
    unittest.main()
