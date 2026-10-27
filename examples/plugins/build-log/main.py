"""build-log, the example plugin: every part of the plugin API in about fifty lines.

  qap plugins install examples/plugins/build-log && qap plugins enable build-log
  qap build-log show [-n 10]     the latest entries
  qap build-log clear            forget them

It hears two events (pass_built, content_changed), keeps its entries in its data.json, has one setting, one
route for its dashboard part (web/main.js), and two commands.
"""
from __future__ import annotations

from datetime import datetime

from qap.plugins import Plugin, Setting


class BuildLog(Plugin):
    def onload(self) -> None:
        self.add_settings(Setting("keep", "Entries to keep", 200, "Older entries are dropped."))
        # No cli= given: the commands are `qap build-log show` and `qap build-log clear`.
        self.add_command("show", "Build log: the latest entries", self.show,
                         args=[(["-n"], {"dest": "n", "type": int, "default": 10, "help": "how many (default 10)"})])
        self.add_command("clear", "Build log: forget every entry", self.clear)
        self.register_event("pass_built", self.on_built)
        self.register_event("content_changed", self.on_changed)
        self.register_route("GET", "entries", self.route_entries)

    # -- events
    def on_built(self, payload: dict) -> None:
        self.record(event="build", what=payload["subject"], ok=payload["ok"])
        # returning {"text": "..."} would print a line under `qap build`; a log stays quiet

    def on_changed(self, payload: dict) -> None:
        self.record(event=payload["action"], what=payload["source"], ok=True)

    # -- storage: ~/.config/qap/plugins/build-log/data.json (settings live in the same file)
    def entries(self) -> list[dict]:
        return self.load_data().get("entries") or []

    def record(self, **entry) -> None:
        data = self.load_data()
        entries = (data.get("entries") or []) + [{"at": datetime.now().isoformat(timespec="seconds"), **entry}]
        data["entries"] = entries[-self.settings["keep"]:]
        self.save_data(data)

    # -- commands: return {"text": ..., **data}; `--json` prints the data, a terminal prints the text
    def show(self, opts) -> dict:
        latest = self.entries()[-opts.n:]
        lines = [f"{e['at']}  {e['event']:<12} {e['what']}{'' if e['ok'] else '  (failed)'}" for e in latest]
        return {"entries": latest, "text": "\n".join(lines) or "nothing logged yet"}

    def clear(self, opts) -> dict:
        data = self.load_data()
        count = len(data.pop("entries", []) or [])
        self.save_data(data)
        return {"cleared": count, "text": f"forgot {count} entr{'y' if count == 1 else 'ies'}"}

    # -- route: GET /api/plugins/build-log/entries?n=20 (the query string arrives as the body)
    def route_entries(self, body: dict) -> dict:
        return {"entries": self.entries()[-int(body.get("n") or 20):]}
