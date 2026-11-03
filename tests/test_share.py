"""A shared or downloaded pass rewrites a home directory to ~/. The command is the saved one."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qap import config, layout as L, share  # noqa: E402


PAGE = """<!doctype html><html><head><title>Pass</title></head><body>
<h1>The schedule</h1>
<footer>Stored at <code>/Users/iyan/Desktop/Dev/QA-PASS-1.html</code>.
<a href="file:///Users/iyan/notes.html">notes</a>
<a href="file://localhost/home/iyan/other.html">other</a>
see /Users/iyan. and https://example.com/home/iyan/keep
and %2FUsers%2Fiyan%2FDesktop</footer>
</body></html>
"""


class Redact(unittest.TestCase):
    def test_home_paths_become_a_tilde(self):
        text = share.redact(PAGE)
        self.assertNotIn("/Users/iyan", text)
        self.assertNotIn("file://", text)
        self.assertNotIn("/home/iyan/other", text)
        self.assertNotIn("%2FUsers%2Fiyan", text)
        self.assertIn("~/Desktop/Dev/QA-PASS-1.html", text)
        self.assertIn("~/notes.html", text)
        self.assertIn("~/other.html", text)
        self.assertIn("~.", text)
        self.assertIn("https://example.com/home/iyan/keep", text)
        self.assertEqual(share.redact(text), text)

    def test_the_page_on_disk_is_not_rewritten(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        L.make_subject(root, "db/interaction", title="Interaction")
        page = root / "db/interaction/QA-PASS-1.html"
        page.write_text(PAGE, encoding="utf-8")
        name, data = share.redact_page(root, "db/interaction/QA-PASS-1.html")
        self.assertEqual(name, "Interaction — The schedule.html")
        self.assertNotIn(b"/Users/iyan", data)
        self.assertIn("/Users/iyan", page.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            share.pass_file(root, "db/interaction/subject.json")
        with self.assertRaises(L.LayoutError):
            share.pass_file(root, "../secret")

    def test_the_download_is_named_after_the_pass(self):
        self.assertEqual(
            share.copy_name("The schedule", "Interaction", "QA-PASS-1.html"),
            "Interaction — The schedule.html",
        )
        self.assertEqual(
            share.copy_name('say "hi" / there:\nnext', "Interaction", "QA-PASS-1.html"),
            "Interaction — say hi there next.html",
        )
        self.assertEqual(share.copy_name("", "Interaction", "QA-PASS-1.html"), "Interaction.html")
        self.assertEqual(share.copy_name(":/", "", "QA-PASS-9.html"), "QA-PASS-9.html")
        self.assertEqual(share.copy_name("The schedule", "The schedule", "QA-PASS-1.html"), "The schedule.html")
        long_name = share.copy_name("alpha " * 40, "Subject", "QA-PASS-1.html")
        self.assertTrue(long_name.endswith(".html"))
        self.assertLessEqual(len(long_name), 105)
        self.assertTrue(long_name.startswith("Subject — "))
        header = share.content_disposition("RBAC — Café «notes».html")
        self.assertTrue(header.isascii())
        self.assertIn('filename="RBAC Cafe notes.html"', header)
        star = header.split("filename*=UTF-8''", 1)[1]
        self.assertEqual(unquote(star), "RBAC — Café «notes».html")


class Context(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        L.make_subject(self.root, "db/interaction", title="Interaction", qa_project="v3-interaction")
        L.set_meta(self.root, "db", title="DB migration v3")
        L.make_project(self.root, "work", title="Work")
        self._put(self.root / "db/folder.json", {"description": "the family"})
        self._put(self.root / "db/interaction/subject.json", {
            "description": "how the screen behaves",
            "sources": ["/Users/iyan/secret/choices"],
        })
        projects = json.loads((self.root / "projects.json").read_text(encoding="utf-8"))
        projects["projects"][0]["description"] = "the project"
        (self.root / "projects.json").write_text(json.dumps(projects), encoding="utf-8")
        (self.root / "db/interaction/QA-PASS-1.html").write_text(PAGE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, path: Path, extra: dict) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(extra)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_variables_come_from_the_manifests_not_from_sources(self):
        values = share.context(self.root, "db/interaction/QA-PASS-1.html")
        self.assertEqual(values["PROJECT"], "Work")
        self.assertEqual(values["FAMILY"], "DB migration v3")
        self.assertEqual(values["SUBJECT"], "Interaction")
        self.assertEqual(values["PASS"], "1")
        self.assertEqual(values["PASS_NUMBER"], "1")
        self.assertEqual(values["PROJECT_DESCRIPTION"], "the project")
        self.assertEqual(values["FAMILY_DESCRIPTION"], "the family")
        self.assertEqual(values["SUBJECT_DESCRIPTION"], "how the screen behaves")
        self.assertEqual(values["PASS_TITLE"], "The schedule")
        self.assertEqual(values["PASS_FILE"], "QA-PASS-1.html")
        self.assertEqual(values["QA_PROJECT"], "v3-interaction")
        self.assertEqual(values["PASS_PATH"], "")
        blob = "\n".join(values.values())
        self.assertNotIn("secret/choices", blob)
        self.assertNotIn("sources", blob)


class Preview(unittest.TestCase):
    def test_values_are_double_quoted(self):
        template = 'share --qa-pass "$PASS_PATH" --family $FAMILY --note "see $SUBJECT"'
        values = {
            "PASS_PATH": "/tmp/qap-share-x/QA-PASS-1.html",
            "FAMILY": "DB migration v3",
            "SUBJECT": 'say "hi" and $HOME and `id` and !',
        }
        self.assertEqual(
            share.render_command(template, values),
            'share --qa-pass "/tmp/qap-share-x/QA-PASS-1.html"'
            ' --family "DB migration v3"'
            ' --note "see say \\"hi\\" and \\$HOME and \\`id\\` and \\!"',
        )
        self.assertEqual(share.render_command("echo '$PROJECT'", {"PROJECT": "Work"}), "echo '$PROJECT'")
        self.assertEqual(share.render_command("echo ${PASS}", {"PASS": "4", "PASS_NUMBER": "42"}), 'echo "4"')
        self.assertEqual(
            share.render_command("$PASS $PASS_NUMBER", {"PASS": "4", "PASS_NUMBER": "42"}),
            '"4" "42"',
        )
        self.assertEqual(share.render_command("echo $NOT_HERE", {"PROJECT": "Work"}), "echo $NOT_HERE")
        self.assertEqual(share.render_command("echo $FAMILY", {"FAMILY": ""}), 'echo ""')
        self.assertEqual(share.render_command(r'echo "a\$PROJECT"', {"PROJECT": "Work"}), r'echo "a\$PROJECT"')


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "content"
        self.cfg = Path(self.tmp.name) / "cfg"
        L.make_subject(self.root, "db/interaction", title="Interaction", qa_project="v3-interaction")
        L.set_meta(self.root, "db", title="DB migration v3")
        self.page = self.root / "db/interaction/QA-PASS-1.html"
        self.page.write_text(PAGE, encoding="utf-8")
        subject = json.loads((self.root / "db/interaction/subject.json").read_text(encoding="utf-8"))
        subject["sources"] = ["/Users/iyan/secret/choices"]
        subject["description"] = "how the screen behaves"
        (self.root / "db/interaction/subject.json").write_text(json.dumps(subject), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_saved_command_sends_a_redacted_copy(self):
        seen = {}

        def launch(command, env, timeout, cwd=None):
            seen["command"] = command
            seen["env"] = dict(env)
            seen["bytes"] = Path(env["PASS_PATH"]).read_bytes()
            seen["cwd"] = cwd
            return subprocess.CompletedProcess(
                ["zsh"], 0, stdout="https://share.example/t/QA-PASS-1.html\n", stderr="noise\n")

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.cfg)}), \
                mock.patch("qap.share.launch", launch):
            config.write_share_command('share --qa-pass "$PASS_PATH" --family "$FAMILY"')
            result = share.run(self.root, "db/interaction/QA-PASS-1.html")
        self.assertEqual(seen["command"], 'share --qa-pass "$PASS_PATH" --family "$FAMILY"')
        self.assertEqual(result["url"], "https://share.example/t/QA-PASS-1.html")
        self.assertNotIn(b"/Users/iyan", seen["bytes"])
        self.assertIn(b"~/Desktop/Dev/QA-PASS-1.html", seen["bytes"])
        self.assertIn("/Users/iyan", self.page.read_text(encoding="utf-8"))
        self.assertFalse(Path(seen["env"]["PASS_PATH"]).exists())
        self.assertEqual(seen["env"]["FAMILY"], "DB migration v3")
        self.assertEqual(seen["env"]["SUBJECT_DESCRIPTION"], "how the screen behaves")
        self.assertNotIn("secret/choices", seen["env"]["SUBJECT_DESCRIPTION"])
        self.assertEqual(Path(seen["cwd"]).resolve(), self.page.resolve().parent)

    def test_an_empty_command_is_refused_and_a_timeout_removes_the_copy(self):
        seen = {}

        def launch(command, env, timeout, cwd=None):
            seen["path"] = env["PASS_PATH"]
            raise subprocess.TimeoutExpired(["zsh"], timeout)

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.cfg)}):
            with self.assertRaises(share.NeedsCommand):
                share.run(self.root, "db/interaction/QA-PASS-1.html")
            config.write_share_command("share x")
            with mock.patch("qap.share.launch", launch):
                with self.assertRaises(share.ShareFailed):
                    share.run(self.root, "db/interaction/QA-PASS-1.html")
        self.assertFalse(Path(seen["path"]).exists())

    def test_the_command_is_stored_as_text(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.cfg)}):
            stored = config.write_share_command('share --qa-pass "$PASS_PATH"\n')
            self.assertEqual(stored, 'share --qa-pass "$PASS_PATH"')
            self.assertEqual(config.share_command(), stored)
            config.write_config("skill_dir", "skill")
            saved = json.loads((self.cfg / "qap" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["share_command"], stored)
            self.assertNotEqual(saved["skill_dir"], "skill")
            self.assertEqual(config.write_share_command("  "), "")
            saved = json.loads((self.cfg / "qap" / "config.json").read_text(encoding="utf-8"))
            self.assertNotIn("share_command", saved)
