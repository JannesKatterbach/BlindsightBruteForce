"""API and server. Error cases, security, parallel runs, cancellation."""

import json
import threading
import time
import urllib.request

import pytest
from blindsight.web.server import App, serve


def call(app, method, path, obj=None, raw=None):
    body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
    code, ctype, payload = app.handle(method, path, {}, body)
    return code, payload


def default_cfg(app):
    return json.loads(call(app, "GET", "/api/default")[1])


def wait(app, job, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        st = json.loads(call(app, "GET", f"/api/status/{job}")[1])
        if st["state"] not in ("queued", "running"):
            return st
        time.sleep(0.1)
    raise AssertionError("Zeitueberschreitung")


def test_schema_lists_all_fields():
    app = App()
    sch = json.loads(call(app, "GET", "/api/schema")[1])
    paths = {f["path"] for f in sch["fields"]}
    assert {"rod.diameter", "motor.width", "stack.n_motor_planes", "search.weights.count", "search.optimizer"} <= paths


def test_unknown_routes_and_jobs():
    app = App()
    assert call(app, "GET", "/api/nope")[0] == 404
    assert call(app, "GET", "/api/status/zzz")[0] == 404
    assert call(app, "POST", "/api/cancel/zzz", {})[0] == 404
    assert call(app, "GET", "/static/../server.py")[0] == 404
    assert call(app, "GET", "/api/example/../../etc/passwd")[0] == 404


def test_bad_bodies():
    app = App()
    for raw in (b"{", b"[]", b"null", b'"x"', b"\xff\xfe"):
        code, payload = call(app, "POST", "/api/start", raw=raw)
        assert code == 400, raw
        assert "errors" in json.loads(payload)


def test_validate_reports_collisions_and_rejects_bad_placements():
    app = App()
    cfg = default_cfg(app)
    good = [{"x": 30, "y": 60, "plane": 1, "angle": 0}, {"x": 90, "y": 60, "plane": 2, "angle": 0}]
    code, payload = call(app, "POST", "/api/validate", {"project": cfg, "placements": good})
    assert code == 200 and json.loads(payload)["valid"] is True
    bad = [{"x": 50, "y": 60, "plane": 1, "angle": 0}, {"x": 53, "y": 60, "plane": 1, "angle": 0}]
    r = json.loads(call(app, "POST", "/api/validate", {"project": cfg, "placements": bad})[1])
    assert r["valid"] is False and r["geometry"]["collisions"]
    for pl in ({"x": "a", "y": 1, "plane": 1, "angle": 0}, {"x": 1, "y": 1, "plane": 99, "angle": 0}, {"x": float("nan"), "y": 1, "plane": 1, "angle": 0}, {"x": 1, "y": 1, "plane": True, "angle": 0}, 5, {"x": 1, "y": 1, "plane": 1, "angle": 0, "zzz": 1}):
        code, payload = call(app, "POST", "/api/validate", {"project": cfg, "placements": [pl]})
        assert code == 400, pl


def test_export_layout_formats():
    app = App()
    cfg = default_cfg(app)
    pls = [{"x": 60, "y": 60, "plane": 1, "angle": 0}]
    for fmt, marker in (("svg", b"<svg"), ("dxf", b"EOF"), ("csv", b"plane,unit"), ("json", b"units")):
        code, payload = call(app, "POST", "/api/export-layout", {"project": cfg, "placements": pls, "format": fmt})
        assert code == 200 and marker in payload, fmt
    assert call(app, "POST", "/api/export-layout", {"project": cfg, "placements": pls, "format": "exe"})[0] == 400


def test_parallel_jobs_and_cancel():
    app = App()
    cfg = default_cfg(app)
    cfg["target_count"] = 30
    cfg["search"]["time_limit_s"] = 60
    jobs = [json.loads(call(app, "POST", "/api/start", cfg)[1])["job_id"] for _ in range(3)]
    time.sleep(0.5)
    for j in jobs:
        assert call(app, "POST", f"/api/cancel/{j}", {})[0] == 200
    for j in jobs:
        st = wait(app, j)
        assert st["state"] in ("cancelled", "finished")


def test_live_best_solution_endpoint():
    app = App()
    cfg = default_cfg(app)
    cfg["target_count"] = 5
    cfg["search"]["time_limit_s"] = 3
    job = json.loads(call(app, "POST", "/api/start", cfg)[1])["job_id"]
    seen = False
    t = time.time()
    while time.time() - t < 10 and not seen:
        r = json.loads(call(app, "GET", f"/api/live/{job}")[1])
        seen = r["geometry"] is not None
        time.sleep(0.1)
    wait(app, job)
    assert seen


def test_host_and_origin_checks():
    app = App()
    assert app.host_ok("127.0.0.1:8765", None)
    assert app.host_ok("localhost:8765", "http://localhost:8765")
    assert not app.host_ok("evil.com", None)
    assert not app.host_ok("127.0.0.1:8765", "http://evil.com")
    assert not app.host_ok(None, None)


def test_real_http_server_security_and_limits():
    server = serve("127.0.0.1", 0, open_browser=False)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert urllib.request.urlopen(base + "/").status == 200
        req = urllib.request.Request(base + "/api/default", headers={"Origin": "http://evil.com"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/start", data=b"x" * (9 * 1024 * 1024), method="POST")
        with pytest.raises(Exception):
            urllib.request.urlopen(req)
        req = urllib.request.Request(base + "/api/start", data=b"{", method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400
        # Types a browser may send cross site without a preflight request are rejected (CSRF protection)
        req = urllib.request.Request(base + "/api/start", data=b"{}", method="POST", headers={"Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 415
    finally:
        server.shutdown()
        server.server_close()


def test_parallel_workers_via_job_manager():
    app = App()
    cfg = default_cfg(app)
    cfg["target_count"] = 4
    cfg["search"]["time_limit_s"] = 2
    cfg["search"]["workers"] = 2
    job = json.loads(call(app, "POST", "/api/start", cfg)[1])["job_id"]
    st = wait(app, job, 60)
    assert st["state"] == "finished"
    res = json.loads(call(app, "GET", f"/api/result/{job}")[1])
    assert res["geometry"]["units"] and "x2" in res["result"]["optimizer"]
