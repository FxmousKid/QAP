"""git-storage, a core plugin: the whole content root (projects, folders, subjects, passes, images) backed up
in a remote git repository, the way the Obsidian Git plugin backs up a vault.

  qap storage git init --remote <url>        set it up, or restore a backup into an empty content root
  qap storage git sync [-m MSG] [--no-push]  commit everything, pull, push
  qap storage git status [--fetch]           what is not backed up yet, a conflict, warnings
  qap storage git log [-n N]                 the latest commits
  qap storage git commit [-m MSG]            commit here only (no network)
  qap storage git resolve --mine|--theirs    settle a conflict, keeping one side (the other stays in history)

Automatic, once set up: after each `qap build`, every N minutes while `qap serve` runs, and when it starts.
The settings tab is `qap plugins config git-storage` (or the dashboard's Plugins page). The git logic is in
store.py; this file only wires it to qap.
"""
from __future__ import annotations

from qap.plugins import Plugin, PluginError, Setting

from .store import GitError, Store

GROUP = ("storage", "git")


class GitStorage(Plugin):
    def onload(self) -> None:
        self.add_settings(
            Setting("auto_sync_minutes", "Auto-sync interval (minutes)", 10,
                    "While `qap serve` runs: commit, pull and push every N minutes. 0 turns it off."),
            Setting("sync_after_build", "Sync after each build", True,
                    "Commit, pull and push after every `qap build`."),
            Setting("sync_on_startup", "Sync when the dashboard starts", True,
                    "When `qap serve` starts: bring in what other machines pushed, push what is new here."),
            Setting("push", "Push", True, "Off: commit and pull only; nothing leaves this machine."),
            Setting("sync_method", "Pull with", "merge",
                    "merge keeps both histories as they were; rebase replays this machine's commits on top.",
                    choices=("merge", "rebase")),
            Setting("commit_message", "Commit message", "qap {{trigger}}: {{subjects}} ({{fileCount}}, {{hostname}})",
                    "Placeholders: {{date}} {{hostname}} {{numFiles}} (3) {{fileCount}} (3 files) {{files}} "
                    "{{subjects}} {{trigger}} (build, interval, startup, manual, init, resolve)."),
            Setting("date_format", "Date format", "%Y-%m-%d %H:%M", "strftime codes, for {{date}}."),
            Setting("list_files_in_body", "List the files in the commit body", True, ""),
            Setting("sign_commits", "Sign commits", "inherit",
                    "inherit: as your git config says (commit.gpgsign). off: qap's commits are not signed, so a "
                    "background sync never waits on a signing prompt.", choices=("inherit", "off")),
        )
        self.add_command("init", "Set up the git backup", self.cmd_init, cli=GROUP + ("init",), args=[
            (["--remote"], {"required": True,
                            "help": "the remote's URL: git@host:you/passes.git, https://…, or file:///path"}),
            (["--branch"], {"default": "main", "help": "branch for a new repository (default: main)"}),
            (["--remote-name"], {"dest": "remote_name", "default": "origin", "help": "default: origin"}),
        ])
        self.add_command("sync", "Commit and sync now", self.cmd_sync, cli=GROUP + ("sync",), args=[
            (["--message", "-m"], {"help": "the commit message (default: the template)"}),
            (["--no-push"], {"dest": "no_push", "action": "store_true", "help": "commit and pull, do not push"}),
        ])
        self.add_command("status", "Backup status", self.cmd_status, cli=GROUP + ("status",), args=[
            (["--fetch"], {"action": "store_true", "help": "ask the remote first (ahead / behind are fresh)"}),
        ])
        self.add_command("log", "Latest backups", self.cmd_log, cli=GROUP + ("log",), args=[
            (["-n"], {"dest": "n", "type": int, "default": 20, "help": "how many commits (default 20)"}),
        ])
        self.add_command("commit", "Commit here only", self.cmd_commit, cli=GROUP + ("commit",), args=[
            (["--message", "-m"], {"help": "the commit message (default: the template)"}),
        ])
        self.add_command("resolve", "Settle a conflict", self.cmd_resolve, cli=GROUP + ("resolve",), needs_input=True, args=[
            (["--mine"], {"dest": "keep", "action": "store_const", "const": "mine",
                          "help": "keep this machine's version of the conflicting files"}),
            (["--theirs"], {"dest": "keep", "action": "store_const", "const": "theirs",
                            "help": "keep the remote's version"}),
        ])
        self.register_event("pass_built", self.on_build)
        self.register_event("startup", self.on_startup)
        self.register_interval(lambda: self.settings["auto_sync_minutes"] * 60, self.on_interval)
        self.register_route("GET", "status", self.route_status)

    def store(self, interactive: bool = False) -> Store:
        return Store(self.app.root, self.settings, interactive=interactive)

    # ---------------------------------------------------------------- commands (CLI and dashboard)
    def cmd_init(self, opts) -> dict:
        try:
            return self.store(opts.interactive).init(opts.remote or "", opts.branch or "main",
                                                     opts.remote_name or "origin")
        except GitError as e:
            raise PluginError(str(e))

    def cmd_sync(self, opts) -> dict:
        try:
            return self.store(opts.interactive).sync("manual", opts.message, push=False if opts.no_push else None)
        except GitError as e:
            raise PluginError(str(e))

    def cmd_status(self, opts) -> dict:
        try:
            info = self.store(opts.interactive).status(fetch=opts.fetch)
        except GitError as e:
            raise PluginError(str(e))
        info["auto"] = self.auto()
        return info

    def cmd_log(self, opts) -> dict:
        try:
            commits = self.store().log(opts.n)
        except GitError as e:
            raise PluginError(str(e))
        text = "\n".join(f"{c['sha']}  {c['date'][:16].replace('T', ' ')}  {c['subject']}" for c in commits)
        return {"commits": commits, "text": text or "no commit yet"}

    def cmd_commit(self, opts) -> dict:
        s = self.store()
        try:
            s.require_initialized()
            with s.locked():
                s.require_clean()
                done = s.commit("manual", opts.message)
        except GitError as e:
            raise PluginError(str(e))
        return {"committed": done, "text": f"git: committed {done['files']} file(s) as {done['sha']}" if done
                else "git: nothing to commit"}

    def cmd_resolve(self, opts) -> dict:
        if not opts.keep:
            raise PluginError("say which side to keep: --mine or --theirs")
        try:
            return self.store(opts.interactive).resolve(opts.keep)
        except GitError as e:
            raise PluginError(str(e))

    # ---------------------------------------------------------------- automatic syncs
    def auto(self) -> dict:
        s = self.settings
        return {"interval_minutes": s["auto_sync_minutes"], "after_build": s["sync_after_build"],
                "on_startup": s["sync_on_startup"], "push": s["push"]}

    def _auto_sync(self, trigger: str, interactive: bool = False) -> dict | None:
        store = self.store(interactive)
        if not store.initialized():
            return None  # not set up for this content root: the plugin stays out of the way
        try:
            return store.sync(trigger)
        except GitError as e:
            return {"ok": False, "error": str(e), "text": f"git: {e}"}

    def on_build(self, payload: dict) -> dict | None:
        if not self.settings["sync_after_build"]:
            return None
        return self._auto_sync("build", bool(payload.get("interactive")))

    def on_startup(self, payload: dict) -> None:
        if self.settings["sync_on_startup"]:
            result = self._auto_sync("startup")
            if result:
                self.log(result["text"])

    def on_interval(self) -> None:
        result = self._auto_sync("interval")
        if result and (not result.get("ok") or result.get("committed") or result.get("pulled")):
            self.log(result["text"])  # quiet when there was nothing to do

    # ---------------------------------------------------------------- dashboard
    def route_status(self, body: dict) -> dict:
        info = self.store().status(fetch=False)
        info["auto"] = self.auto()
        return info
