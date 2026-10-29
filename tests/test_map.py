"""docs/map.md names real tests and real files. A renamed test or a moved file fails here."""
from __future__ import annotations

import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

MAP = ROOT / "docs" / "map.md"


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    if match is None:
        raise AssertionError(f"docs/map.md has no ## {heading}")
    rest = text[match.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(set(cell) <= set("-: ") for cell in cells):
            continue
        if cells[0].lower() in ("rule", "files"):
            continue
        rows.append(cells)
    return rows


class Map(unittest.TestCase):
    def setUp(self):
        self.text = MAP.read_text(encoding="utf-8")

    def test_every_named_test_exists(self):
        rows = _rows(_section(self.text, "Rules"))
        self.assertGreaterEqual(len(rows), 10)
        for cells in rows:
            self.assertGreaterEqual(len(cells), 3, cells)
            names = re.findall(r"`([^`]+)`", cells[2])
            self.assertEqual(len(names), 1, cells[2])
            qual = names[0]
            parts = qual.split(".")
            self.assertGreaterEqual(len(parts), 4, qual)
            self.assertEqual(parts[0], "tests", qual)
            mod = importlib.import_module(".".join(parts[:2]))
            obj = mod
            for part in parts[2:]:
                obj = getattr(obj, part, None)
                self.assertIsNotNone(obj, qual)
            self.assertTrue(callable(obj), qual)

    def test_every_named_file_exists(self):
        rows = _rows(_section(self.text, "After a change"))
        self.assertGreaterEqual(len(rows), 5)
        seen = []
        for cells in rows:
            paths = re.findall(r"`([^`]+)`", cells[0])
            self.assertGreaterEqual(len(paths), 1, cells[0])
            for path in paths:
                found = (ROOT / path).resolve()
                found.relative_to(ROOT)
                self.assertTrue(found.exists(), path)
                seen.append(path)
        self.assertIn("docs/map.md", seen)
        self.assertIn("src/qap/snapshot.py", seen)
        self.assertIn("skill/scripts/html_span.py", seen)


if __name__ == "__main__":
    unittest.main()
