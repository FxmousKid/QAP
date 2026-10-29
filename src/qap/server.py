"""qap serve: the dashboard and the content from ONE origin, bound to 127.0.0.1 only.

FastAPI serves it (uvicorn listens). One origin matters: the pages keep their stars in localStorage under
qa-stars:<qa-project>, and browsers keep localStorage per origin. Served from here, every pass of a subject
(and the dashboard's frame) shares them.

  GET  /                  the dashboard (web/index.html)
  GET  /ui/<file>         the dashboard's modules, stylesheet, icons.json
  GET  /c/<path>          a file of the content root (pages, images); symlinks inside the root are followed
  GET  /api/tree          the tree: projects, folders, subjects, passes (qap.snapshot.tree)
  GET  /api/search        the search index: every project, folder, subject and pass (qap.snapshot.search_index)
  GET  /docs              the same API, as OpenAPI
  POST /api/mkdir         {parent, title, icon?, color?, name?}  -> layout.make_folder (parent "@id": a top-level
                                                                    folder in that project)
  POST /api/mv            {src, dest}                            -> layout.move (dest "@id": assign_project)
  POST /api/rename        {path, title}                          -> layout.set_meta (path "@id": a project)
  POST /api/icon          {path, icon?, color?}                  -> layout.set_meta
  POST /api/rmdir         {path}                                 -> layout.remove_folder (empty folders only;
                                                                    "@id": remove_project, empty projects only)
  POST /api/project       {title, icon?, color?, id?}            -> layout.make_project

  Plugins (qap.plugins):
  GET  /api/plugins                       every plugin, on or off, with its settings and commands
  POST /api/plugins/<id>/enable|disable   turn it on or off (saved, and loaded or unloaded right away)
  POST /api/plugins/<id>/settings         {key: value, ...}
  POST /api/plugins/<id>/run/<command>    run a plugin command with {arg: value}
  GET|POST /api/plugins/<id>/<route>      a route the plugin registered
  GET  /plugins/<id>/web/<file>           the plugin's dashboard part (its web/ folder only)

Writes are refused unless the request comes from this origin (Host and Origin checked, JSON body), so a web
page elsewhere cannot drive them; the Host check also stops DNS-rebinding reads.

The tree and the search index are reused until a pass file or a manifest changes. Pass titles stay on the
tree: the viewer uses them.
"""
from __future__ import annotations

import errno
import json
import mimetypes
import os
import posixpath
import socket
import stat
import sys
import threading
import webbrowser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse, Response

from . import icons, layout as L, plugins as PL, snapshot

WEB = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8750
_MAX_BODY = 64 * 1024
_SECURITY = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".md": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".py": "text/plain; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8"}


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _json(code: int, data: dict) -> JSONResponse:
    return JSONResponse(data, status_code=code, headers=_SECURITY)


def _log_message(fmt: str, *args: object) -> None:
    """Quiet access log: 4xx and 5xx only. Tests replace this on RequestHandlerClass."""
    if len(args) > 1 and str(args[1])[:1] in "45":
        sys.stderr.write(f"qap serve: {args[0]} -> {args[1]}\n")


def _bound_port(request: Request) -> int:
    server = request.scope.get("server")
    if server and server[1]:
        return int(server[1])
    return request.app.state.port


async def _json_body(request: Request) -> dict:
    """A POST body. Empty is {}. Anything that is not a JSON object is a 400 the dashboard can show."""
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="body too large")
    try:
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad JSON: {e}") from e
    return data


JsonBody = Annotated[dict, Depends(_json_body)]


def _under(base: Path, rel: str) -> Path | None:
    """base/rel for a URL path, refusing '..' escapes and hidden segments (symlinks are followed)."""
    norm = posixpath.normpath("/" + rel).lstrip("/")
    if not norm or any(seg.startswith(".") for seg in norm.split("/")):
        return None
    return base / norm


def _file(path: Path, request: Request) -> Response:
    try:
        st = path.stat()
    except OSError:
        return _json(404, {"ok": False, "error": "not found"})
    if not stat.S_ISREG(st.st_mode):
        return _json(404, {"ok": False, "error": "not found"})
    since = request.headers.get("if-modified-since")
    if since:
        try:
            if int(st.st_mtime) <= parsedate_to_datetime(since).timestamp():
                return Response(status_code=304, headers=dict(_SECURITY))
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return FileResponse(path, media_type=content_type(path), stat_result=st, headers=dict(_SECURITY))


def _query(request: Request) -> dict:
    found: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        found[key] = value  # a repeated key: the plugin sees the last one
    return found


# ------------------------------------------------------------------ the app

def build_api(root: Path, plugins: PL.App) -> FastAPI:
    api = FastAPI(
        title="qap",
        description="Local dashboard for QA passes, bound to 127.0.0.1.",
        redirect_slashes=False,
        telemetry={"tracing": False, "metrics": False, "logs": False},
    )
    api.state.root = root
    api.state.plugins = plugins
    api.state.lock = threading.Lock()
    api.state.port = 0

    @api.middleware("http")
    async def guard(request: Request, call_next):
        refused = _refused(request)
        response = refused if refused is not None else await call_next(request)
        for key, value in _SECURITY.items():
            response.headers[key] = value
        status = str(response.status_code)
        if status[:1] in "45":
            request.app.state.server.RequestHandlerClass.log_message(
                '"%s" %s %s', f"{request.method} {request.scope['path']}", status, "-")
        return response

    def _refused(request: Request) -> JSONResponse | None:
        port = _bound_port(request)
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = request.headers.get("host", "")
        if request.method == "POST":
            origin = request.headers.get("origin")
            if host not in hosts or (origin is not None and origin not in {f"http://{h}" for h in hosts}):
                return _json(403, {"ok": False, "error": "writes are only accepted from the dashboard's origin"})
            if not request.headers.get("content-type", "").startswith("application/json"):
                return _json(415, {"ok": False, "error": "send JSON"})
            length = int(request.headers.get("content-length") or 0)
            if length > _MAX_BODY:
                return _json(413, {"ok": False, "error": "body too large"})
            return None
        if host not in hosts:
            return _json(421, {"ok": False, "error": "use http://127.0.0.1 or http://localhost"})
        return None

    async def on_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _json(404, {"ok": False, "error": "not found"})
        error = exc.detail if isinstance(exc.detail, str) else "bad request"
        return _json(exc.status_code, {"ok": False, "error": error})

    async def on_bad_json(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _json(400, {"ok": False, "error": f"bad JSON: {exc.errors()[0]['msg']}"})

    api.add_exception_handler(HTTPException, on_http_error)
    api.add_exception_handler(RequestValidationError, on_bad_json)

    # A pass page probes /ui/search.js with HEAD. FastAPI does not answer HEAD for a GET route, so each
    # read is registered twice. The HEAD copy stays out of /docs (one operation id per path).
    def read(path: str, *, include_in_schema: bool = True):
        def decorate(fn):
            api.add_api_route(path, fn, methods=["GET"], include_in_schema=include_in_schema)
            api.add_api_route(path, fn, methods=["HEAD"], include_in_schema=False)
            return fn
        return decorate

    @read("/", include_in_schema=False)
    @read("/index.html", include_in_schema=False)
    def index_page(request: Request) -> Response:
        return _file(WEB / "index.html", request)

    @read("/favicon.ico", include_in_schema=False)
    def favicon(request: Request) -> Response:
        return _file(WEB / "favicon.svg", request)

    @read("/ui/{rel:path}", include_in_schema=False)
    def ui_file(rel: str, request: Request) -> Response:
        target = _under(WEB, rel)
        if target is None:
            return _json(404, {"ok": False, "error": "not found"})
        return _file(target, request)

    @read("/c/{rel:path}", include_in_schema=False)
    def content_file(rel: str, request: Request) -> Response:
        target = _under(request.app.state.root, rel)
        if target is None or not target.is_file():
            return _json(404, {"ok": False, "error": f"no such file: {request.scope['path'][3:]}"})
        return _file(target, request)

    @read("/plugins/{pid}/{rel:path}", include_in_schema=False)
    def plugin_file(pid: str, rel: str, request: Request) -> Response:
        plugin = request.app.state.plugins.plugins.get(pid)
        web = plugin.folder / "web" if plugin else None
        target = _under(web, rel[len("web/"):]) if web is not None and rel.startswith("web/") else None
        if target is None or not target.is_file():
            return _json(404, {"ok": False, "error": "not found"})
        return _file(target, request)

    @read("/api/tree")
    def api_tree(request: Request) -> JSONResponse:
        root = request.app.state.root
        try:
            tree = snapshot.tree(root)
        except L.LayoutError as e:
            return _json(500, {"ok": False, "error": str(e)})
        return _json(200, {"ok": True, "root": str(root), "tree": tree, "icons": sorted(icons.builtin())})

    @read("/api/search")
    def api_search(request: Request) -> JSONResponse:
        try:
            return _json(200, snapshot.search_index(request.app.state.root))
        except L.LayoutError as e:
            return _json(500, {"ok": False, "error": str(e)})

    @read("/api/plugins")
    def api_plugins(request: Request) -> JSONResponse:
        app = request.app.state.plugins
        return _json(200, {"ok": True, "app_version": app.version, "plugins": app.describe()})

    # Plugin routes are registered before POST /api/{action}, or that route would swallow them.
    @read("/api/plugins/{pid}/{rest:path}")
    def plugin_get(pid: str, rest: str, request: Request) -> JSONResponse:
        return _plugin_call(request, "GET", pid, rest, _query(request))

    @api.post("/api/plugins/{pid}/{rest:path}")
    def plugin_post(pid: str, rest: str, request: Request, body: JsonBody) -> JSONResponse:
        return _plugin_call(request, "POST", pid, rest, body)

    @api.post("/api/{action:path}")
    def post_action(action: str, request: Request, body: JsonBody) -> JSONResponse:
        handler = ACTIONS.get(action)
        if handler is None:
            return _json(404, {"ok": False, "error": f"no action {action!r}"})
        try:
            with request.app.state.lock:
                result = handler(request.app.state.root, body)
        except (L.LayoutError, ValueError, OSError) as e:
            return _json(400, {"ok": False, "error": str(e)})
        request.app.state.plugins.emit("content_changed", {"action": action, "source": "dashboard", "request": body})
        return _json(200, {"ok": True, **result})

    return api


def _plugin_call(request: Request, method: str, pid: str, rest: str, body: dict) -> JSONResponse:
    app = request.app.state.plugins
    try:
        if method == "POST" and rest in ("enable", "disable"):
            found = app.found().get(pid)
            if rest == "enable" and found and not found.core and not app.is_enabled(pid, found):
                # a page served from /c/ shares this origin: it must not be able to switch on code
                return _json(403, {"ok": False, "error": f"turn a community plugin on from a terminal: "
                                                         f"qap plugins enable {pid}"})
            app.enable(pid) if rest == "enable" else app.disable(pid)
            return _json(200, {"ok": True, "plugins": app.describe()})
        if method == "POST" and rest == "settings":
            plugin = app.get(pid)
            saved = {key: plugin.set_setting(key, value) for key, value in body.items()}
            return _json(200, {"ok": True, "saved": saved})
        if method == "POST" and rest.startswith("run/"):
            cmd = app._commands.get(f"{pid}:{rest[4:]}")
            if not cmd:
                return _json(404, {"ok": False, "error": f"no command {pid}:{rest[4:]}"})
            known = cmd.defaults()
            result = app.run_command(cmd.full_id, {k: v for k, v in body.items() if k in known}, source="dashboard")
        else:
            handler = app.route(pid, method, rest)
            if not handler:
                return _json(404, {"ok": False, "error": f"no route {method} {request.scope['path']}"})
            result = {"ok": True, **(handler(body) or {})}
    except PL.PluginError as e:
        return _json(400, {"ok": False, "error": str(e)})
    except Exception as e:  # a plugin bug is a 500 for that call, never a dead server
        app.log(f"plugin {pid}: {method} {rest} failed: {type(e).__name__}: {e}")
        return _json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    if not result.get("ok", True):
        result.setdefault("error", result.get("text") or "failed")
    return _json(200, result)


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

class QapServer:
    """The socket is bound here, so server_address is known before serve_forever. Tests drive this object."""

    def __init__(self, api: FastAPI, sock: socket.socket):
        self._sock = sock
        self.server_address = sock.getsockname()
        self.RequestHandlerClass = type("RequestHandler", (), {"log_message": staticmethod(_log_message)})
        api.state.server = self
        api.state.port = self.server_address[1]
        config = uvicorn.Config(api, host="127.0.0.1", port=self.server_address[1], lifespan="off",
                                log_config=None, access_log=False, log_level="warning")
        self._uvicorn = uvicorn.Server(config)
        self._done = threading.Event()

    def serve_forever(self) -> None:
        try:
            self._uvicorn.run(sockets=[self._sock])
        finally:
            self._done.set()

    def shutdown(self) -> None:
        self._uvicorn.should_exit = True
        self._done.wait(timeout=5)

    def server_close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def _listen(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


def make_server(root: Path, port: int | None, app: PL.App | None = None) -> QapServer:
    app = app or PL.App(root, mode="serve")  # no plugin loaded unless the caller loaded them
    app.set_root(root)
    api = build_api(root, app)
    explicit = port is not None
    port = DEFAULT_PORT if port is None else port
    for candidate in [port] if explicit else range(port, port + 20):
        try:
            return QapServer(api, _listen(candidate))
        except OSError as e:
            if e.errno != errno.EADDRINUSE or explicit:
                raise OSError(f"cannot listen on 127.0.0.1:{candidate}: {e.strerror}"
                              + (" (pick another --port)" if e.errno == errno.EADDRINUSE else "")) from e
    raise OSError(f"ports {port}-{port + 19} are all taken; pick one with --port")


def serve(root: Path, port: int | None = None, open_browser: bool = False, as_json: bool = False,
          app: PL.App | None = None) -> None:
    if not root.is_dir():
        raise L.LayoutError(f"content root {root} does not exist (`qap config content_root <path>`)")
    if app is None:
        app = PL.App(root, mode="serve")
        app.load_enabled()
    httpd = make_server(root, port, app)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    if as_json:
        print(json.dumps({"ok": True, "url": url, "root": str(root), "pid": os.getpid()}), flush=True)
    else:
        print(f"QA passes dashboard: {url}\n  content: {root}\n  Ctrl+C to stop", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    # "startup" runs beside the server (a git pull must not hold the dashboard back)
    threading.Thread(target=app.emit, args=("startup", {"url": url}), name="qap-startup", daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.server_close()
        app.emit("shutdown", {})
        app.unload_all()
