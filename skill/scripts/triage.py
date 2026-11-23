#!/usr/bin/env python3
"""Read the groups of a triage pass: which topics go to which group session, the fast lane and the info list.

Usage: python3 triage.py <QA-PASS-N.html>     prints the groups as JSON

A triage pass is a QA pass with <meta name="qa-kind" content="triage">. Its topics (h2 id="pN") sit under
group headings. A group heading is an h2.grp with its lane and what the group needs:

  <h2 id="g-reanalysis" class="grp" data-lane="session" data-group="reanalysis"
      data-owns="MeetingListViewModel.kt; the analysis read policy" data-waits="">
    Re-analysis: what is current, and who sees it</h2>
  <p class="goal">During and after a re-analysis, every viewer sees the newest analysis's state.</p>
  <h2 id="p4">…</h2> … <h2 id="p11">…</h2>

  data-lane    session: one session per group · fast: one PR each, no session · info: nothing to change
  data-group   a session group's folder name (lower-case letters, digits, '-'); qap split creates it
  data-owns    the files or contracts the group owns, ';'-separated; in a batch each one has one owner
  data-waits   the groups whose PR merges first, ','-separated
  p.goal       one sentence: what is true once the group is done (the first p.goal under its heading)

The order of the session headings is the order the sessions start in. A triage pass needs at least two session
groups: with fewer, the work is one ordinary pass. check.py runs the same reading and fails a triage pass on any
of these problems; qap split refuses one too.
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser

LANES = ("session", "fast", "info")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
TAKEN = {"triage", "img", "node_modules"}  # the batch's own triage subject, and folders qap never lists
TOPIC = re.compile(r"^p\d+$")
KIND = re.compile(r'<meta\s+name="qa-kind"\s+content="([^"]*)"', re.I)


class _Headings(HTMLParser):
    """Every h2 in order (its id, class, data- attributes and text without the number span) and each p.goal."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self.h2: dict | None = None
        self.goal: dict | None = None
        self.skip = 0  # depth inside the h2's span.n

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        cls = set(a.get("class", "").split())
        if tag == "h2":
            self.h2 = {"kind": "h2", "id": a.get("id", ""), "grp": "grp" in cls, "text": "",
                       "data": {k[5:]: v for k, v in a.items() if k.startswith("data-")}}
        elif tag == "span" and self.h2 is not None and ("n" in cls or self.skip):
            self.skip += 1
        elif tag == "p" and "goal" in cls and self.h2 is None:
            self.goal = {"kind": "goal", "text": ""}

    def handle_endtag(self, tag):
        if tag == "span" and self.skip:
            self.skip -= 1
        elif tag == "h2" and self.h2 is not None:
            self.h2["text"] = " ".join(self.h2["text"].split())
            self.items.append(self.h2)
            self.h2 = None
        elif tag == "p" and self.goal is not None:
            self.goal["text"] = " ".join(self.goal["text"].split())
            self.items.append(self.goal)
            self.goal = None

    def handle_data(self, data):
        if self.h2 is not None and not self.skip:
            self.h2["text"] += data
        elif self.goal is not None:
            self.goal["text"] += data


def _split(value: str, sep: str) -> list[str]:
    return [part.strip() for part in value.split(sep) if part.strip()]


def read(html: str) -> dict:
    """The page's groups, in order, each with its topics; the topics in no group; and the problems."""
    kind = KIND.search(html)
    scan = _Headings()
    scan.feed(html)
    groups: list[dict] = []
    loose: list[str] = []
    current: dict | None = None
    for item in scan.items:
        if item["kind"] == "goal":
            if current is not None and not current["goal"]:
                current["goal"] = item["text"]
            continue
        if item["grp"]:
            data = item["data"]
            current = {"id": item["id"], "lane": data.get("lane", "").strip(), "name": data.get("group", "").strip(),
                       "title": item["text"], "goal": "", "owns": _split(data.get("owns", ""), ";"),
                       "waits": _split(data.get("waits", ""), ","), "topics": []}
            groups.append(current)
        elif TOPIC.match(item["id"]):
            num = item["id"][1:].zfill(2)
            topic = {"id": item["id"], "num": num, "title": re.sub(rf"^{num}\s*", "", item["text"])}
            if current is None or not current["lane"]:
                loose.append(item["id"])
            else:
                current["topics"].append(topic)
        else:
            current = None  # a section that is not a topic (What I need from you) ends the group, as in the page
    is_triage = bool(kind and kind.group(1).strip() == "triage")
    return {"kind": kind.group(1).strip() if kind else "", "groups": [g for g in groups if g["lane"]],
            "loose": loose, "problems": problems(groups, loose) if is_triage else []}


def problems(groups: list[dict], loose: list[str]) -> list[str]:
    found = []
    sessions = [g for g in groups if g["lane"] == "session"]
    if len(sessions) < 2:
        found.append(f"{len(sessions)} session group(s): a batch is for at least two independent problems. With fewer, "
                     "this is one ordinary pass: create a subject (qap new-subject) and write it there")
    if loose:
        found.append(f"{len(loose)} topic(s) in no group: {loose[:8]} (put each under an h2.grp with a data-lane)")
    names: dict[str, str] = {}
    for g in groups:
        where = g["id"] or g["title"][:40]
        if g["lane"] and g["lane"] not in LANES:
            found.append(f"{where}: data-lane {g['lane']!r} is not one of {', '.join(LANES)}")
        if g["lane"] != "session":
            continue
        if not NAME.match(g["name"]) or g["name"] in TAKEN:
            found.append(f"{where}: a session group needs data-group, a folder name in lower-case letters, digits "
                         f"and '-', other than {', '.join(sorted(TAKEN))} (got {g['name']!r})")
        elif g["name"] in names:
            found.append(f"{where}: data-group {g['name']!r} is already the name of {names[g['name']]}")
        else:
            names[g["name"]] = where
        if not g["topics"]:
            found.append(f"{where}: a session group with no topic")
    owners: dict[str, str] = {}
    for g in groups:
        if g["lane"] != "session":
            continue
        for item in g["owns"]:
            key = item.lower()
            if key in owners and owners[key] != g["name"]:
                found.append(f"{item!r} is owned by two groups ({owners[key]} and {g['name']}): give it one owner, "
                             f"and make the other wait for it")
            owners.setdefault(key, g["name"])
        for other in g["waits"]:
            if other == g["name"]:
                found.append(f"{g['name']} waits for itself")
            elif other not in names:
                found.append(f"{g['name']} waits for {other!r}, which is not a session group of this pass")
    cycle = _cycle({g["name"]: [w for w in g["waits"] if w in names] for g in groups if g["lane"] == "session"})
    if cycle:
        found.append(f"the groups wait for each other in a circle ({' → '.join(cycle)}): none of them could start")
    return found


def _cycle(waits: dict[str, list[str]]) -> list[str]:
    """A loop in "waits for", as the names along it (the first one repeated at the end), or []."""
    state: dict[str, int] = {}  # 1 on the current path, 2 done

    def visit(name: str, path: list[str]) -> list[str]:
        state[name] = 1
        for other in waits.get(name, []):
            if state.get(other) == 1:
                return path[path.index(other):] + [name, other] if other in path else [name, other]
            if not state.get(other):
                found = visit(other, path + [name])
                if found:
                    return found
        state[name] = 2
        return []

    for name in waits:
        if not state.get(name):
            found = visit(name, [])
            if found:
                return found
    return []


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        print(json.dumps(read(f.read()), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
