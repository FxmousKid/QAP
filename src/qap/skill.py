"""Thin wrappers around the skill's own scripts (build.py, check.py, carry.py) and its template.

The scripts stay the single implementation: qap only picks the files (which source, which number, which
output) and runs them with the current Python.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, passes as P


def scripts_dir() -> Path:
    d = config.skill_dir()[0] / "scripts"
    if not (d / "build.py").is_file():
        raise FileNotFoundError(f"the qa-pass skill scripts are not at {d} (set QAP_SKILL_DIR or "
                                f"`qap config skill_dir <path>`)")
    return d


def run(script: str, *args: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(scripts_dir() / script), *args],
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def build(src: Path, out: Path | None = None) -> dict:
    out = out or P.built_for(src)
    code, text = run("build.py", str(src), str(out))
    return {"src": str(src), "html": str(out), "ok": code == 0, "output": text}


def check(page: Path) -> dict:
    code, text = run("check.py", str(page))
    problems = [line.strip()[len("PROBLEM"):].strip() for line in text.splitlines()
                if line.strip().startswith("PROBLEM")]
    warnings = sum(1 for line in text.splitlines() if line.strip().startswith("warning"))
    return {"html": str(page), "ok": code == 0, "problems": problems, "warnings": warnings, "output": text}


def rebuild_safely(src: Path) -> dict:
    """Rebuild an existing page from its source, keeping the old page when the new one has check PROBLEMs
    (old-format sources) or when the build fails. Used by `qap build --all`."""
    out = P.built_for(src)
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / out.name
        result = build(src, candidate)
        if not result["ok"]:
            return {**result, "html": str(out), "replaced": False, "reason": "build failed"}
        verdict = check(candidate)
        if not verdict["ok"]:
            return {**result, "html": str(out), "replaced": False,
                    "reason": f"kept the old page: {len(verdict['problems'])} check problem(s)",
                    "problems": verdict["problems"]}
        same = out.is_file() and out.read_bytes() == candidate.read_bytes()
        if not same:
            out.write_bytes(candidate.read_bytes())
        return {**result, "html": str(out), "replaced": not same, "reason": "unchanged" if same else "rebuilt"}


def carry(prev: Path, nxt: Path, n: int, skip: str = "", stars: str = "", ai: str = "") -> dict:
    args = [str(prev), str(nxt), "--pass", str(n)]
    if skip:
        args += ["--skip", skip]
    if stars:
        args += ["--stars", stars]
    if ai:
        args += ["--ai", ai]
    code, text = run("carry.py", *args)
    return {"from": str(prev), "src": str(nxt), "n": n, "ok": code == 0, "output": text}


def seed_first(dest: Path, qa_project: str, n: int = 1) -> dict:
    """Start a subject's first pass from the template, with its qa-project and number filled in."""
    template = config.skill_dir()[0] / "template" / "QA-PASS.src.html"
    text = template.read_text(encoding="utf-8")
    text = text.replace('content="PROJECT"', f'content="{qa_project}"')
    text = text.replace('<meta name="qa-pass" content="N">', f'<meta name="qa-pass" content="{n}">')
    text = re.sub(r"\bPROJECT\b", qa_project, text)
    text = text.replace("Q&amp;A pass N", f"Q&amp;A pass {n}").replace("pass N ·", f"pass {n} ·")
    dest.write_text(text, encoding="utf-8")
    return {"from": str(template), "src": str(dest), "n": n, "ok": True,
            "output": f"{dest}: pass {n} started from the template; fill it, then `qap build`."}
