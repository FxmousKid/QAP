"""The server snapshot: a second read reuses the index, and a changed pass file builds it again."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import layout as L, passes, snapshot  # noqa: E402


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        L.make_subject(self.root, "db/interaction", title="Interaction", qa_project="v3-interaction")
        self.page = self.root / "db/interaction/QA-PASS-1.html"
        self.page.write_text("<h1>Q&amp;A pass 1</h1><p>One subject, subject 01.</p>", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_second_read_does_not_open_the_pages_again(self):
        first = snapshot.search_index(self.root)
        passes._outline.cache_clear()
        passes._head_info.cache_clear()
        opened: list[str] = []
        real_open = open

        def spy(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", spy):
            second = snapshot.search_index(self.root)
        self.assertIs(second, first)
        self.assertEqual(opened, [])

    def test_editing_a_pass_invalidates_the_cache(self):
        first = snapshot.tree(self.root)
        self.assertEqual(first["children"][0]["children"][0]["passes"][0]["title"], "Q&A pass 1")
        self.page.write_text("<h1>Q&amp;A pass 1 revised title</h1>", encoding="utf-8")
        second = snapshot.tree(self.root)
        self.assertIsNot(second, first)
        self.assertEqual(second["children"][0]["children"][0]["passes"][0]["title"],
                         "Q&A pass 1 revised title")


if __name__ == "__main__":
    unittest.main()
