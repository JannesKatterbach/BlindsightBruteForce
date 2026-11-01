"""Local web application (standard library only).

Start. ``python -m blindsight`` (or ``blindsight``) and open http://127.0.0.1:8765 in the browser.
The UI only displays. All computations run in the Python core.

Structure
  App          endpoints, independent of HTTP (``dispatch`` returns a Response)
  ROUTES       table (method, path, handler). A new endpoint is an entry plus a method
  make_handler HTTP binding with host and origin check, size limit and content type check

Language. Every request is answered in the language from the header ``X-Language``, otherwise the query
parameter ``lang`` (for downloads via links), otherwise ``Accept-Language``, otherwise German. All
texts of a response (also results of earlier runs) are rendered in that language.

Error responses always have the form {"error": first message, "errors": [all messages]}.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import traceback
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from .. import sketch as sk
from ..analysis import analyze
from ..config import ConfigError, Project, motor_from_dict, schema
from .. import holes as hole_files
from ..export import EXPORTERS, build_geometry, exporter_schema
from ..i18n import LANGUAGE_NAMES, LANGUAGES, LocalText, current_language, localize, negotiate, normalize_language, tr, use_language
from ..layout import Placement
from ..model import Model
from ..motor_import import ScaleRequired, SvgImportError, outline_from_svg
from ..scoring import evaluate
from ..tiling import TilingError, tile_project
from ..service import JobManager, JobNotFound

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024
MAX_PLACEMENTS = 5000
DEFAULT_PORT = 8765
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
JSON_TYPE = "application/json; charset=utf-8"
# Fixed MIME types of static files (with nosniff the browser must not guess)
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": JSON_TYPE,
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
# Content types a browser may send cross site without a preflight request (CORS preflight).
# POST with these types is rejected, the UI sends application/json.
SIMPLE_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain")

__all__ = ["App", "Response", "analyze", "make_handler", "serve", "main"]


# ---------------------------------------------------------------------------
# Responses and requests
# ---------------------------------------------------------------------------
@dataclass
class Response:
    code: int
    body: bytes
    content_type: str = JSON_TYPE
    headers: dict[str, str] = field(default_factory=dict)

    def as_tuple(self) -> tuple[int, str, bytes]:
        return self.code, self.content_type, self.body


def json_response(obj: Any, code: int = 200) -> Response:
    """JSON response in the current language. NaN and infinity are not valid JSON and count as errors."""
    obj = localize(obj, current_language())
    return Response(code, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode())


def error_response(code: int, errors: list[str] | str) -> Response:
    errors = [errors] if isinstance(errors, str) else list(errors)
    return json_response({"error": errors[0] if errors else "", "errors": errors}, code)


class BadRequest(ValueError):
    """Invalid request (400)."""


def _reject_constant(name: str) -> Any:
    raise BadRequest(tr("server.invalid_number", name=name))


def parse_json(body: bytes) -> Any:
    """JSON from the request body. NaN, Infinity and too deep nesting raise BadRequest."""
    try:
        return json.loads(body or b"{}", parse_constant=_reject_constant)
    except RecursionError:
        raise BadRequest(tr("server.json_too_deep")) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadRequest(tr("server.invalid_json", error=str(exc))) from None


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    body: bytes
    tail: str = ""  # rest of the path after a prefix (e.g. job id)

    @property
    def data(self) -> Any:
        return parse_json(self.body)

    def dict_data(self) -> dict:
        data = self.data
        if not isinstance(data, dict):
            raise BadRequest(tr("server.object_expected"))
        return data

    def int_query(self, name: str, default: int = 0) -> int:
        try:
            return int(self.query.get(name, [str(default)])[0])
        except ValueError:
            raise BadRequest(tr("server.query_integer", name=name)) from None


def _examples_dir() -> Optional[Path]:
    for cand in (Path(__file__).resolve().parents[3] / "examples", Path.cwd() / "examples"):
        if cand.is_dir():
            return cand
    return None


def _host_name(host: str) -> str:
    """Host name without port and square brackets (IPv6), lower case."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # name or IPv4 with port
        return host.rsplit(":", 1)[0]
    return host  # without port or bare IPv6 address


def _url_host(host: str) -> str:
    """Host for a URL (IPv6 in square brackets)."""
    return f"[{host}]" if ":" in host else host


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
Handler = Callable[["App", Request], Response]
ROUTES: list[tuple[str, str, bool, str]] = []  # (method, path or prefix, is prefix, method name)


def request_language(headers: Optional[dict], query: dict) -> str:
    """Language of a request. X-Language, then ?lang=, then Accept-Language, then the default."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    explicit = headers.get("x-language") or (query.get("lang") or [None])[0]
    if explicit:
        return normalize_language(explicit)
    return negotiate(headers.get("accept-language"))


def _message(exc: Exception) -> Any:
    """Message of an exception, keeping a LocalText so it can be rendered in the request language."""
    if len(exc.args) == 1 and isinstance(exc.args[0], LocalText):
        return exc.args[0]
    return str(exc)


def route(method: str, path: str, prefix: bool = False):
    """Decorator for App methods. Registers the endpoint in ROUTES."""
    def decorate(fn):
        ROUTES.append((method, path, prefix, fn.__name__))
        return fn
    return decorate


class App:
    def __init__(self, allowed_hosts: set[str] | None = None) -> None:
        self.jobs = JobManager()
        # None = loopback names only. Entries without port, IPv6 without brackets
        self.allowed_hosts = {_host_name(h) for h in allowed_hosts} if allowed_hosts else None

    # -- Security ------------------------------------------------------------
    def host_ok(self, host: str | None, origin: str | None) -> bool:
        """Protection against DNS rebinding and foreign web pages that address local services.

        Host must be an allowed name. An origin must be allowed as well. Origin "null" (sandbox,
        file://) is rejected because any page can hide behind it."""
        allowed = self.allowed_hosts or LOOPBACK_HOSTS
        if host is None or _host_name(host) not in allowed:
            return False
        if origin is not None:
            if origin.strip().lower() == "null":
                return False
            if (urlparse(origin).hostname or "") not in allowed:
                return False
        return True

    # -- Dispatch --------------------------------------------------------------
    def dispatch(self, method: str, path: str, query: dict, body: bytes, headers: Optional[dict] = None) -> Response:
        """Find the endpoint in ROUTES and run it in the request language. Errors become 4xx or 500."""
        with use_language(request_language(headers, query)):
            return self._dispatch(method, path, query, body)

    def _dispatch(self, method: str, path: str, query: dict, body: bytes) -> Response:
        try:
            for r_method, r_path, prefix, name in ROUTES:
                if r_method != method:
                    continue
                if prefix and path.startswith(r_path):
                    return getattr(self, name)(Request(method, path, query, body, path[len(r_path):]))
                if not prefix and path == r_path:
                    return getattr(self, name)(Request(method, path, query, body))
            return error_response(404, tr("server.not_found"))
        except (ConfigError, hole_files.HolesError, TilingError) as exc:
            return error_response(400, exc.errors)
        except SvgImportError as exc:
            return error_response(400, _message(exc))
        except JobNotFound as exc:
            return error_response(404, exc.message)
        except ValueError as exc:  # checks in the core (placement, sketch, export) raise ValueError
            return error_response(400, tr("server.bad_request", error=_message(exc)))
        except Exception as exc:  # programming error. The server stays reachable
            traceback.print_exc()
            return error_response(500, tr("server.internal_error", error=f"{type(exc).__name__}: {exc}"))

    def handle(self, method: str, path: str, query: dict, body: bytes,
               headers: Optional[dict] = None) -> tuple[int, str, bytes]:
        """Like dispatch, as a tuple (code, content type, body)."""
        return self.dispatch(method, path, query, body, headers).as_tuple()

    # -- Static files and master data -------------------------------------------
    @route("GET", "/")
    @route("GET", "/index.html")
    def index(self, req: Request) -> Response:
        return Response(200, (STATIC / "index.html").read_bytes(), STATIC_TYPES[".html"])

    @route("GET", "/static/", prefix=True)
    def static_file(self, req: Request) -> Response:
        f = (STATIC / req.tail).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return error_response(404, tr("server.not_found"))
        return Response(200, f.read_bytes(), STATIC_TYPES.get(f.suffix.lower(), "application/octet-stream"))

    @route("GET", "/favicon.ico")
    def favicon(self, req: Request) -> Response:
        return Response(204, b"", STATIC_TYPES[".ico"])

    @route("GET", "/api/schema")
    def get_schema(self, req: Request) -> Response:
        out = schema()
        out["sketch_constraints"] = sk.constraint_schema()
        out["exporters"] = exporter_schema()
        out["languages"] = [{"code": code, "name": LANGUAGE_NAMES[code]} for code in LANGUAGES]
        out["language"] = current_language()
        return json_response(out)

    @route("GET", "/api/default")
    def default_project(self, req: Request) -> Response:
        return json_response(Project().to_dict())

    @route("GET", "/api/examples")
    def examples(self, req: Request) -> Response:
        d = _examples_dir()
        return json_response(sorted(p.stem for p in d.glob("*.json")) if d else [])

    @route("GET", "/api/example/", prefix=True)
    def example(self, req: Request) -> Response:
        d = _examples_dir()
        f = d / (Path(req.tail).name + ".json") if d else None
        if not f or not f.is_file():
            return error_response(404, tr("server.example_not_found"))
        try:
            return json_response(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return error_response(500, tr("server.example_unreadable", error=str(exc)))

    # -- Runs ----------------------------------------------------------------------
    @route("POST", "/api/start")
    def start(self, req: Request) -> Response:
        job = self.jobs.start(Project.from_dict(req.data))
        return json_response({"job_id": job.id})

    @route("GET", "/api/status/", prefix=True)
    def status(self, req: Request) -> Response:
        return json_response(self.jobs.get(req.tail).status_dict())

    @route("POST", "/api/cancel/", prefix=True)
    def cancel(self, req: Request) -> Response:
        self.jobs.cancel(req.tail)
        return json_response({"ok": True})

    @route("GET", "/api/live/", prefix=True)
    def live(self, req: Request) -> Response:
        job = self.jobs.get(req.tail)
        placements = [Placement(**p) for p in job.best_so_far()]
        return json_response({"geometry": build_geometry(job.model, placements) if placements else None})

    @route("GET", "/api/result/", prefix=True)
    def result(self, req: Request) -> Response:
        job = self.jobs.get(req.tail)
        if job.result is None:
            return error_response(409, tr("server.no_result"))
        out = {"result": job.result.as_dict(), "geometry": None}
        out["result"]["solutions"] = [
            {"score": s.score.as_dict(), "count": len(s.placements), **({"tile": s.tile} if s.tile else {})}
            for s in job.result.solutions
        ]
        if job.result.solutions:
            idx = self._solution_index(req, len(job.result.solutions))
            out["geometry"] = build_geometry(job.model, job.result.solutions[idx].placements)
            out["solution_index"] = idx
        return json_response(out)

    @route("GET", "/api/export/", prefix=True)
    def export_result(self, req: Request) -> Response:
        job_id, _, name = req.tail.partition(".")
        job = self.jobs.get(job_id)
        if job.result is None or not job.result.solutions or name not in EXPORTERS:
            return error_response(404, tr("server.export_impossible"))
        idx = self._solution_index(req, len(job.result.solutions))
        exporter = EXPORTERS[name]()
        response = self._export(exporter, build_geometry(job.model, job.result.solutions[idx].placements))
        response.headers["Content-Disposition"] = f'attachment; filename="{exporter.filename}"'
        return response

    @staticmethod
    def _solution_index(req: Request, count: int) -> int:
        return max(0, min(req.int_query("solution"), count - 1))

    @staticmethod
    def _export(exporter, geometry: dict) -> Response:
        return Response(200, exporter.export(geometry).encode(), exporter.mime + "; charset=utf-8")

    # -- Arrangements without a run ---------------------------------------------------------
    def _layout_request(self, req: Request) -> tuple[dict, Project, Model, list[Placement]]:
        data = req.data
        if not isinstance(data, dict) or "project" not in data or not isinstance(data.get("placements"), list):
            raise BadRequest(tr("server.layout_expected"))
        if len(data["placements"]) > MAX_PLACEMENTS:
            raise BadRequest(tr("server.too_many_placements", max=MAX_PLACEMENTS))
        project = Project.from_dict(data["project"])
        n = project.stack.n_motor_planes
        placements = [Placement.from_dict(p, n) for p in data["placements"]]
        return data, project, Model(project), placements

    @route("POST", "/api/validate")
    def validate(self, req: Request) -> Response:
        _, project, model, placements = self._layout_request(req)
        geometry = build_geometry(model, placements)
        score = evaluate(model, placements, project.search.weights, project.target_count).as_dict() if placements else None
        return json_response({"geometry": geometry, "valid": not geometry["collisions"], "score": score})

    @route("POST", "/api/tile")
    def tile(self, req: Request) -> Response:
        """Set a repeating block side by side ({project, tile, nx, ny} -> project with a fitted board,
        placements, geometry, valid, notes)."""
        data = req.dict_data()
        project, placements, notes = tile_project(Project.from_dict(data.get("project", {})), data.get("tile"),
                                                  data.get("nx"), data.get("ny"), MAX_PLACEMENTS)
        geometry = build_geometry(Model(project), placements)
        return json_response({"project": project.to_dict(), "placements": [p.as_dict() for p in placements],
                              "geometry": geometry, "valid": not geometry["collisions"], "notes": notes})

    @route("POST", "/api/export-layout")
    def export_layout(self, req: Request) -> Response:
        data, _, model, placements = self._layout_request(req)
        fmt = data.get("format", "svg")
        if fmt not in EXPORTERS:
            raise BadRequest(tr("server.unknown_format", format=fmt))
        return self._export(EXPORTERS[fmt](), build_geometry(model, placements))

    @route("POST", "/api/analyze")
    def analyze_project(self, req: Request) -> Response:
        return json_response(analyze(Project.from_dict(req.data)))

    # -- Hole patterns -------------------------------------------------------------------
    @route("POST", "/api/holes/parse")
    def holes_parse(self, req: Request) -> Response:
        """Read a hole pattern file (blindsight.holes or a rod positions export) and return it normalised."""
        return json_response(hole_files.parse(req.data).as_dict())

    @route("POST", "/api/holes/check")
    def holes_check(self, req: Request) -> Response:
        """Problems of single holes for the generator ({project, holes} -> {problems})."""
        data = req.dict_data()
        project = Project.from_dict(data.get("project", {}))
        doc = hole_files.parse({"holes": data.get("holes", [])}) if data.get("holes") else hole_files.HoleDocument()
        if len(doc.holes) > MAX_PLACEMENTS:
            raise BadRequest(tr("server.too_many_placements", max=MAX_PLACEMENTS))
        return json_response({"problems": hole_files.check(project, doc.holes)})

    # -- Motor -------------------------------------------------------------------------
    @route("POST", "/api/svg-motor-import")
    def svg_motor_import(self, req: Request) -> Response:
        data = req.dict_data()
        try:
            outline = outline_from_svg(data.get("svg", ""), data.get("mm_per_unit"))
        except ScaleRequired as exc:
            return json_response({"scale_required": True, "message": _message(exc)})
        out = {"width": outline.width, "depth": outline.depth, "outline": outline.outline,
               "convex": outline.was_convex, "notes": outline.notes}
        if isinstance(data.get("motor"), dict):  # sketch in the rod frame matching the current motor
            out["sketch"] = sk.sketch_from_outline(outline.outline, motor_from_dict(data["motor"]))
        return json_response(out)

    @route("POST", "/api/sketch/", prefix=True)
    def sketch_api(self, req: Request) -> Response:
        """Endpoints of the motor sketch. Solver results (also conflicts) are normal responses with ok=false.

        from-motor  {motor}                 sketch of the housing rectangle and the gear from the motor fields
        solve       {sketch, drag?, diagnose?}"""
        op = req.tail
        data = req.dict_data()
        if op == "from-motor":
            motor = motor_from_dict(data.get("motor"))
            return json_response(sk.solve(sk.sketch_from_motor(motor)).as_dict())
        if op != "solve":
            return error_response(404, tr("server.not_found"))
        sketch = data.get("sketch")
        if not isinstance(sketch, dict):
            raise BadRequest(tr("server.sketch_required"))
        diagnose = data.get("diagnose", True)
        return json_response(sk.solve(sketch, drag=data.get("drag"), diagnose=diagnose is not False).as_dict())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def make_handler(app: App):
    class RequestHandler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            headers = dict(self.headers.items())
            with use_language(request_language(headers, query)):
                problem = self._precheck(method)
            if problem is not None:
                self._send(problem)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._send(app.dispatch(method, url.path, query, body, headers))

        def _precheck(self, method: str) -> Optional[Response]:
            """Host, content type and size checks before the body is read. None if all is fine."""
            if not app.host_ok(self.headers.get("Host"), self.headers.get("Origin")):
                return error_response(403, tr("server.host_forbidden"))
            if method == "POST" and self._simple_content_type():
                return error_response(415, tr("server.json_content_type"))
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return error_response(413 if length > 0 else 400, tr("server.body_size"))
            return None

        def _simple_content_type(self) -> bool:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            return ctype in SIMPLE_CONTENT_TYPES

        def _send(self, response: Response) -> None:
            self.send_response(response.code)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

        def do_GET(self):  # noqa: N802
            self._serve("GET")

        def do_POST(self):  # noqa: N802
            self._serve("POST")

        def log_message(self, fmt, *args):  # quiet console
            pass

    return RequestHandler


class _IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, open_browser: bool = True) -> ThreadingHTTPServer:
    """Create the server (without serve_forever yet). Foreign hosts must be given explicitly."""
    app = App(None if host.lower() in LOOPBACK_HOSTS else {host, "127.0.0.1", "localhost"})
    server_class = _IPv6Server if ":" in host else ThreadingHTTPServer
    server = server_class((host, port), make_handler(app))
    server.app = app  # type: ignore[attr-defined]
    server.daemon_threads = True
    if open_browser:
        url = f"http://{_url_host(host)}:{server.server_address[1]}"
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=str(tr("server.description")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = serve(args.host, args.port, not args.no_browser)
    print(tr("server.running", url=f"http://{_url_host(args.host)}:{server.server_address[1]}"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + tr("server.stopped"))
    finally:
        server.app.jobs.shutdown()  # type: ignore[attr-defined]
        server.server_close()


if __name__ == "__main__":
    main()
