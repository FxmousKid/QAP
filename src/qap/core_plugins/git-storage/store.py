"""The content root as a git repository, synced with one remote: commit everything, fetch, merge (or rebase),
push. Three rules hold everywhere:

  - never force-push: a push the remote refuses is retried once after a pull, then reported;
  - never leave conflict markers in the passes: a merge that conflicts is undone (merge --abort), the
    conflicting files are recorded, automatic syncs pause, and `resolve --mine|--theirs` or a hand merge
    finishes it (the side not kept stays in the history);
  - credentials are git's business (your ssh agent, your credential helper): qap never sees or stores one.
    Background syncs run without a terminal, so a passphrase prompt fails instead of hanging.

GIT_CEILING_DIRECTORIES pins every git call to the content root itself, so a content root that sits inside
another repository (~/Desktop/Dev/ai/QAP/contents inside ~/Desktop/Dev/ai) never touches that repository.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from qap import layout as L

try:
    import fcntl
except ImportError:  # not POSIX: syncs are not serialised across processes
    fcntl = None

STATE_FILE = "qap-storage.json"  # in .git/: never committed, one per repository
LOCK_FILE = "qap-storage.lock"
BIG_FILE = 50 * 1024 * 1024  # GitHub warns at 50 MB and refuses 100 MB
GITIGNORE = """\
# Written by `qap storage git init`. qap never rewrites this file: edit it freely.
# Not backed up: system files and caches.
.DS_Store
Thumbs.db
__pycache__/
*.pyc
*.tmp
"""


class GitError(Exception):
    """A git step failed; the message says which and what to do."""


class Conflict(GitError):
    def __init__(self, files: list[str], ref: str, detail: str = ""):
        self.files, self.ref, self.detail = files, ref, detail
        super().__init__(f"conflict with {ref} on {len(files)} file(s): {', '.join(files[:5])}")


class Rejected(GitError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, root: Path, settings: dict | None = None, interactive: bool = False, timeout: int = 90):
        self.root = Path(root).expanduser().resolve()
        self.settings = settings or {}
        self.interactive = interactive
        self.timeout = timeout

    # ------------------------------------------------------------------ running git
    def git(self, *args: str, check: bool = True, network: bool = False, sign: bool = False,
            cwd: Path | None = None, ceiling: bool = True) -> subprocess.CompletedProcess:
        pre = ["-c", "core.quotepath=false"]
        if sign and self.settings.get("sign_commits") == "off":
            pre += ["-c", "commit.gpgsign=false"]
        env = dict(os.environ)
        if ceiling:
            env["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        if not self.interactive:
            env["GIT_TERMINAL_PROMPT"] = "0"
        timeout = self.timeout if network else 120
        try:
            proc = subprocess.run(["git", *pre, *args], cwd=cwd or self.root, capture_output=True, text=True,
                                  env=env, timeout=timeout, start_new_session=not self.interactive,
                                  stdin=None if self.interactive else subprocess.DEVNULL)
        except FileNotFoundError:
            raise GitError("git is not installed (or not on PATH)")
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} gave no answer in {timeout} s"
                           + (" (network down, or a credential prompt with no terminal?)" if network else ""))
        if check and proc.returncode:
            raise GitError(f"git {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()}")
        return proc

    def out(self, *args: str, **kw) -> str:
        return self.git(*args, **kw).stdout.strip()

    # ------------------------------------------------------------------ facts about the repository
    def is_repo(self) -> bool:
        if not (self.root / ".git").exists():
            return False
        proc = self.git("rev-parse", "--show-toplevel", check=False)
        return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == self.root

    def git_dir(self) -> Path:
        return Path(self.out("rev-parse", "--absolute-git-dir"))

    def parent_repo(self) -> Path | None:
        """The repository the content root sits inside, when it is not its own."""
        if not self.root.is_dir():
            return None
        proc = self.git("rev-parse", "--show-toplevel", check=False, ceiling=False)
        top = Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else None
        return top if top and top != self.root else None

    def state(self) -> dict:
        try:
            data = json.loads((self.git_dir() / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError, GitError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_state(self, **changes) -> dict:
        state = {k: v for k, v in {**self.state(), **changes}.items() if v is not None}
        self._write_state(state)
        return state

    def initialized(self) -> bool:
        return self.is_repo() and bool(self.state().get("remote"))

    @property
    def remote(self) -> str:
        return self.state().get("remote") or "origin"

    def branch(self) -> str:
        proc = self.git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        return proc.stdout.strip() or self.state().get("branch") or "main"

    def remote_ref(self) -> str:
        return f"{self.remote}/{self.branch()}"

    def has_ref(self, ref: str) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False).returncode == 0

    def has_commits(self) -> bool:
        return self.has_ref("HEAD")

    def remote_url(self, name: str | None = None) -> str | None:
        proc = self.git("remote", "get-url", name or self.remote, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def changes(self) -> list[dict]:
        raw = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        items, parts, i = [], raw.split("\0"), 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            if code[0] in "RC":
                i += 1  # the rename's old path follows
            items.append({"status": code.strip() or "?", "path": path})
        return items

    def in_progress(self) -> str | None:
        d = self.git_dir()
        if (d / "rebase-merge").exists() or (d / "rebase-apply").exists():
            return "rebase"
        if (d / "MERGE_HEAD").exists():
            return "merge"
        if (d / "CHERRY_PICK_HEAD").exists() or (d / "REVERT_HEAD").exists():
            return "cherry-pick"
        return None

    def unmerged(self) -> list[str]:
        return [p for p in self.git("diff", "--name-only", "--diff-filter=U", "-z").stdout.split("\0") if p]

    def counts(self, ref: str) -> tuple[int, int]:
        """(ahead, behind): commits here that ref lacks, commits in ref that are not here."""
        if not self.has_commits():
            return 0, (int(self.out("rev-list", "--count", ref)) if self.has_ref(ref) else 0)
        ahead, behind = self.out("rev-list", "--left-right", "--count", f"HEAD...{ref}").split()
        return int(ahead), int(behind)

    def short(self, ref: str = "HEAD") -> str:
        return self.out("rev-parse", "--short", ref)

    # ------------------------------------------------------------------ one process at a time
    @contextlib.contextmanager
    def locked(self, wait: float = 60.0):
        if fcntl is None:
            yield
            return
        with open(self.git_dir() / LOCK_FILE, "w") as handle:
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise GitError("another qap sync is running on this content root; try again in a moment")
                    time.sleep(0.2)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # ------------------------------------------------------------------ the steps
    def commit(self, trigger: str, message: str | None = None) -> dict | None:
        """Stage everything (the .gitignore decides what is left out) and commit it. None: nothing to commit."""
        self.git("add", "--all")
        files = [p for p in self.git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
        if not files:
            return None
        subject = message or self.render(self.settings.get("commit_message") or "qap {{trigger}}: {{subjects}}",
                                         files, trigger)
        args = ["commit", "--quiet", "-m", subject]
        if self.settings.get("list_files_in_body", True) and not message:
            listed = files[:200] + ([f"… and {len(files) - 200} more"] if len(files) > 200 else [])
            args += ["-m", "\n".join(listed)]
        proc = self.git(*args, check=False, sign=True)
        if proc.returncode:
            detail = (proc.stderr or proc.stdout).strip()
            if "identity" in detail.lower() or "user.email" in detail:
                detail += "\n  set it once: git config --global user.name 'Your Name'; " \
                          "git config --global user.email you@example.com"
            elif "gpg" in detail.lower() or "sign" in detail.lower():
                detail += "\n  automatic commits cannot sign without a prompt: " \
                          "qap plugins config git-storage sign_commits off"
            raise GitError(f"git commit failed: {detail}")
        return {"sha": self.short(), "files": len(files), "message": subject}

    def render(self, template: str, files: list[str], trigger: str) -> str:
        subjects = self.subjects_of(files)
        shown = ", ".join(subjects[:3]) + (f" +{len(subjects) - 3}" if len(subjects) > 3 else "")
        values = {
            "date": datetime.now().strftime(self.settings.get("date_format") or "%Y-%m-%d %H:%M"),
            "hostname": socket.gethostname().split(".")[0],
            "numFiles": str(len(files)),
            "fileCount": f"{len(files)} file{'' if len(files) == 1 else 's'}",
            "files": ", ".join(files[:5]) + (f" +{len(files) - 5}" if len(files) > 5 else ""),
            "subjects": shown or "/",
            "trigger": trigger,
        }
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", value)
        return template.strip() or f"qap {trigger}"

    def subjects_of(self, files: list[str]) -> list[str]:
        """The subjects (or folders) the changed files belong to, in first-seen order."""
        seen: list[str] = []
        for f in files:
            parts = f.split("/")[:-1]
            where = "/"
            for depth in range(len(parts), 0, -1):
                d = self.root.joinpath(*parts[:depth])
                if d.is_dir() and L.is_subject_dir(d):
                    where = "/".join(parts[:depth])
                    break
            else:
                where = "/".join(p for p in parts if p != "img") or "/"
            if where not in seen:
                seen.append(where)
        return [w for w in seen if w != "/"] or seen  # top-level files (.gitignore) only when alone

    def fetch(self) -> None:
        self.git("fetch", "--quiet", "--prune", self.remote, network=True)

    def integrate(self, ref: str, unrelated: bool = False) -> int:
        """Bring ref's commits in (merge, or rebase when set and there is something to replay). Returns how
        many commits came in. On a conflict, undoes the merge or rebase and raises Conflict."""
        if not self.has_ref(ref):
            return 0
        ahead, behind = self.counts(ref)
        if not behind:
            return 0
        if not self.has_commits():  # nothing here yet (not even a file): take the remote's history as is
            self.git("checkout", "--quiet", "-B", self.branch(), "--track", ref)
            return behind
        if self.settings.get("sync_method") == "rebase" and ahead and not unrelated:
            args = ["rebase", "--quiet", ref]
        else:
            args = ["merge", "--quiet", "--no-edit", ref] + (["--allow-unrelated-histories"] if unrelated else [])
        proc = self.git(*args, check=False, sign=True)
        if proc.returncode:
            files = self.unmerged()
            state = self.in_progress()
            if state == "rebase":
                self.git("rebase", "--abort", check=False)
            elif state == "merge":
                self.git("merge", "--abort", check=False)
            detail = (proc.stderr or proc.stdout).strip()
            if files:
                raise Conflict(files, ref, detail)
            raise GitError(f"git {args[0]} {ref} failed (nothing changed): {detail}")
        return behind

    def push(self) -> int:
        """Push this branch to the remote: never forced. Returns how many commits went out."""
        branch, ref = self.branch(), self.remote_ref()
        ahead = self.counts(ref)[0] if self.has_ref(ref) else int(self.out("rev-list", "--count", "HEAD"))
        if not ahead:
            return 0
        proc = self.git("push", "--quiet", "--set-upstream", self.remote, f"HEAD:refs/heads/{branch}",
                        check=False, network=True)
        if proc.returncode:
            detail = (proc.stderr or proc.stdout).strip()
            if "rejected" in detail or "fetch first" in detail or "non-fast-forward" in detail:
                raise Rejected(detail)
            raise GitError(f"git push failed: {detail}")
        return ahead

    # ------------------------------------------------------------------ what the commands do
    def require_initialized(self) -> None:
        if not self.root.is_dir():
            raise GitError(f"content root {self.root} does not exist")
        if not self.initialized():
            raise GitError(f"{self.root} is not backed up with git yet: qap storage git init --remote <url>")

    def require_clean(self) -> None:
        """No half-done merge or rebase (checked under the lock: another sync may be mid-merge)."""
        state = self.in_progress()
        if state:
            raise GitError(f"a {state} is in progress in {self.root}: finish it (or `git {state} --abort`) "
                           f"and run `qap storage git sync` again")
        if self.unmerged():
            raise GitError(f"files with unresolved conflicts in {self.root}: resolve them, commit, then sync")

    def init(self, url: str, branch: str = "main", remote: str = "origin") -> dict:
        if not self.root.is_dir():
            raise GitError(f"content root {self.root} does not exist")
        url = url.strip()
        if not url:
            raise GitError("give the remote's URL: --remote git@github.com:you/qa-passes.git (or a file:// path)")
        notes = []
        if not self.is_repo():
            parent = self.parent_repo()
            self.git("init", "--quiet", f"--initial-branch={branch}")
            notes.append(f"created a git repository in {self.root}")
            if parent and self.git("check-ignore", "-q", str(self.root), cwd=parent, check=False,
                                   ceiling=False).returncode != 0:
                notes.append(f"note: {self.root} sits inside the repository {parent}; add "
                             f"'{self.root.relative_to(parent).as_posix()}/' to {parent / '.gitignore'} "
                             f"so that repository does not see a nested one")
        else:
            branch = self.branch()
        current = self.remote_url(remote)
        if current is None:
            self.git("remote", "add", remote, url)
        elif current != url:
            raise GitError(f"remote {remote} already points at {current}; qap never rewrites a remote "
                           f"(git -C {self.root} remote set-url {remote} <url>, then init again)")
        wrote_ignore = False
        if not (self.root / ".gitignore").exists():
            (self.root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
            wrote_ignore = True
            notes.append("wrote .gitignore (system files and caches)")
        self.save_state(remote=remote, branch=branch, initialized=self.state().get("initialized") or now())
        with self.locked():
            try:
                self.fetch()
            except GitError as e:
                self.save_state(last_error={"at": now(), "error": str(e)})
                return {"ok": False, "notes": notes, "error": str(e),
                        "text": "\n".join(notes + [f"set up locally, but the remote is out of reach: {e}",
                                                   "run `qap storage git sync` once it is reachable"])}
            ref = self.remote_ref()
            if self.has_ref(ref) and not self.has_commits():
                local = [c for c in self.changes() if not (wrote_ignore and c["path"] == ".gitignore")]
                if not local:  # an empty content root: restore the backup
                    if wrote_ignore:
                        (self.root / ".gitignore").unlink()
                    self.git("checkout", "--quiet", "-B", branch, "--track", ref)
                    notes.append(f"restored {self.out('rev-list', '--count', 'HEAD')} commit(s) from {ref}")
                    self.save_state(last_sync={"at": now(), "trigger": "init", "commit": self.short()})
                    return {"ok": True, "notes": notes, "restored": True, "text": "\n".join(notes)}
            result = self._sync(trigger="init", message=None, push=True, unrelated=True)
        result["notes"] = notes
        result["text"] = "\n".join(notes + [result["text"]])
        return result

    def sync(self, trigger: str = "manual", message: str | None = None, push: bool | None = None) -> dict:
        """Commit everything, pull, push. Automatic triggers stay paused while a conflict is unresolved."""
        self.require_initialized()
        conflict = self.state().get("conflict")
        if conflict and trigger != "manual":
            return {"ok": False, "skipped": "conflict", "conflict": conflict,
                    "text": f"git sync paused: conflict with {conflict['ref']} on {', '.join(conflict['files'][:3])} "
                            f"(qap storage git status)"}
        with self.locked(wait=60 if trigger == "manual" else 20):
            self.require_clean()
            return self._sync(trigger, message, push)

    def _sync(self, trigger: str, message: str | None, push: bool | None, unrelated: bool = False) -> dict:
        push = self.settings.get("push", True) if push is None else push
        committed = self.commit(trigger, message)
        out = {"ok": True, "trigger": trigger, "committed": committed, "pulled": 0, "pushed": 0}
        words = [f"committed {committed['files']} file(s) as {committed['sha']}"] if committed else []
        ref = self.remote_ref()
        try:
            self.fetch()
            out["pulled"] = self.integrate(ref, unrelated)
            if push:
                try:
                    out["pushed"] = self.push()
                except Rejected:  # the remote moved since our fetch: pull once more, push once more
                    self.fetch()
                    out["pulled"] += self.integrate(ref)
                    out["pushed"] = self.push()
        except Conflict as c:
            conflict = {"at": now(), "trigger": trigger, "ref": c.ref, "files": c.files,
                        "theirs": self.short(c.ref), "mine": self.short()}
            self.save_state(conflict=conflict, last_error={"at": now(), "error": str(c)})
            return {**out, "ok": False, "conflict": conflict, "text": self.conflict_text(conflict, words)}
        except GitError as e:
            self.save_state(last_error={"at": now(), "error": str(e)})
            kept = " (committed here; nothing lost)" if committed else ""
            return {**out, "ok": False, "error": str(e), "text": "; ".join(words + [f"sync failed{kept}: {e}"])}
        if out["pulled"]:
            words.append(f"pulled {out['pulled']} commit(s)")
        if out["pushed"]:
            words.append(f"pushed {out['pushed']} commit(s) to {ref}")
        if not words:
            words.append(f"up to date with {ref}")
        elif not push and (not self.has_ref(ref) or self.counts(ref)[0]):
            words.append("not pushed (push is off)")
        state = self.state()
        state.pop("conflict", None)
        state.pop("last_error", None)
        state["last_sync"] = {"at": now(), "trigger": trigger, "commit": self.short() if self.has_commits() else "",
                              "pulled": out["pulled"], "pushed": out["pushed"],
                              "committed": committed["files"] if committed else 0}
        self._write_state(state)
        out["text"] = "git: " + ", ".join(words)
        return out

    def _write_state(self, state: dict) -> None:
        path = self.git_dir() / STATE_FILE
        tmp = path.with_name(STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def conflict_text(self, conflict: dict, words: list[str] | None = None) -> str:
        files = conflict["files"]
        listed = "\n".join(f"    {f}" for f in files[:12]) + (f"\n    … and {len(files) - 12} more" if len(files) > 12 else "")
        head = ("git: " + "; ".join(words) + "\n") if words else ""
        return (f"{head}git: CONFLICT with {conflict['ref']}: this machine and the remote both changed\n{listed}\n"
                f"  Nothing was pushed and your files are as they were (the merge was undone).\n"
                f"  Automatic syncs are paused until this is settled. Either:\n"
                f"    qap storage git resolve --mine     keep this machine's version of those files\n"
                f"    qap storage git resolve --theirs   keep the remote's version\n"
                f"  (the version not kept stays in the history), or merge by hand in {self.root}\n"
                f"  (git merge {conflict['ref']}, fix, commit) and run `qap storage git sync`.")

    def resolve(self, keep: str) -> dict:
        """Finish a recorded conflict by keeping one side, file by file; the other side stays in history."""
        if keep not in ("mine", "theirs"):
            raise GitError("keep must be mine or theirs")
        self.require_initialized()
        with self.locked():
            self.require_clean()
            committed = self.commit("resolve")
            self.fetch()
            ref = self.remote_ref()
            if not self.has_ref(ref):
                raise GitError(f"{ref} does not exist: nothing to resolve against")
            proc = self.git("merge", "--quiet", "--no-edit", ref, check=False, sign=True)
            files = self.unmerged() if proc.returncode else []
            if proc.returncode and not files:
                self.git("merge", "--abort", check=False)
                raise GitError(f"git merge {ref} failed: {(proc.stderr or proc.stdout).strip()}")
            other = self.short(ref if keep == "mine" else "HEAD")
            for f in files:
                side = "--ours" if keep == "mine" else "--theirs"
                if self.git("checkout", side, "--", f, check=False).returncode:
                    self.git("rm", "--quiet", "--", f)  # that side deleted it
                else:
                    self.git("add", "--", f)
            if files:
                self.git("commit", "--quiet", "-m",
                         f"qap resolve: kept {'this machine' if keep == 'mine' else 'the remote'}'s version of "
                         f"{len(files)} file(s)", "-m", "\n".join(files), sign=True)
            pushed = self.push() if self.settings.get("push", True) else 0
            state = self.state()
            state.pop("conflict", None)
            state.pop("last_error", None)
            state["last_sync"] = {"at": now(), "trigger": "resolve", "commit": self.short(), "pulled": 0,
                                  "pushed": pushed, "committed": committed["files"] if committed else 0}
            self._write_state(state)
        if not files:
            return {"ok": True, "files": [], "text": f"git: no conflict any more; merged {ref}"
                                                     + (f" and pushed {pushed} commit(s)" if pushed else "")}
        return {"ok": True, "files": files, "kept": keep, "other": other, "pushed": pushed,
                "text": f"git: kept {'your' if keep == 'mine' else 'the remote'} version of {len(files)} file(s)"
                        + (f", pushed {pushed} commit(s)" if pushed else "")
                        + f".\n  The other version is in commit {other}: git -C {self.root} show {other}:<path>"}

    # ------------------------------------------------------------------ reading
    def log(self, n: int = 20) -> list[dict]:
        if not self.is_repo() or not self.has_commits():
            return []
        raw = self.git("log", f"-n{n}", "--name-only", "--format=%x1e%h%x1f%cI%x1f%an%x1f%s").stdout
        out = []
        for record in raw.split("\x1e"):
            lines = [line for line in record.strip("\n").split("\n")]
            if not lines or not lines[0]:
                continue
            sha, date, author, subject = (lines[0].split("\x1f") + ["", "", "", ""])[:4]
            files = [f for f in lines[1:] if f.strip()]
            out.append({"sha": sha, "date": date, "author": author, "subject": subject, "files": len(files)})
        return out

    def status(self, fetch: bool = False) -> dict:
        info: dict = {"root": str(self.root), "repo": self.is_repo(), "initialized": False, "warnings": []}
        if not info["repo"]:
            parent = self.parent_repo()
            info["parent_repo"] = str(parent) if parent else None
            info["text"] = (f"{self.root}: not backed up with git. "
                            f"Set it up: qap storage git init --remote <url>")
            return info
        state = self.state()
        info["initialized"] = bool(state.get("remote"))
        ref = self.remote_ref()
        if fetch and info["initialized"]:
            try:
                self.fetch()
            except GitError as e:
                info["warnings"].append(f"fetch failed: {e}")
        ahead, behind = self.counts(ref) if self.has_ref(ref) else (None, None)
        changes = self.changes()
        info.update({
            "branch": self.branch(), "remote": {"name": self.remote, "url": self.remote_url()},
            "upstream": ref if self.has_ref(ref) else None, "ahead": ahead, "behind": behind,
            "changes": changes[:200], "changed": len(changes), "in_progress": self.in_progress(),
            "conflict": state.get("conflict"), "last_sync": state.get("last_sync"),
            "last_error": state.get("last_error"), "recent": self.log(8),
        })
        info["warnings"] += self.warnings()
        info["text"] = self.status_text(info)
        return info

    def warnings(self) -> list[str]:
        out = []
        outside, big = [], []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                p = Path(dirpath) / name
                if p.is_symlink():
                    target = p.resolve()
                    if self.root not in target.parents and target != self.root:
                        outside.append(p.relative_to(self.root).as_posix())
                elif p.is_file() and p.stat().st_size > BIG_FILE:
                    big.append(p.relative_to(self.root).as_posix())
        if outside:
            out.append(f"{len(outside)} symlink(s) point outside the content root; git keeps the link, not the "
                       f"file: {', '.join(outside[:3])}")
        if big:
            out.append(f"{len(big)} file(s) over 50 MB (GitHub refuses 100 MB): {', '.join(big[:3])}")
        if not self.out("config", "user.email", check=False):
            out.append("no git identity: commits will fail (git config --global user.name / user.email)")
        if self.settings.get("sign_commits", "inherit") == "inherit" and \
                self.out("config", "--bool", "commit.gpgsign", check=False) == "true":
            out.append("your commits are signed (commit.gpgsign): background syncs may prompt or fail; "
                       "`qap plugins config git-storage sign_commits off` signs nothing qap commits")
        return out

    def status_text(self, info: dict) -> str:
        lines = [f"{info['root']}  ({info['branch']} -> {info['remote']['url'] or 'no remote'})"]
        if not info["initialized"]:
            lines.append("  a git repository, not set up by qap: qap storage git init --remote <url>")
        if info["conflict"]:
            lines.append(self.conflict_text(info["conflict"]))
        if info["in_progress"]:
            lines.append(f"  a {info['in_progress']} is in progress: finish or abort it")
        if info["upstream"]:
            lines.append(f"  {info['ahead']} to push, {info['behind']} to pull (as of the last fetch)")
        else:
            lines.append("  never pushed")
        lines.append(f"  {info['changed']} uncommitted change(s)"
                     + "".join(f"\n    {c['status']:>2} {c['path']}" for c in info["changes"][:10])
                     + (f"\n    … and {info['changed'] - 10} more" if info["changed"] > 10 else ""))
        last = info.get("last_sync")
        if last:
            lines.append(f"  last sync {last['at']} ({last['trigger']}) at {last.get('commit') or '—'}")
        if info.get("last_error") and not info["conflict"]:
            lines.append(f"  last error {info['last_error']['at']}: {info['last_error']['error']}")
        lines += [f"  ! {w}" for w in info["warnings"]]
        return "\n".join(lines)
