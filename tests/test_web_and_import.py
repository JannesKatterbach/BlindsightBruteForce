import json

import pytest
from blindsight.motor_import import ScaleRequired, motor_outline_from_svg
from blindsight.web.server import App


def test_svg_import_requires_scale_when_ambiguous():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="12" height="24"/></svg>'
    with pytest.raises(ScaleRequired):
        motor_outline_from_svg(svg)
    assert motor_outline_from_svg(svg, mm_per_unit=1.0) == (12.0, 24.0)


def test_svg_import_with_units():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24mm" height="48mm" viewBox="0 0 12 24"><rect width="12" height="24"/></svg>'
    w, d = motor_outline_from_svg(svg)
    assert (round(w, 6), round(d, 6)) == (24.0, 48.0)


def test_api_roundtrip():
    app = App()
    code, _, body = app.handle("GET", "/api/default", {}, b"")
    cfg = json.loads(body)
    cfg["target_count"] = 3
    cfg["search"]["time_limit_s"] = 1
    code, _, body = app.handle("POST", "/api/start", {}, json.dumps(cfg).encode())
    assert code == 200
    job = json.loads(body)["job_id"]
    import time

    for _ in range(60):
        st = json.loads(app.handle("GET", f"/api/status/{job}", {}, b"")[2])
        if st["state"] != "running" and st["state"] != "queued":
            break
        time.sleep(0.1)
    code, _, body = app.handle("GET", f"/api/result/{job}", {}, b"")
    assert code == 200 and json.loads(body)["geometry"]["units"]
    code, ctype, svg = app.handle("GET", f"/api/export/{job}.svg", {}, b"")
    assert code == 200 and svg.startswith(b"<?xml")


def test_api_rejects_invalid_config():
    app = App()
    cfg = json.loads(app.handle("GET", "/api/default", {}, b"")[2])
    cfg["rod"]["diameter"] = -3
    code, _, body = app.handle("POST", "/api/start", {}, json.dumps(cfg).encode())
    assert code == 400 and json.loads(body)["errors"]
