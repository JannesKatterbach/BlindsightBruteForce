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
from urllib.parse import urlparse, parse_qs

from ..config import ConfigError, Project
from ..export import EXPORTERS, build_geometry
from ..model import Model
from ..motor_import import ScaleRequired, SvgImportError, motor_outline_from_svg
from ..service import JobManager

STATIC = Path(__file__).parent / "static"


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


class App:
    def __init__(self) -> None:
        self.jobs = JobManager()

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
                if path == "/api/analyze":
                    return js(analyze(Project.from_dict(data)))
                if path.startswith("/api/cancel/"):
                    self.jobs.cancel(path.rsplit("/", 1)[1])
                    return js({"ok": True})
                if path == "/api/svg-motor-import":
                    try:
                        w, d = motor_outline_from_svg(data.get("svg", ""), data.get("mm_per_unit"))
                    except ScaleRequired as exc:
                        return js({"scale_required": True, "message": str(exc)})
                    return js({"width": w, "depth": d})
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
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            code, ctype, payload = app.handle(method, u.path, parse_qs(u.query), body)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            if u.path.startswith("/api/export/"):
                self.send_header("Content-Disposition", f'attachment; filename="blindsight.{u.path.rsplit(".", 1)[-1]}"')
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
    server = ThreadingHTTPServer((host, port), make_handler(App()))
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
        server.server_close()


if __name__ == "__main__":
    main()
