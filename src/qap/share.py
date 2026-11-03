"""Download a QA pass, or hand a copy of it to a command saved on this machine.

The copy rewrites a home directory to ~/. /Users/<name> and /home/<name>, including
a file:// URL, become ~/. The built page on disk is left as it is.

The command is share_command in the config file. It is stored as text, not as a
path, and a request cannot substitute a different one. It runs in an interactive
zsh, so a function from ~/.zshrc (share) exists, and these variables are in the
environment. Quote them in the command.

    PROJECT FAMILY SUBJECT PASS PASS_NUMBER
    PROJECT_DESCRIPTION FAMILY_DESCRIPTION SUBJECT_DESCRIPTION
    PASS_TITLE PASS_FILE PASS_PATH PASS_SOURCE
    QA_PROJECT SUBJECT_PATH FAMILY_PATH CONTENT_ROOT

PASS_PATH is the redacted copy, named like the page. PASS_SOURCE is the built
page. A description is the "description" field of that manifest, when it is
text. A subject's sources list is never one of these variables.

The file a browser saves is named after the subject and the pass title, so the
download is not QA-PASS-N.html. The page on disk keeps that name.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

from . import config, layout as L, passes as P

NAMES = (
    "PROJECT", "FAMILY", "SUBJECT", "PASS", "PASS_NUMBER",
    "PROJECT_DESCRIPTION", "FAMILY_DESCRIPTION", "SUBJECT_DESCRIPTION",
    "PASS_TITLE", "PASS_FILE", "PASS_PATH", "PASS_SOURCE",
    "QA_PROJECT", "SUBJECT_PATH", "FAMILY_PATH", "CONTENT_ROOT",
)
SUGGESTED = (
    'share --qa-pass "$PASS_PATH"'
    ' --project "$PROJECT" --family "$FAMILY" --subject "$SUBJECT"'
    ' --pass "$PASS" --title "$PASS_TITLE" --qa-project "$QA_PROJECT"'
)
TIMEOUT = 90

# A home prefix: /Users/<name> or /home/<name>, optionally behind file://.
# The name is one path segment. A letter before the slash keeps a URL such as
# https://example.com/home/ivan intact. Trailing sentence punctuation stays.
_HOME = re.compile(
    r"(?<![A-Za-z0-9._-])"
    r"(?:(?:file://(?:localhost)?)?(?:/Users|/home)/[^/\s\"'<>]+"
    r"|%2F(?:Users|home)%2F(?:%[0-9A-Fa-f]{2}|[^%/\s\"'<>])+)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s\"'<>]+")


class NeedsCommand(Exception):
    """share_command is empty. The dashboard shows the config line for it."""

    def __str__(self) -> str:
        return "no share command yet"


class ShareFailed(ValueError):
    """The command ran and did not succeed, or it never started."""


def redact(text: str) -> str:
    """Rewrite a home directory to ~/. A second pass changes nothing."""
    def tilde(match: re.Match) -> str:
        raw = match.group(0)
        core = raw.rstrip(".,;:)]}>")
        return "~" + raw[len(core):]

    return _HOME.sub(tilde, text)


# A download name stays readable and legal: no controls, no path, no quotes.
_BAD_NAME = re.compile(r"[\x00-\x1f<>:\"/\\|?*]")


def copy_name(title: str, subject: str, fallback: str) -> str:
    """Subject and pass title, as one file name. An empty title keeps the subject. Neither leaves the QA-PASS name."""
    parts = []
    for piece in (subject, title):
        piece = _safe_stem(piece)
        if piece and piece not in parts:
            parts.append(piece)
    stem = " — ".join(parts).strip(" .")
    if len(stem) > 100:
        cut = stem[:100].rstrip()
        stem = cut.rsplit(" ", 1)[0] if " " in cut[20:] else cut
        stem = stem.strip(" .—")
    if not stem:
        stem = _safe_stem(Path(fallback).stem) or "QA-PASS"
    return stem + ".html"


def _safe_stem(text: str) -> str:
    text = _BAD_NAME.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip(" .")


def content_disposition(name: str) -> str:
    """The download header. filename* is the real name. filename is an ASCII stand-in a header can carry."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9 ._()'-]+", " ", ascii_name)
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip(" .")
    if not ascii_name.lower().endswith(".html"):
        ascii_name = (ascii_name + ".html").strip()
    if ascii_name in ("", ".html"):
        ascii_name = "QA-PASS.html"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='.')}"


def redact_page(root: Path, rel: str) -> tuple[str, bytes]:
    """The built page, redacted, and the name the browser should save. The file on disk is not written."""
    path = pass_file(root, rel)
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    values = context(root, rel)
    name = copy_name(values["PASS_TITLE"], values["SUBJECT"], path.name)
    return name, redact(text).encode("utf-8", errors="surrogateescape")


def describe(root: Path, rel: str = "") -> dict:
    """The saved command, and that command with this pass's values quoted into it."""
    values = {name: "" for name in NAMES}
    if rel.strip():
        values.update(preview(root, rel))
    command = config.share_command().strip()
    return {
        "command": command,
        "suggested": SUGGESTED,
        "preview": render_command(command, values) if command else "",
        "variables": [{"name": name, "value": values[name]} for name in NAMES],
    }


def preview(root: Path, rel: str) -> dict[str, str]:
    """The variables a preview can show. The copy's directory is chosen when the command runs."""
    values = context(root, rel)
    values["PASS_PATH"] = f"/tmp/qap-share-…/{values['PASS_FILE']}"
    return values


def shell_quote(value: str) -> str:
    """One double-quoted word. zsh -ic still expands $, `, and ! inside quotes, so those are escaped."""
    return '"' + _escape_double(value) + '"'


def render_command(template: str, values: dict[str, str]) -> str:
    """Substitute $NAME and ${NAME} with double-quoted values. Text in single quotes stays as written."""
    out: list[str] = []
    i, n = 0, len(template)
    while i < n:
        c = template[i]
        if c == "'":
            j = template.find("'", i + 1)
            if j < 0:
                out.append(template[i:])
                break
            out.append(template[i:j + 1])
            i = j + 1
            continue
        if c == '"':
            inner, i = _double_quoted(template, i + 1, values)
            out.append('"' + inner + '"')
            continue
        if c == "$":
            name, nxt = _read_var(template, i)
            if name is not None and name in values:
                out.append(shell_quote(values[name]))
                i = nxt
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _escape_double(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("!", "\\!")
    )


def _read_var(text: str, i: int) -> tuple[str | None, int]:
    """At a `$`, the name and the index after it. None when this `$` is not a name."""
    if i >= len(text) or text[i] != "$":
        return None, i
    if i + 1 < len(text) and text[i + 1] == "{":
        end = text.find("}", i + 2)
        name = text[i + 2:end] if end >= 0 else ""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            return name, end + 1
        return None, i
    j = i + 1
    while j < len(text) and (text[j].isalnum() or text[j] == "_"):
        j += 1
    if j == i + 1:
        return None, i
    return text[i + 1:j], j


def _double_quoted(text: str, i: int, values: dict[str, str]) -> tuple[str, int]:
    """The inside of a double-quoted span, and the index just after its closing quote."""
    out: list[str] = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2] if i + 1 < n else c)
            i += 2
            continue
        if c == '"':
            return "".join(out), i + 1
        if c == "$":
            name, nxt = _read_var(text, i)
            if name is not None and name in values:
                out.append(_escape_double(values[name]))
                i = nxt
                continue
        out.append(c)
        i += 1
    return "".join(out), i


def context(root: Path, rel: str) -> dict[str, str]:
    """The variables for this pass. PASS_PATH is empty until run() fills it."""
    path = pass_file(root, rel)
    info = P.parse_name(path.name)
    assert info is not None  # pass_file already required a pass name
    subject_dir = path.parent
    subject_rel = L.rel_path(root, subject_dir)
    subject = L.resolve(root, subject_rel, "subject")
    top = subject_rel.split("/")[0]
    if top == subject_rel:
        family, family_manifest = subject, subject_dir / L.SUBJECT_FILE
    else:
        family = L.resolve(root, top, "folder")
        family_manifest = L.abs_path(root, top) / L.FOLDER_FILE
    project, project_description = _project(root, str(family.get("project") or ""))
    title, page_project = P.head_info(path)
    ext = info["ext"]
    stem = path.name[: -len(ext) - 1]
    label = stem[len("QA-PASS-"):] if stem.startswith("QA-PASS-") else stem
    values = {
        "PROJECT": project,
        "FAMILY": str(family.get("title") or ""),
        "SUBJECT": str(subject.get("title") or ""),
        "PASS": label,
        "PASS_NUMBER": "" if info["n"] is None else str(info["n"]),
        "PROJECT_DESCRIPTION": project_description,
        "FAMILY_DESCRIPTION": _description(family_manifest),
        "SUBJECT_DESCRIPTION": _description(subject_dir / L.SUBJECT_FILE),
        "PASS_TITLE": title,
        "PASS_FILE": path.name,
        "PASS_PATH": "",
        "PASS_SOURCE": str(path),
        "QA_PROJECT": str(subject.get("qa_project") or page_project),
        "SUBJECT_PATH": str(subject_dir),
        "FAMILY_PATH": str(L.abs_path(root, str(family.get("path") or ""))),
        "CONTENT_ROOT": str(root),
    }
    return {name: values[name].replace("\x00", "") for name in NAMES}


def run(root: Path, rel: str) -> dict:
    """Run the saved command. The redacted copy exists only while it runs."""
    command = config.share_command().strip()
    if not command:
        raise NeedsCommand()
    values = context(root, rel)
    path = Path(values["PASS_SOURCE"])
    directory = Path(tempfile.mkdtemp(prefix="qap-share-"))
    try:
        dest = directory / path.name
        dest.write_bytes(redact(path.read_text(encoding="utf-8", errors="surrogateescape"))
                         .encode("utf-8", errors="surrogateescape"))
        values["PASS_PATH"] = str(dest)
        env = os.environ.copy()
        env.update(values)
        try:
            proc = launch(command, env, TIMEOUT, cwd=str(path.parent))
        except subprocess.TimeoutExpired as e:
            raise ShareFailed(f"the share command took more than {TIMEOUT}s") from e
        except OSError as e:
            raise ShareFailed(f"could not run zsh: {e}") from e
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        if proc.returncode != 0:
            detail = (stderr or stdout or "the share command failed").strip()
            raise ShareFailed(detail[-500:])
        return {
            "url": _last_url(stdout) or _last_url(stderr),
            "stdout": _tail(stdout),
            "stderr": _tail(stderr),
            "code": proc.returncode,
        }
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def launch(command: str, env: dict, timeout: float, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Interactive zsh, so ~/.zshrc functions (share) exist. `command` is the saved text."""
    return subprocess.run(
        ["zsh", "-ic", command],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def pass_file(root: Path, rel: str) -> Path:
    """The built page inside the content root. A source, a manifest, or a path outside is refused."""
    rel = L.clean_rel(rel)
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError(f"not a built pass: {rel}") from e
    info = P.parse_name(path.name)
    if info is None or info["ext"] == "src.html" or not path.is_file():
        raise ValueError(f"not a built pass: {rel}")
    if not L.is_subject_dir(path.parent):
        raise ValueError(f"not a built pass: {rel}")
    return path


def _description(path: Path) -> str:
    value = L.read_json(path).get("description")
    return value.strip() if isinstance(value, str) else ""


def _project(root: Path, pid: str) -> tuple[str, str]:
    if not pid:
        return "", ""
    for entry in L.read_json(root / L.PROJECTS_FILE).get("projects") or []:
        if isinstance(entry, dict) and entry.get("id") == pid:
            title = entry.get("title") or pid
            description = entry.get("description") if isinstance(entry.get("description"), str) else ""
            return str(title), description.strip()
    return pid, ""


def _last_url(text: str) -> str:
    found = _URL.findall(text or "")
    return found[-1] if found else ""


def _tail(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[-limit:]
