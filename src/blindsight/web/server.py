"""Lokale Web Anwendung (nur Standardbibliothek).

Start. python -m blindsight   (oder blindsight)  und im Browser http://127.0.0.1:8765 oeffnen.
Die Oberflaeche ist eine reine Darstellung. Alle Berechnungen laufen im Python Kern.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from ..config import ConfigError, Project, motor_from_dict, schema
from ..export import EXPORTERS, build_geometry
from ..layout import Placement
from ..model import Model
from .. import sketch as sk
from ..motor_import import ScaleRequired, SvgImportError, outline_from_svg
from ..service import JobManager

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024


def _examples_dir() -> Path | None:
    for cand in (Path(__file__).resolve().parents[3] / "examples", Path.cwd() / "examples"):
        if cand.is_dir():
            return cand
    return None


def analyze(project: Project) -> dict:
    """Abgeleitete Groessen ohne Optimierung (Ebenen, Stangenlaengen, Probleme)."""
    model = Model(project)
    planes = []
    for p in model.stack.planes:
        entry = {"index": p.index, "name": p.name, "z_top": p.z_top, "z_bottom": p.z_bottom, "thickness": p.thickness}
        if p.index > 0:
            entry["rod"] = model.rod_geometry(p.index).as_dict()
            entry["problems"] = model.plane_problems(p.index)
            entry["free_above"] = model.stack.free_height_above(p.index)
        planes.append(entry)
    return {"planes": planes, "unit_radius": model.unit_radius, "required_gap": model.gap}


def _int(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("Ganze Zahl erwartet")
    return v


class App:
    def __init__(self, allowed_hosts: set[str] | None = None) -> None:
        self.jobs = JobManager()
        self.allowed_hosts = allowed_hosts  # None = nur Loopback Namen

    def host_ok(self, host: str | None, origin: str | None) -> bool:
        """Schutz gegen DNS Rebinding und fremde Webseiten, die lokale Dienste ansprechen."""
        def name(h: str) -> str:
            h = h.strip().lower()
            if h.startswith("["):
                return h.split("]")[0] + "]"
            return h.rsplit(":", 1)[0] if ":" in h else h

        ok = self.allowed_hosts or {"127.0.0.1", "localhost", "[::1]"}
        if host is None or name(host) not in ok:
            return False
        if origin and origin != "null":
            from urllib.parse import urlparse as _u

            if (_u(origin).hostname or "") not in {x.strip("[]") for x in ok}:
                return False
        return True

    def _sketch_api(self, op: str, data: Any) -> tuple[int, str, bytes]:
        """Endpunkte der Motor Skizze. Solver Ergebnisse (auch Widersprueche) sind normale Antworten mit ok=false."""
        def js(obj, code=200):
            return code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode()

        if not isinstance(data, dict):
            raise ValueError("Objekt erwartet")
        cd = data.get("cd", 5.0)
        gear = data.get("gear")
        if gear is not None:
            if not (isinstance(gear, list) and len(gear) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in gear)):
                raise ValueError("gear muss [Durchmesser, Breite] sein")
            gear = (float(gear[0]), float(gear[1]))
        if op == "from-motor":
            motor = motor_from_dict(data.get("motor"))
            skd = sk.legacy_to_sketch(motor, with_constraints=data.get("constraints", True))
            return js(sk.solve(skd, cd=motor.center_distance, gear=(motor.gear_diameter, motor.gear_width)).as_dict())
        skd = data.get("sketch")
        if not isinstance(skd, dict):
            raise ValueError("sketch (Objekt mit points und constraints) erforderlich")
        skd = sk.sketch_dict(skd)
        errs = sk.validate_structure(skd)
        if errs:
            return js({"ok": False, "errors": errs, "sketch": skd, "state": "invalid", "dof": 0, "constraints": [], "warnings": []})
        try:
            if op == "solve":
                return js(sk.solve(skd, cd=cd, drag=data.get("drag"), gear=gear).as_dict())
            if op == "hull":
                skd = sk.hull_sketch(skd)
            elif op == "insert":
                skd = sk.insert_point(skd, _int(data.get("side")), float(data.get("t", 0.5)))
            elif op == "delete":
                skd = sk.delete_point(skd, _int(data.get("point")))
            else:
                return js({"error": "nicht gefunden"}, 404)
        except sk.SketchError as exc:
            return js({"ok": False, "errors": exc.errors, "sketch": skd, "state": "invalid", "dof": 0, "constraints": [], "warnings": []})
        return js(sk.solve(skd, cd=cd, gear=gear).as_dict())

    def handle(self, method: str, path: str, query: dict, body: bytes) -> tuple[int, str, bytes]:
        def js(obj, code=200):
            return code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode()

        try:
            if method == "GET":
                if path in ("/", "/index.html"):
                    return 200, "text/html; charset=utf-8", (STATIC / "index.html").read_bytes()
                if path.startswith("/static/"):
                    f = (STATIC / path[len("/static/"):]).resolve()
                    if STATIC.resolve() not in f.parents or not f.is_file():
                        return js({"error": "nicht gefunden"}, 404)
                    return 200, mimetypes.guess_type(f.name)[0] or "application/octet-stream", f.read_bytes()
                if path == "/favicon.ico":
                    return 204, "image/x-icon", b""
                if path == "/api/schema":
                    return js(schema())
                if path == "/api/default":
                    return js(Project().to_dict())
                if path == "/api/examples":
                    d = _examples_dir()
                    return js(sorted(p.stem for p in d.glob("*.json")) if d else [])
                if path.startswith("/api/example/"):
                    d = _examples_dir()
                    f = d / (Path(path).name + ".json") if d else None
                    if not f or not f.is_file():
                        return js({"error": "Beispiel nicht gefunden"}, 404)
                    return js(json.loads(f.read_text(encoding="utf-8")))
                if path.startswith("/api/status/"):
                    return js(self.jobs.get(path.rsplit("/", 1)[1]).status_dict())
                if path.startswith("/api/live/"):
                    job = self.jobs.get(path.rsplit("/", 1)[1])
                    pls = [Placement(**p) for p in job.best_so_far()]
                    return js({"geometry": build_geometry(job.model, pls) if pls else None})
                if path.startswith("/api/result/"):
                    job = self.jobs.get(path.rsplit("/", 1)[1])
                    if job.result is None:
                        return js({"error": "Noch kein Ergebnis"}, 409)
                    idx = int(query.get("solution", ["0"])[0])
                    out = {"result": job.result.as_dict(), "geometry": None}
                    out["result"]["solutions"] = [
                        {"score": s.score.as_dict(), "count": len(s.placements)} for s in job.result.solutions
                    ]
                    if job.result.solutions:
                        idx = max(0, min(idx, len(job.result.solutions) - 1))
                        out["geometry"] = build_geometry(job.model, job.result.solutions[idx].placements)
                        out["solution_index"] = idx
                    return js(out)
                if path.startswith("/api/export/"):
                    name = path.rsplit("/", 1)[1]
                    job_id, _, ext = name.partition(".")
                    job = self.jobs.get(job_id)
                    if job.result is None or not job.result.solutions or ext not in EXPORTERS:
                        return js({"error": "Export nicht moeglich"}, 404)
                    idx = int(query.get("solution", ["0"])[0])
                    idx = max(0, min(idx, len(job.result.solutions) - 1))
                    geo = build_geometry(job.model, job.result.solutions[idx].placements)
                    ex = EXPORTERS[ext]()
                    return 200, ex.mime + "; charset=utf-8", ex.export(geo).encode()
            elif method == "POST":
                data = json.loads(body or b"{}")
                if path == "/api/start":
                    project = Project.from_dict(data)
                    job = self.jobs.start(project)
                    return js({"job_id": job.id})
                if path in ("/api/validate", "/api/export-layout"):
                    if not isinstance(data, dict) or "project" not in data or not isinstance(data.get("placements"), list):
                        raise ValueError("Erwartet {project, placements}")
                    project = Project.from_dict(data["project"])
                    n = project.stack.n_motor_planes
                    pls = [Placement.from_dict(p, n) for p in data["placements"]]
                    if len(pls) > 5000:
                        raise ValueError("Zu viele Platzierungen (max 5000)")
                    model = Model(project)
                    geo = build_geometry(model, pls)
                    if path == "/api/validate":
                        from ..scoring import evaluate

                        sc = evaluate(model, pls, project.search.weights, project.target_count).as_dict() if pls else None
                        return js({"geometry": geo, "valid": not geo["collisions"], "score": sc})
                    fmt = data.get("format", "svg")
                    if fmt not in EXPORTERS:
                        raise ValueError(f"Unbekanntes Exportformat {fmt}")
                    ex = EXPORTERS[fmt]()
                    return 200, ex.mime + "; charset=utf-8", ex.export(geo).encode()
                if path == "/api/analyze":
                    return js(analyze(Project.from_dict(data)))
                if path.startswith("/api/cancel/"):
                    self.jobs.cancel(path.rsplit("/", 1)[1])
                    return js({"ok": True})
                if path.startswith("/api/sketch/"):
                    return self._sketch_api(path.rsplit("/", 1)[1], data)
                if path == "/api/svg-motor-import":
                    try:
                        o = outline_from_svg(data.get("svg", ""), data.get("mm_per_unit"))
                    except ScaleRequired as exc:
                        return js({"scale_required": True, "message": str(exc)})
                    out = {"width": o.width, "depth": o.depth, "outline": o.outline, "convex": o.was_convex, "notes": o.notes}
                    if isinstance(data.get("motor"), dict):  # Skizze im Stangenrahmen passend zum aktuellen Motor
                        motor = motor_from_dict(data["motor"])
                        out["sketch"] = sk.sketch_from_outline(o.outline, motor)
                    return js(out)
        except ConfigError as exc:
            return js({"errors": exc.errors}, 400)
        except SvgImportError as exc:
            return js({"errors": [str(exc)]}, 400)
        except KeyError as exc:
            return js({"error": str(exc)}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            return js({"errors": [f"Ungueltige Anfrage. {exc}"]}, 400)
        return js({"error": "nicht gefunden"}, 404)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            u = urlparse(self.path)
            if not app.host_ok(self.headers.get("Host"), self.headers.get("Origin")):
                self._send(403, "application/json", b'{"error": "Host oder Origin nicht erlaubt"}', u.path)
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._send(413 if n > 0 else 400, "application/json", b'{"error": "Ungueltige oder zu grosse Anfrage"}', u.path)
                return
            body = self.rfile.read(n) if n else b""
            code, ctype, payload = app.handle(method, u.path, parse_qs(u.query), body)
            self._send(code, ctype, payload, u.path)

        def _send(self, code: int, ctype: str, payload: bytes, path: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if path.startswith("/api/export/"):
                self.send_header("Content-Disposition", f'attachment; filename="blindsight.{path.rsplit(".", 1)[-1]}"')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            self._serve("GET")

        def do_POST(self):  # noqa: N802
            self._serve("POST")

        def log_message(self, fmt, *args):  # ruhige Konsole
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    app = App(None if host in ("127.0.0.1", "localhost", "::1") else {host.lower(), "127.0.0.1", "localhost"})
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.app = app  # type: ignore[attr-defined]
    server.daemon_threads = True
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://{host}:{server.server_address[1]}")).start()
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Project Blindsight Web Oberflaeche")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = serve(args.host, args.port, not args.no_browser)
    print(f"Project Blindsight laeuft auf http://{args.host}:{server.server_address[1]}  (Beenden mit Strg+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        for job in list(server.app.jobs.jobs.values()):  # type: ignore[attr-defined]
            if job.stop:
                job.stop.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
