"""Where the content lives and where the skill lives.

content_root, first match wins:
  1. --root on the command line (passed in as `override`)
  2. the QAP_CONTENT_ROOT environment variable
  3. ~/.config/qap/config.json  {"content_root": "..."}
  4. ~/Desktop/Dev/ai/QAP/contents

skill_dir (build.py, check.py, carry.py, the template), first match wins:
  1. the QAP_SKILL_DIR environment variable
  2. config.json {"skill_dir": "..."}
  3. <repo>/skill, when qap runs from its repo (uv run --project, bin/qap)
  4. ~/.claude/skills/qa-pass (the symlink the skill is installed through; works after `uv tool install`)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_ROOT = Path("~/Desktop/Dev/ai/QAP/contents")
KEYS = ("content_root", "skill_dir")


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "qap" / "config.json"


def read_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"qap: cannot read {path}: {e}")
    return data if isinstance(data, dict) else {}


def write_config(key: str, value: str | None) -> dict:
    if key not in KEYS:
        raise ValueError(f"unknown config key {key!r}; known: {', '.join(KEYS)}")
    data = read_config()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = str(Path(value).expanduser().resolve())
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def content_root(override: str | None = None) -> tuple[Path, str]:
    """The content root and where that choice came from."""
    if override:
        return Path(override).expanduser(), "--root"
    env = os.environ.get("QAP_CONTENT_ROOT")
    if env:
        return Path(env).expanduser(), "QAP_CONTENT_ROOT"
    configured = read_config().get("content_root")
    if configured:
        return Path(configured).expanduser(), str(config_path())
    return DEFAULT_ROOT.expanduser(), "default"


def skill_dir() -> tuple[Path, str]:
    env = os.environ.get("QAP_SKILL_DIR")
    if env:
        return Path(env).expanduser(), "QAP_SKILL_DIR"
    configured = read_config().get("skill_dir")
    if configured:
        return Path(configured).expanduser(), str(config_path())
    repo_skill = Path(__file__).resolve().parents[2] / "skill"
    if (repo_skill / "scripts" / "build.py").is_file():
        return repo_skill, "repo"
    return Path("~/.claude/skills/qa-pass").expanduser(), "installed skill"
