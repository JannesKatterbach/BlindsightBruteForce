"""Lokale Web Anwendung (nur Standardbibliothek).

Start. ``python -m blindsight`` (oder ``blindsight``) und im Browser http://127.0.0.1:8765 oeffnen.
Die Oberflaeche ist eine reine Darstellung. Alle Berechnungen laufen im Python Kern.

Aufbau
  App          fachliche Endpunkte, unabhaengig von HTTP (``dispatch`` liefert eine Response)
  ROUTES       Tabelle (Methode, Pfad, Handler). Ein neuer Endpunkt ist ein Eintrag plus Methode
  make_handler HTTP Anbindung mit Host und Origin Pruefung, Groessenlimit und Content Type Pruefung

Fehlerantworten haben immer die Form {"error": erste Meldung, "errors": [alle Meldungen]}.
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
from ..export import EXPORTERS, build_geometry, exporter_schema
from ..layout import Placement
from ..model import Model
from ..motor_import import ScaleRequired, SvgImportError, outline_from_svg
from ..scoring import evaluate
from ..service import JobManager, JobNotFound
from ..units import is_finite_number

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024
MAX_PLACEMENTS = 5000
DEFAULT_PORT = 8765
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
JSON_TYPE = "application/json; charset=utf-8"
# Feste MIME Typen fuer statische Dateien (mit nosniff darf der Browser nicht raten)
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": JSON_TYPE,
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
# Content Types, die ein Browser ohne Vorabfrage (CORS Preflight) seitenuebergreifend senden darf.
# POST mit diesen Typen wird abgewiesen, die UI sendet application/json.
SIMPLE_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain")

__all__ = ["App", "Response", "analyze", "make_handler", "serve", "main"]


# ---------------------------------------------------------------------------
# Antworten und Anfragen
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
    """JSON Antwort. NaN und Unendlich sind kein gueltiges JSON und werden als Fehler behandelt."""
    return Response(code, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode())


def error_response(code: int, errors: list[str] | str) -> Response:
    errors = [errors] if isinstance(errors, str) else list(errors)
    return json_response({"error": errors[0] if errors else "", "errors": errors}, code)


class BadRequest(ValueError):
    """Ungueltige Anfrage (400)."""


def _reject_constant(name: str) -> Any:
    raise BadRequest(f"{name} ist kein gueltiger Zahlenwert")


def parse_json(body: bytes) -> Any:
    """JSON aus dem Anfragekoerper. NaN, Infinity und zu tiefe Schachtelung fuehren zu BadRequest."""
    try:
        return json.loads(body or b"{}", parse_constant=_reject_constant)
    except RecursionError:
        raise BadRequest("JSON ist zu tief verschachtelt") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadRequest(f"Kein gueltiges JSON. {exc}") from None


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    body: bytes
    tail: str = ""  # Pfadrest nach einem Praefix (z.B. Job Id)

    @property
    def data(self) -> Any:
        return parse_json(self.body)

    def dict_data(self) -> dict:
        data = self.data
        if not isinstance(data, dict):
            raise BadRequest("Objekt erwartet")
        return data

    def int_query(self, name: str, default: int = 0) -> int:
        try:
            return int(self.query.get(name, [str(default)])[0])
        except ValueError:
            raise BadRequest(f"{name} muss eine ganze Zahl sein") from None


def _int(v: Any, name: str = "Wert") -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise BadRequest(f"{name}. Ganze Zahl erwartet")
    return v


def _examples_dir() -> Optional[Path]:
    for cand in (Path(__file__).resolve().parents[3] / "examples", Path.cwd() / "examples"):
        if cand.is_dir():
            return cand
    return None


def _host_name(host: str) -> str:
    """Hostname ohne Port und ohne eckige Klammern (IPv6), klein geschrieben."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # Name oder IPv4 mit Port
        return host.rsplit(":", 1)[0]
    return host  # ohne Port oder nackte IPv6 Adresse


def _url_host(host: str) -> str:
    """Host fuer eine URL (IPv6 in eckigen Klammern)."""
    return f"[{host}]" if ":" in host else host


# ---------------------------------------------------------------------------
# Anwendung
# ---------------------------------------------------------------------------
Handler = Callable[["App", Request], Response]
ROUTES: list[tuple[str, str, bool, str]] = []  # (Methode, Pfad oder Praefix, ist Praefix, Methodenname)


def route(method: str, path: str, prefix: bool = False):
    """Dekorator fuer App Methoden. Traegt den Endpunkt in ROUTES ein."""
    def decorate(fn):
        ROUTES.append((method, path, prefix, fn.__name__))
        return fn
    return decorate


class App:
    def __init__(self, allowed_hosts: set[str] | None = None) -> None:
        self.jobs = JobManager()
        # None = nur Loopback Namen. Eintraege ohne Port, IPv6 ohne Klammern
        self.allowed_hosts = {_host_name(h) for h in allowed_hosts} if allowed_hosts else None

    # -- Sicherheit ------------------------------------------------------------
    def host_ok(self, host: str | None, origin: str | None) -> bool:
        """Schutz gegen DNS Rebinding und fremde Webseiten, die lokale Dienste ansprechen.

        Host muss ein erlaubter Name sein. Ein Origin muss ebenfalls erlaubt sein. Origin "null"
        (Sandbox, file://) wird abgewiesen, weil sich dahinter jede Seite verbergen kann."""
        allowed = self.allowed_hosts or LOOPBACK_HOSTS
        if host is None or _host_name(host) not in allowed:
            return False
        if origin is not None:
            if origin.strip().lower() == "null":
                return False
            if (urlparse(origin).hostname or "") not in allowed:
                return False
        return True

    # -- Verteilung --------------------------------------------------------------
    def dispatch(self, method: str, path: str, query: dict, body: bytes) -> Response:
        """Sucht den Endpunkt in ROUTES und fuehrt ihn aus. Fehler werden zu 4xx oder 500."""
        try:
            for r_method, r_path, prefix, name in ROUTES:
                if r_method != method:
                    continue
                if prefix and path.startswith(r_path):
                    return getattr(self, name)(Request(method, path, query, body, path[len(r_path):]))
                if not prefix and path == r_path:
                    return getattr(self, name)(Request(method, path, query, body))
            return error_response(404, "nicht gefunden")
        except ConfigError as exc:
            return error_response(400, exc.errors)
        except SvgImportError as exc:
            return error_response(400, str(exc))
        except JobNotFound as exc:
            return error_response(404, str(exc))
        except BadRequest as exc:
            return error_response(400, f"Ungueltige Anfrage. {exc}")
        except ValueError as exc:  # Pruefungen im Kern (Placement, Skizze, Export) melden ValueError
            return error_response(400, f"Ungueltige Anfrage. {exc}")
        except Exception as exc:  # Programmfehler. Der Server bleibt erreichbar
            traceback.print_exc()
            return error_response(500, f"Interner Fehler. {type(exc).__name__}: {exc}")

    def handle(self, method: str, path: str, query: dict, body: bytes) -> tuple[int, str, bytes]:
        """Wie dispatch, als Tupel (Code, Content Type, Inhalt). Schnittstelle aus frueheren Versionen."""
        return self.dispatch(method, path, query, body).as_tuple()

    # -- Statische Dateien und Stammdaten -------------------------------------------
    @route("GET", "/")
    @route("GET", "/index.html")
    def index(self, req: Request) -> Response:
        return Response(200, (STATIC / "index.html").read_bytes(), STATIC_TYPES[".html"])

    @route("GET", "/static/", prefix=True)
    def static_file(self, req: Request) -> Response:
        f = (STATIC / req.tail).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return error_response(404, "nicht gefunden")
        return Response(200, f.read_bytes(), STATIC_TYPES.get(f.suffix.lower(), "application/octet-stream"))

    @route("GET", "/favicon.ico")
    def favicon(self, req: Request) -> Response:
        return Response(204, b"", STATIC_TYPES[".ico"])

    @route("GET", "/api/schema")
    def get_schema(self, req: Request) -> Response:
        out = schema()
        out["sketch_constraints"] = sk.constraint_schema()
        out["exporters"] = exporter_schema()
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
            return error_response(404, "Beispiel nicht gefunden")
        try:
            return json_response(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return error_response(500, f"Beispiel nicht lesbar. {exc}")

    # -- Laeufe ----------------------------------------------------------------------
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
            return error_response(409, "Noch kein Ergebnis")
        out = {"result": job.result.as_dict(), "geometry": None}
        out["result"]["solutions"] = [{"score": s.score.as_dict(), "count": len(s.placements)} for s in job.result.solutions]
        if job.result.solutions:
            idx = self._solution_index(req, len(job.result.solutions))
            out["geometry"] = build_geometry(job.model, job.result.solutions[idx].placements)
            out["solution_index"] = idx
        return json_response(out)

    @route("GET", "/api/export/", prefix=True)
    def export_result(self, req: Request) -> Response:
        job_id, _, ext = req.tail.partition(".")
        job = self.jobs.get(job_id)
        if job.result is None or not job.result.solutions or ext not in EXPORTERS:
            return error_response(404, "Export nicht moeglich")
        idx = self._solution_index(req, len(job.result.solutions))
        response = self._export(EXPORTERS[ext](), build_geometry(job.model, job.result.solutions[idx].placements))
        response.headers["Content-Disposition"] = f'attachment; filename="blindsight.{ext}"'
        return response

    @staticmethod
    def _solution_index(req: Request, count: int) -> int:
        return max(0, min(req.int_query("solution"), count - 1))

    @staticmethod
    def _export(exporter, geometry: dict) -> Response:
        return Response(200, exporter.export(geometry).encode(), exporter.mime + "; charset=utf-8")

    # -- Anordnungen ohne Lauf ---------------------------------------------------------
    def _layout_request(self, req: Request) -> tuple[dict, Project, Model, list[Placement]]:
        data = req.data
        if not isinstance(data, dict) or "project" not in data or not isinstance(data.get("placements"), list):
            raise BadRequest("Erwartet {project, placements}")
        if len(data["placements"]) > MAX_PLACEMENTS:
            raise BadRequest(f"Zu viele Platzierungen (max {MAX_PLACEMENTS})")
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

    @route("POST", "/api/export-layout")
    def export_layout(self, req: Request) -> Response:
        data, _, model, placements = self._layout_request(req)
        fmt = data.get("format", "svg")
        if fmt not in EXPORTERS:
            raise BadRequest(f"Unbekanntes Exportformat {fmt}")
        return self._export(EXPORTERS[fmt](), build_geometry(model, placements))

    @route("POST", "/api/analyze")
    def analyze_project(self, req: Request) -> Response:
        return json_response(analyze(Project.from_dict(req.data)))

    # -- Motor -------------------------------------------------------------------------
    @route("POST", "/api/svg-motor-import")
    def svg_motor_import(self, req: Request) -> Response:
        data = req.dict_data()
        try:
            outline = outline_from_svg(data.get("svg", ""), data.get("mm_per_unit"))
        except ScaleRequired as exc:
            return json_response({"scale_required": True, "message": str(exc)})
        out = {"width": outline.width, "depth": outline.depth, "outline": outline.outline,
               "convex": outline.was_convex, "notes": outline.notes}
        if isinstance(data.get("motor"), dict):  # Skizze im Stangenrahmen passend zum aktuellen Motor
            out["sketch"] = sk.sketch_from_outline(outline.outline, motor_from_dict(data["motor"]))
        return json_response(out)

    @route("POST", "/api/sketch/", prefix=True)
    def sketch_api(self, req: Request) -> Response:
        """Endpunkte der Motor Skizze. Solver Ergebnisse (auch Widersprueche) sind normale Antworten mit ok=false."""
        op = req.tail
        data = req.dict_data()
        gear = self._gear_arg(data.get("gear"))
        if op == "from-motor":
            motor = motor_from_dict(data.get("motor"))
            sketch = sk.legacy_to_sketch(motor, with_constraints=data.get("constraints", True))
            return json_response(sk.solve(sketch, cd=motor.center_distance, gear=(motor.gear_diameter, motor.gear_width)).as_dict())
        if op not in ("solve", "hull", "insert", "delete"):
            return error_response(404, "nicht gefunden")
        sketch = data.get("sketch")
        if not isinstance(sketch, dict):
            raise BadRequest("sketch (Objekt mit points und constraints) erforderlich")
        sketch = sk.sketch_dict(sketch)
        errors = sk.validate_structure(sketch)
        if errors:
            return json_response(self._invalid_sketch(sketch, errors))
        cd = data.get("cd", 5.0)
        try:
            if op == "solve":
                return json_response(sk.solve(sketch, cd=cd, drag=data.get("drag"), gear=gear).as_dict())
            if op == "hull":
                sketch = sk.hull_sketch(sketch)
            elif op == "insert":
                sketch = sk.insert_point(sketch, _int(data.get("side"), "side"), data.get("t", 0.5))
            else:
                sketch = sk.delete_point(sketch, _int(data.get("point"), "point"))
        except sk.SketchError as exc:
            return json_response(self._invalid_sketch(sketch, exc.errors))
        return json_response(sk.solve(sketch, cd=cd, gear=gear).as_dict())

    @staticmethod
    def _gear_arg(gear: Any) -> Optional[tuple[float, float]]:
        if gear is None:
            return None
        if not (isinstance(gear, list) and len(gear) == 2 and all(is_finite_number(v) for v in gear)):
            raise BadRequest("gear muss [Durchmesser, Breite] sein")
        return float(gear[0]), float(gear[1])

    @staticmethod
    def _invalid_sketch(sketch: dict, errors: list[str]) -> dict:
        return {"ok": False, "errors": errors, "sketch": sketch, "state": "invalid", "dof": 0, "constraints": [],
                "warnings": []}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def make_handler(app: App):
    class RequestHandler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            url = urlparse(self.path)
            if not app.host_ok(self.headers.get("Host"), self.headers.get("Origin")):
                self._send(error_response(403, "Host oder Origin nicht erlaubt"))
                return
            if method == "POST" and self._simple_content_type():
                self._send(error_response(415, "POST erwartet Content-Type application/json"))
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self._send(error_response(413 if length > 0 else 400, "Ungueltige oder zu grosse Anfrage"))
                return
            body = self.rfile.read(length) if length else b""
            self._send(app.dispatch(method, url.path, parse_qs(url.query), body))

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

        def log_message(self, fmt, *args):  # ruhige Konsole
            pass

    return RequestHandler


class _IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, open_browser: bool = True) -> ThreadingHTTPServer:
    """Erzeugt den Server (noch ohne serve_forever). Fremde Hosts muessen ausdruecklich angegeben werden."""
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
    ap = argparse.ArgumentParser(description="Project Blindsight Web Oberflaeche")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = serve(args.host, args.port, not args.no_browser)
    print(f"Project Blindsight laeuft auf http://{_url_host(args.host)}:{server.server_address[1]}  (Beenden mit Strg+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.app.jobs.shutdown()  # type: ignore[attr-defined]
        server.server_close()


if __name__ == "__main__":
    main()
