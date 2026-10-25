"""Tile icons: a built-in set (web/icons.json, shared with the dashboard) or any emoji."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@lru_cache(maxsize=1)
def builtin() -> dict:
    return json.loads((WEB / "icons.json").read_text(encoding="utf-8"))


def validate(icon: str | None) -> str | None:
    """A built-in icon name or an emoji; '' clears the icon; None leaves it unchanged."""
    if icon is None or icon == "":
        return icon
    icon = icon.strip()
    if icon in builtin():
        return icon
    if len(icon) <= 16 and not icon.isascii() and not any(c.isspace() for c in icon):
        return icon  # an emoji (sequences with modifiers or joiners included)
    raise ValueError(f"unknown icon {icon!r}: use an emoji or one of {', '.join(sorted(builtin()))}")


def validate_color(color: str | None) -> str | None:
    if color is None or color == "" or COLOR.match(color.strip()):
        return color.strip() if color else color
    raise ValueError(f"bad colour {color!r}: use #RRGGBB")
