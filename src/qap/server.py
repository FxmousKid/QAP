"""qap serve: the dashboard and the content from ONE origin, bound to 127.0.0.1 only.

One origin matters: the pages keep their stars in localStorage under qa-stars:<qa-project>, and browsers keep
localStorage per origin. Served from here, every pass of a subject (and the dashboard's frame) shares them.

  GET  /                  the dashboard (web/index.html)
  GET  /ui/<file>         the dashboard's modules, stylesheet, icons.json
  GET  /c/<path>          a file of the content root (pages, images); symlinks inside the root are followed
  GET  /api/tree          the tree: projects, folders, subjects, passes (qap.layout.tree)
  GET  /api/search        the search index: every project, folder, subject and pass (qap.search.build)
  POST /api/mkdir         {parent, title, icon?, color?, name?}  -> layout.make_folder (parent "@id": a top-level
                                                                    folder in that project)
  POST /api/mv            {src, dest}                            -> layout.move (dest "@id": assign_project)
  POST /api/rename        {path, title}                          -> layout.set_meta (path "@id": a project)
  POST /api/icon          {path, icon?, color?}                  -> layout.set_meta
  POST /api/rmdir         {path}                                 -> layout.remove_folder (empty folders only;
                                                                    "@id": remove_project, empty projects only)
  POST /api/project       {title, icon?, color?, id?}            -> layout.make_project

Writes are refused unless the request comes from this origin (Host and Origin checked, JSON body), so a web
page elsewhere cannot drive them; the Host check also stops DNS-rebinding reads.
"""
from __future__ import annotations

import errno
import json
import mimetypes
import posixpath
import sys
import threading
import webbrowser
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import icons, layout as L, search

WEB = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8750
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".md": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".py": "text/plain; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8"}


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class Handler(BaseHTTPRequestHandler):
    server_version = "qap"
    root: Path
    lock = threading.Lock()

    # -------------------------------------------------------------- guards
    def _hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "") in self._hosts()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in self._hosts()}

    # -------------------------------------------------------------- responses
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _file(self, path: Path) -> None:
        try:
            st = path.stat()
        except OSError:
            return self._json(404, {"ok": False, "error": "not found"})
        since = self.headers.get("If-Modified-Since")
        if since:
            try:
                if int(st.st_mtime) <= parsedate_to_datetime(since).timestamp():
                    self.send_response(304)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    return
            except (TypeError, ValueError):
                pass
        self._send(200, path.read_bytes(), content_type(path),
                   {"Last-Modified": formatdate(st.st_mtime, usegmt=True)})

    def log_message(self, fmt: str, *args) -> None:  # quiet: errors only
        if len(args) > 1 and str(args[1])[:1] in "45":
            sys.stderr.write(f"qap serve: {self.command} {self.path} -> {args[1]}\n")

    # -------------------------------------------------------------- GET
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(421, {"ok": False, "error": "use http://127.0.0.1 or http://localhost"})
        path = unquote(urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            return self._file(WEB / "index.html")
        if path.startswith("/ui/"):
            return self._file(self._under(WEB, path[len("/ui/"):]) or WEB / "__missing__")
        if path.startswith("/c/"):
            target = self._under(self.root, path[len("/c/"):])
            if target is None or not target.is_file():
                return self._json(404, {"ok": False, "error": f"no such file: {path[3:]}"})
            return self._file(target)
        if path == "/api/tree":
            try:
                return self._json(200, {"ok": True, "root": str(self.root), "tree": L.tree(self.root),
                                        "icons": sorted(icons.builtin())})
            except L.LayoutError as e:
                return self._json(500, {"ok": False, "error": str(e)})
        if path == "/api/search":
            try:
                return self._json(200, search.build(self.root))
            except L.LayoutError as e:
                return self._json(500, {"ok": False, "error": str(e)})
        if path == "/favicon.ico":
            return self._file(WEB / "favicon.svg")
        return self._json(404, {"ok": False, "error": "not found"})

    @staticmethod
    def _under(base: Path, rel: str) -> Path | None:
        """base/rel for a URL path, refusing '..' escapes and hidden segments (symlinks are followed)."""
        norm = posixpath.normpath("/" + rel).lstrip("/")
        if not norm or any(seg.startswith(".") for seg in norm.split("/")):
            return None
        return base / norm

    # -------------------------------------------------------------- POST
    def do_POST(self) -> None:
        if not self._host_ok() or not self._origin_ok():
            return self._json(403, {"ok": False, "error": "writes are only accepted from the dashboard's origin"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "error": "send JSON"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64 * 1024:
            return self._json(413, {"ok": False, "error": "body too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
        except ValueError as e:
            return self._json(400, {"ok": False, "error": f"bad JSON: {e}"})
        action = urlsplit(self.path).path.removeprefix("/api/")
        handler = ACTIONS.get(action)
        if not handler:
            return self._json(404, {"ok": False, "error": f"no action {action!r}"})
        try:
            with self.lock:
                result = handler(self.root, body)
        except (L.LayoutError, ValueError, OSError) as e:
            return self._json(400, {"ok": False, "error": str(e)})
        return self._json(200, {"ok": True, **result})


# ------------------------------------------------------------------ actions (same functions as the CLI)

def _text(body: dict, key: str, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def act_mkdir(root: Path, body: dict) -> dict:
    parent = (_text(body, "parent", False) or "").strip()
    project = parent if parent.startswith("@") else None
    parent = "" if project else L.clean_rel(parent)
    title = (_text(body, "title") or "").strip()
    if not title:
        raise ValueError("give the folder a title")
    icon = icons.validate(_text(body, "icon", False) or None)
    color = icons.validate_color(_text(body, "color", False) or None)
    base = L.slug(_text(body, "name", False) or title)
    for i in range(1, 50):
        name = base if i == 1 else f"{base}-{i}"
        rel = f"{parent}/{name}" if parent else name
        if not L.abs_path(root, rel).exists():
            break
    node = L.make_folder(root, rel, title=title, icon=icon, parents=False, project=project)
    if color:
        L.set_meta(root, node["path"], color=color)
    return {"path": node["path"]}


def act_mv(root: Path, body: dict) -> dict:
    dest = (_text(body, "dest", False) or "").strip()
    if dest.startswith("@"):
        return L.assign_project(root, _text(body, "src"), dest)
    return L.move(root, _text(body, "src"), dest)


def act_rename(root: Path, body: dict) -> dict:
    title = (_text(body, "title") or "").strip()
    if not title:
        raise ValueError("give a title")
    node = L.set_meta(root, _text(body, "path", False) or "", title=title)
    return {"path": node["path"], "title": node["title"]}


def act_icon(root: Path, body: dict) -> dict:
    icon = icons.validate(_text(body, "icon", False))
    color = icons.validate_color(_text(body, "color", False))
    node = L.set_meta(root, _text(body, "path", False) or "", icon=icon, color=color)
    return {"path": node["path"], "icon": node["icon"], "color": node["color"]}


def act_rmdir(root: Path, body: dict) -> dict:
    path = _text(body, "path").strip()
    if path.startswith("@"):
        return L.remove_project(root, path)
    return L.remove_folder(root, path)


def act_project(root: Path, body: dict) -> dict:
    title = (_text(body, "title") or "").strip()
    if not title:
        raise ValueError("give the project a title")
    icon = icons.validate(_text(body, "icon", False) or None)
    color = icons.validate_color(_text(body, "color", False) or None)
    base = L.project_id(_text(body, "id", False) or title)
    taken = {p["id"] for p in L.read_projects(root)["projects"]}
    pid = next(c for c in [base] + [f"{base}-{i}" for i in range(2, 50)] if c not in taken)
    node = L.make_project(root, pid, title=title, icon=icon, color=color)
    return {"path": node["path"], "id": node["id"]}


ACTIONS = {"mkdir": act_mkdir, "mv": act_mv, "rename": act_rename, "icon": act_icon, "rmdir": act_rmdir,
           "project": act_project}


# ------------------------------------------------------------------ entry point

def make_server(root: Path, port: int | None) -> ThreadingHTTPServer:
    handler = type("QapHandler", (Handler,), {"root": root})
    explicit = port is not None
    port = DEFAULT_PORT if port is None else port
    for candidate in [port] if explicit else range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            httpd.daemon_threads = True
            return httpd
        except OSError as e:
            if e.errno != errno.EADDRINUSE or explicit:
                raise OSError(f"cannot listen on 127.0.0.1:{candidate}: {e.strerror}"
                              + (" (pick another --port)" if e.errno == errno.EADDRINUSE else ""))
    raise OSError(f"ports {port}-{port + 19} are all taken; pick one with --port")


def serve(root: Path, port: int | None = None, open_browser: bool = False, as_json: bool = False) -> None:
    if not root.is_dir():
        raise L.LayoutError(f"content root {root} does not exist (`qap config content_root <path>`)")
    httpd = make_server(root, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    if as_json:
        print(json.dumps({"ok": True, "url": url, "root": str(root), "pid": __import__("os").getpid()}), flush=True)
    else:
        print(f"QA passes dashboard: {url}\n  content: {root}\n  Ctrl+C to stop", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.server_close()
