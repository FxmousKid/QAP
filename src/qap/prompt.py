"""Small terminal prompts for interactive use. Agents never see them: they only run in a TTY,
and --json or --yes turn them off."""
from __future__ import annotations

import sys


class Cancelled(Exception):
    pass


def interactive(args) -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and not getattr(args, "json", False) \
        and not getattr(args, "yes", False)


def _input(text: str) -> str:
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        raise Cancelled()


def ask(text: str, default: str | None = None, required: bool = True) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        value = _input(f"{text}{hint}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""


def choose(text: str, options: list[tuple[str, str]], default: int = 0, allow_new: str | None = None) -> str:
    """Numbered menu; returns the chosen option's value. allow_new: a label for typing a value instead."""
    print(text)
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i:>2}. {label}")
    if allow_new:
        print(f"   n. {allow_new}")
    while True:
        raw = _input(f"Choice [{default + 1}]: ").strip()
        if not raw:
            return options[default][0]
        if allow_new and raw.lower() == "n":
            return ask(allow_new)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("  type a number from the list" + (" or n" if allow_new else ""))


def confirm(text: str, default: bool = True) -> bool:
    raw = _input(f"{text} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not raw else raw in ("y", "yes", "o", "oui")
