"""Batches: a triage pass, one subject per group, and the board that says which session waits for you.

A batch is a folder that holds batch.json, a triage subject, and one subject per session group:

    <family>/<batch>/
      batch.json            {title, triage, created, groups: [session groups, in start order], fast, info}
      triage/               the triage pass sorts the topics into groups (skill/scripts/triage.py reads it)
        decisions.json      the rules the batch starts from
      <group>/              one subject per session group; only that group's session writes in it
        subject.json        title, qa_project, and "group": {batch, order, goal, owns, waits, topics}
        brief.md            what the session reads first; qap split writes it once
        status.json         {phase, note, pr, session: {state, since, question, id, app_id}, updated}
        decisions.json      {"decisions": [...]}: the group's own rules, added to, never rewritten
        events.jsonl        one JSON line per event
        inbox.jsonl         the notes other groups sent it

Two things say where a group is, and they are kept apart:
  phase           what the session reports (qap status): ready, queued, planning, plan_agreed, implementing,
                  pr_open, merged, done, blocked. qap split writes ready, or queued when the group waits for another.
  session.state   what the session's hooks report, never the agent: working, waiting (its turn ended, so it waits
                  for you), permission (it asks for one), ended.

The ledger is every decisions.json under the batch's family (its top-level folder), oldest first: each file has
one writer, and the family's view is assembled when it is read.

The board offers to start at most START_AT_ONCE sessions at a time. The triage agent is never told that number:
it orders the groups, and whoever starts the sessions follows the board.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # not on a POSIX system: writes go unlocked
    fcntl = None

from . import config, layout as L, passes as P, skill

BATCH_FILE = "batch.json"
STATUS_FILE = "status.json"
DECISIONS_FILE = "decisions.json"
EVENTS_FILE = "events.jsonl"
INBOX_FILE = "inbox.jsonl"
BRIEF_FILE = "brief.md"
TRIAGE = "triage"
START_AT_ONCE = 3
PHASES = ("ready", "queued", "planning", "plan_agreed", "implementing", "pr_open", "merged", "done", "blocked")
FINISHED = ("merged", "done")
# What each hook event says about the session. "spawned" only records the app's session id.
EVENTS = {"started": "working", "answered": "working", "working": "working", "waiting": "waiting",
          "permission": "permission", "ended": "ended", "spawned": None, "note": None}
QUESTION_CHARS = 600


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@contextmanager
def _locked(d: Path):
    """One writer at a time for a group's files: the CLI (the agents' qap status) and qap serve (the hooks) both
    read, change and write status.json, and number the notes of inbox.jsonl."""
    if fcntl is None:
        yield
        return
    with open(d / ".qap.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------- finding things

def batch_dir(root: Path, ref: str) -> Path:
    """The batch a reference names: the batch folder itself, or any subject inside it (triage, a group)."""
    rel = L.clean_rel(ref)
    path = L.abs_path(root, rel)
    if not path.is_dir():
        path = L.abs_path(root, L.resolve(root, ref)["path"])
    for candidate in (path, path.parent):
        if (candidate / BATCH_FILE).is_file():
            return candidate
    raise L.LayoutError(f"{ref!r} is not a batch, nor a subject inside one (no {BATCH_FILE}; `qap new-batch`)")


def group_dir(root: Path, ref: str) -> Path:
    """A group's subject folder: <batch>/<group>, or a unique group name."""
    node = L.resolve(root, ref, "subject")
    path = L.abs_path(root, node["path"])
    if not (path.parent / BATCH_FILE).is_file() or path.name == TRIAGE:
        raise L.LayoutError(f"{node['path']} is not a group of a batch")
    return path


def batches(root: Path) -> list[dict]:
    found = []
    for path in sorted(root.rglob(BATCH_FILE)):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        rel = L.rel_path(root, path.parent)
        try:
            meta = L.read_json(path)
        except L.LayoutError as e:
            found.append({"path": rel, "title": L.pretty(path.parent.name), "groups": 0, "error": str(e)})
            continue
        found.append({"path": rel, "title": meta.get("title") or L.pretty(path.parent.name),
                      "groups": len(meta.get("groups") or []), "created": meta.get("created", "")})
    return found


# ---------------------------------------------------------------------------- a new batch

def make_batch(root: Path, rel: str, title: str | None = None, icon: str | None = None,
               project: str | None = None) -> dict:
    """The batch folder, its batch.json, and the triage subject with its pass 1 started from the template."""
    rel = L.clean_rel(rel)
    d = L.abs_path(root, rel)
    if (d / BATCH_FILE).exists():
        raise L.LayoutError(f"{rel} is a batch already")
    if d.exists():  # the folder named, never one a fuzzy match would find
        if not d.is_dir() or L.is_subject_dir(d):
            raise L.LayoutError(f"{rel} is a subject, not a folder: a batch is a folder of its own")
        title = title or L.read_json(d / L.FOLDER_FILE).get("title") or L.pretty(d.name)
    else:
        title = title or L.make_folder(root, rel, title=title, icon=icon, project=project)["title"]
    triage = L.make_subject(root, f"{rel}/{TRIAGE}", title=f"{title}: triage", icon="🧭",
                            qa_project=f"{d.name}-{TRIAGE}")
    L.write_json(d / BATCH_FILE, {"title": title, "triage": TRIAGE, "created": date.today().isoformat(),
                                  "groups": [], "fast": [], "info": []})
    node = {"path": rel}
    t = L.abs_path(root, triage["path"])
    L.write_json(t / DECISIONS_FILE, {"decisions": []})
    seeded = skill.seed_first(t / "QA-PASS-1.src.html", f"{d.name}-{TRIAGE}", 1, template="TRIAGE.src.html")
    return {"batch": node["path"], "dir": str(d), "triage": triage["path"], "src": seeded["src"]}


# ---------------------------------------------------------------------------- the triage pass and the split

def read_triage(root: Path, batch: Path) -> dict:
    """The groups of the batch's latest built triage page (triage.py), with the page they come from."""
    t = batch / (L.read_json(batch / BATCH_FILE).get("triage") or TRIAGE)
    pages = [p for p in P.list_passes(t, with_titles=False) if p["kind"] == "html"]
    if not pages:
        raise L.LayoutError(f"{L.rel_path(root, t)} has no built triage pass yet (`qap build {L.rel_path(root, t)}`)")
    page = t / pages[-1]["file"]
    code, out = skill.run("triage.py", str(page))
    if code != 0:
        raise L.LayoutError(out)
    data = json.loads(out)
    data["page"] = str(page)
    data["subject"] = L.rel_path(root, t)
    return data


def split(root: Path, ref: str, force: bool = False) -> dict:
    """One subject per session group of the triage pass, each with brief.md, status.json and decisions.json.

    Run it again and it adds new groups and updates what each group owns and waits for. A group's brief, status
    and decisions stay as they are (its session may have read them already), unless force rewrites the brief.
    """
    batch = batch_dir(root, ref)
    data = read_triage(root, batch)
    if data["kind"] != "triage":
        raise L.LayoutError(f"{data['page']} is not a triage pass (<meta name=\"qa-kind\" content=\"triage\">)")
    if data["problems"]:
        raise L.LayoutError("the triage pass has problems; fix them and rebuild:\n  " + "\n  ".join(data["problems"]))
    batch_rel = L.rel_path(root, batch)
    sessions = [g for g in data["groups"] if g["lane"] == "session"]
    owners = {item.lower(): (g["name"], item) for g in sessions for item in g["owns"]}
    rules = ledger(root, batch_rel)["decisions"]
    out = []
    for order, g in enumerate(sessions, 1):
        rel = f"{batch_rel}/{g['name']}"
        d = L.abs_path(root, rel)
        created = not (d / L.SUBJECT_FILE).is_file()
        if created:
            L.make_subject(root, rel, title=g["title"], qa_project=f"{batch.name}-{g['name']}")
        meta = L.read_json(d / L.SUBJECT_FILE)
        meta["group"] = {"batch": batch_rel, "order": order, "goal": g["goal"], "owns": g["owns"],
                         "waits": g["waits"], "topics": g["topics"], "triage": data["subject"],
                         "triage_page": data["page"], "heading": g["id"]}
        L.write_json(d / L.SUBJECT_FILE, meta)
        wrote_brief = created or force or not (d / BRIEF_FILE).exists()
        if wrote_brief:
            others = {item: owner for owner, item in owners.values() if owner != g["name"]}
            (d / BRIEF_FILE).write_text(brief(root, rel, g, data, rules, others), encoding="utf-8")
        if not (d / STATUS_FILE).exists():
            L.write_json(d / STATUS_FILE, {"phase": "queued" if g["waits"] else "ready", "note": "", "pr": "",
                                           "session": {}, "updated": now()})
        if not (d / DECISIONS_FILE).exists():
            L.write_json(d / DECISIONS_FILE, {"decisions": []})
        out.append({"group": rel, "title": g["title"], "created": created, "brief": str(d / BRIEF_FILE),
                    "wrote_brief": wrote_brief, "waits": g["waits"]})
    meta = L.read_json(batch / BATCH_FILE)
    meta["groups"] = [g["name"] for g in sessions]
    meta["fast"] = [{"title": g["title"], "topics": g["topics"]} for g in data["groups"] if g["lane"] == "fast"]
    meta["info"] = [{"title": g["title"], "topics": g["topics"]} for g in data["groups"] if g["lane"] == "info"]
    meta["split"] = now()
    L.write_json(batch / BATCH_FILE, meta)
    view = board(root, batch_rel)
    return {"batch": batch_rel, "groups": out, "start_now": [g["path"] for g in view["start_next"]],
            "first_prompts": {g["path"]: first_prompt(root, g["path"]) for g in view["start_next"]}}


def first_prompt(root: Path, group_rel: str) -> str:
    """The whole first prompt of a group session: one line. The brief and the lane file hold the rest."""
    return f"You are the session of group {group_rel} (QAP). Read {L.abs_path(root, group_rel) / BRIEF_FILE}."


def brief(root: Path, rel: str, g: dict, triage: dict, rules: list[dict], others: dict[str, str]) -> str:
    page = triage["page"]
    lane = config.skill_dir()[0] / "lanes" / "group-session.md"
    lines = [f"# Group: {g['title']}", "",
             f"Read first, and follow it: {lane} (what every group session does).", "",
             "## Goal", "", g["goal"] or "(the triage pass gives none: restate it and ask)", "",
             "## Your topics (read each one in the triage pass)", ""]
    lines += [f"- {t['num']} · {t['title']} — {page}#{t['id']}" for t in g["topics"]]
    lines += ["", "## Rules that bind you (the decisions ledger; a new rule is a decision box, not code)", ""]
    lines += [f"- {r['rule']} — {r.get('who') or '?'}, {r.get('where') or 'no source'} ({r.get('date', '')})"
              for r in rules] or ["- none yet"]
    lines += ["", "## Files and contracts", ""]
    lines += [f"- You own: {item}" for item in g["owns"]] or ["- You own nothing named in the triage pass."]
    lines += [f"- Do not touch: {item} (owned by {owner})" for item, owner in sorted(others.items())]
    lines += ["", "## Waits for", ""]
    lines += [f"- {w}: its PR merges first; then rebase onto it" for w in g["waits"]] or ["- No other group."]
    lines += ["", "## Where things are", "",
              f"- Your folder: {L.abs_path(root, rel)} (write only here)",
              f"- Your rounds: `qap carry {rel}`, then `qap build {rel} --check`",
              f"- Your state: `qap status {rel} --phase <phase> [--note …] [--pr <url>]`",
              f"- A rule you agreed with the user: `qap decide {rel} --rule … --why … --who … --where …`",
              f"- A note to another group: `qap tell {rel} <group> \"…\"`",
              f"- The triage pass: {page}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------- status and events

def status(root: Path, ref: str) -> dict:
    d = group_dir(root, ref)
    return {"group": L.rel_path(root, d), **L.read_json(d / STATUS_FILE)}


def set_phase(root: Path, ref: str, phase: str | None = None, note: str | None = None, pr: str | None = None) -> dict:
    d = group_dir(root, ref)
    if phase is not None and phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; one of: {', '.join(PHASES)}")
    with _locked(d):
        st = L.read_json(d / STATUS_FILE)
        before = st.get("phase")
        for key, value in (("phase", phase), ("note", note), ("pr", pr)):
            if value is not None:
                st[key] = value
        st["updated"] = now()
        L.write_json(d / STATUS_FILE, st)
        _append(d / EVENTS_FILE, {"at": st["updated"], "kind": "phase", "phase": st.get("phase"), "from": before,
                                  "note": note or "", "pr": pr or ""})
    return {"group": L.rel_path(root, d), **st}


def record(root: Path, ref: str, kind: str, text: str = "", session_id: str = "", app_id: str = "",
           origin: str = "") -> dict:
    """One event from a session's hooks (or the mod that starts it): the log line, and the session's state."""
    if kind not in EVENTS:
        raise ValueError(f"unknown event {kind!r}; one of: {', '.join(EVENTS)}")
    d = group_dir(root, ref)
    with _locked(d):
        return _record(root, d, kind, text, session_id, app_id, origin)


def _record(root: Path, d: Path, kind: str, text: str, session_id: str, app_id: str, origin: str) -> dict:
    at = now()
    st = L.read_json(d / STATUS_FILE)
    session = dict(st.get("session") or {})
    if session_id:
        session["id"] = session_id
    if app_id:
        session["app_id"] = app_id
    state = EVENTS[kind]
    if state:
        session["state"] = state
        session["since"] = at
        # The person's answer clears the question. A turn they did not start (a note, a task's end) leaves it, and
        # comes back waiting with no text.
        if kind == "answered":
            session["question"] = ""
        elif kind == "waiting" and text:
            session["question"] = _last_paragraphs(text)[-QUESTION_CHARS:]
    if kind == "started" and st.get("phase") in ("ready", "queued"):
        st["phase"] = "planning"
    st["session"] = session
    st["updated"] = at
    L.write_json(d / STATUS_FILE, st)
    _append(d / EVENTS_FILE, {"at": at, "kind": kind, "text": (text or "")[:QUESTION_CHARS],
                              "session_id": session_id, "app_id": app_id, "origin": origin})
    return {"group": L.rel_path(root, d), **st}


def _last_paragraphs(text: str, n: int = 2) -> str:
    """The end of a turn's last words: what the session waits on, with the line before its answer line."""
    parts = [p.strip() for p in (text or "").replace("\r", "").split("\n\n") if p.strip()]
    return "\n\n".join(parts[-n:])


def _append(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _lines(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def events(root: Path, ref: str, last: int = 40) -> list[dict]:
    return _lines(group_dir(root, ref) / EVENTS_FILE)[-last:]


# ---------------------------------------------------------------------------- the ledger

def decide(root: Path, ref: str, rule: str, why: str = "", who: str = "", where: str = "",
           covers: str = "") -> dict:
    """Add one rule to a subject's decisions.json. Entries are only ever added; an id never changes."""
    node = L.resolve(root, ref, "subject")
    d = L.abs_path(root, node["path"])
    rule = (rule or "").strip()
    if not rule:
        raise ValueError("give the rule, in one line")
    with _locked(d):
        data = L.read_json(d / DECISIONS_FILE)
        entries = list(data.get("decisions") or [])
        entry = {"id": f"{d.name}-{len(entries) + 1}", "rule": rule, "why": why.strip(), "who": who.strip(),
                 "where": where.strip(), "covers": covers.strip(), "date": date.today().isoformat(),
                 "by": node["path"]}
        entries.append(entry)
        L.write_json(d / DECISIONS_FILE, {**data, "decisions": entries})
    return entry


def ledger(root: Path, ref: str) -> dict:
    """Every rule of the family (the top-level folder ref sits in), oldest first."""
    rel = L.clean_rel(ref)
    if rel and not L.abs_path(root, rel).exists():
        rel = L.resolve(root, ref)["path"]
    family = rel.split("/", 1)[0] if rel else ""
    base = L.abs_path(root, family)
    found = []
    for path in sorted(base.rglob(DECISIONS_FILE)):
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            continue
        for entry in L.read_json(path).get("decisions") or []:
            if isinstance(entry, dict) and entry.get("rule"):
                found.append({**entry, "by": entry.get("by") or L.rel_path(root, path.parent)})
    found.sort(key=lambda e: (e.get("date", ""), e.get("by", ""), _number(e.get("id", ""))))
    return {"family": family, "decisions": found}


def _number(entry_id: str) -> int:
    tail = str(entry_id).rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


# ---------------------------------------------------------------------------- notes between groups

def tell(root: Path, sender: str, to: str, text: str) -> dict:
    """A note from one group to another, kept in the receiver's inbox. Its session's mod shows it there."""
    src = group_dir(root, sender)
    name = L.clean_rel(to)
    target = group_dir(root, f"{L.rel_path(root, src.parent)}/{name}" if "/" not in name else name)
    if target.parent != src.parent:
        raise L.LayoutError(f"{to!r} is not a group of {L.rel_path(root, src.parent)}: notes stay inside a batch")
    text = (text or "").strip()
    if not text:
        raise ValueError("give the note's text")
    target_rel = L.rel_path(root, target)
    with _locked(target):
        entry = {"id": len(_lines(target / INBOX_FILE)) + 1, "at": now(), "from": L.rel_path(root, src), "text": text}
        _append(target / INBOX_FILE, entry)
        _append(target / EVENTS_FILE, {"at": entry["at"], "kind": "note",
                                       "text": f"from {entry['from']}: {text}"[:300]})
    return {"to": target_rel, **entry}


def inbox(root: Path, ref: str, after: int = 0) -> list[dict]:
    return [n for n in _lines(group_dir(root, ref) / INBOX_FILE) if int(n.get("id", 0)) > after]


# ---------------------------------------------------------------------------- the board

def _lane(st: dict, blocked_by: list[str]) -> str:
    phase = st.get("phase") or "ready"
    state = (st.get("session") or {}).get("state")
    if phase in FINISHED:
        return "done"
    if state in ("waiting", "permission"):
        return "needs_you"
    if state == "working":
        return "working"
    if blocked_by or phase == "blocked":
        return "waits"
    if state == "ended":
        return "stopped"
    return "ready"


NEED_LIST = re.compile(r'id="need".*?<ol[^>]*>(.*?)</ol>', re.S)


def _decisions(page: Path) -> int:
    """How many items the page's "What I need from you" lists: the number on the board's badge."""
    try:
        found = NEED_LIST.search(page.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0
    return found.group(1).count("<li") if found else 0


def _group_view(root: Path, batch: Path, name: str, phases: dict[str, str]) -> dict:
    d = batch / name
    meta = L.read_json(d / L.SUBJECT_FILE)
    g = meta.get("group") or {}
    st = L.read_json(d / STATUS_FILE)
    blocked_by = [w for w in g.get("waits") or [] if phases.get(w) not in FINISHED]
    pages = [p for p in P.list_passes(d, with_titles=False) if p["kind"] == "html"]
    rel = L.rel_path(root, d)
    latest = pages[-1] if pages else None
    return {
        "name": name, "path": rel, "title": meta.get("title") or L.pretty(name), "order": g.get("order", 0),
        "goal": g.get("goal", ""), "owns": g.get("owns") or [], "waits": g.get("waits") or [],
        "blocked_by": blocked_by, "topics": g.get("topics") or [], "phase": st.get("phase") or "ready",
        "note": st.get("note", ""), "pr": st.get("pr", ""), "session": st.get("session") or {},
        "updated": st.get("updated", ""), "lane": _lane(st, blocked_by), "brief": str(d / BRIEF_FILE),
        "round": latest["n"] if latest else None, "page": f"/c/{rel}/{latest['file']}" if latest else "",
        "page_mtime": latest["mtime"] if latest else "", "first_prompt": first_prompt(root, rel),
        "icon": meta.get("icon", ""), "decisions": _decisions(d / latest["file"]) if latest else 0,
    }


def board(root: Path, ref: str) -> dict:
    """Every group of the batch with its lane: needs you, working, waits for another group, ready, done."""
    batch = batch_dir(root, ref)
    meta = L.read_json(batch / BATCH_FILE)
    names = [n for n in meta.get("groups") or [] if (batch / n / L.SUBJECT_FILE).is_file()]
    phases = {n: L.read_json(batch / n / STATUS_FILE).get("phase", "") for n in names}
    groups = sorted((_group_view(root, batch, n, phases) for n in names), key=lambda g: g["order"])
    lanes = {lane: [g["name"] for g in groups if g["lane"] == lane]
             for lane in ("needs_you", "working", "waits", "stopped", "ready", "done")}
    active = len(lanes["needs_you"]) + len(lanes["working"])
    start_next = [g for g in groups if g["lane"] == "ready" and not g["session"].get("app_id")
                  ][:max(0, START_AT_ONCE - active)]
    triage = batch / (meta.get("triage") or TRIAGE)
    pages = [p for p in P.list_passes(triage, with_titles=False) if p["kind"] == "html"] if triage.is_dir() else []
    batch_rel = L.rel_path(root, batch)
    recent = sorted(({**e, "group": n} for n in names for e in _lines(batch / n / EVENTS_FILE)[-12:]),
                    key=lambda e: e.get("at", ""), reverse=True)[:16]
    return {
        "batch": batch_rel, "title": meta.get("title") or L.pretty(batch.name), "groups": groups, "lanes": lanes,
        "recent": recent,
        "start_next": start_next, "start_at_once": START_AT_ONCE, "fast": meta.get("fast") or [],
        "info": meta.get("info") or [], "split": meta.get("split", ""),
        "triage": {"path": L.rel_path(root, triage), "page": f"/c/{L.rel_path(root, triage)}/{pages[-1]['file']}"
                   if pages else ""},
        "ledger": len(ledger(root, batch_rel)["decisions"]),
    }


def team(root: Path, ref: str) -> dict:
    """The batch a subject is part of, with the groups a team of sessions works on: once split, its groups
    (done or not); before, the session groups its latest triage pass proposes, at the paths split will give."""
    batch = batch_dir(root, ref)
    meta = L.read_json(batch / BATCH_FILE)
    rel = L.rel_path(root, batch)
    if meta.get("split"):
        groups = [{"name": g["name"], "title": g["title"], "icon": g["icon"], "owns": g["owns"], "path": g["path"],
                   "brief": g["brief"], "done": g["lane"] == "done"} for g in board(root, rel)["groups"]]
    else:
        try:
            proposed = [g for g in read_triage(root, batch)["groups"] if g["lane"] == "session"]
        except L.LayoutError:
            proposed = []
        if len(proposed) < 2:  # not a batch: split refuses it, and the triage session works alone
            proposed = []
        groups = [{"name": g["name"], "title": g["title"], "icon": "", "owns": g["owns"],
                   "path": f"{rel}/{g['name']}", "brief": str(batch / g["name"] / BRIEF_FILE), "done": False}
                  for g in proposed]
    return {"path": rel, "dir": str(batch), "title": meta.get("title") or L.pretty(batch.name),
            "repo": str(Path(meta["repo"]).expanduser()) if meta.get("repo") else "", "split": bool(meta.get("split")),
            "triage": L.rel_path(root, batch / (meta.get("triage") or TRIAGE)), "groups": groups}


def group(root: Path, ref: str) -> dict:
    """One group: its board entry, its last events, its inbox, and the rules that bind it."""
    d = group_dir(root, ref)
    batch = d.parent
    meta = L.read_json(batch / BATCH_FILE)
    phases = {n: L.read_json(batch / n / STATUS_FILE).get("phase", "") for n in meta.get("groups") or []}
    view = _group_view(root, batch, d.name, phases)
    return {**view, "events": events(root, view["path"]), "inbox": inbox(root, view["path"]),
            "rules": ledger(root, view["path"])["decisions"], "batch": L.rel_path(root, batch)}
