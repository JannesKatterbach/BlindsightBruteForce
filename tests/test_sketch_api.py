"""API of the motor sketch."""

import json
import math
import time

import pytest
from blindsight.web.server import App


def call(path, obj=None, raw=None, method="POST"):
    app = App()
    body = raw if raw is not None else json.dumps(obj).encode()
    code, ctype, payload = app.handle(method, path, {}, body)
    return code, json.loads(payload)


RECT = [[-14, -20], [10, -20], [10, 2], [-14, 2]]


def C(t, a=None, b=None, value=None, **kw):
    return {"type": t, "a": a, "b": b, "value": value, "value2": kw.get("value2"), "ref": kw.get("ref", "rod"), "enabled": True, "name": ""}


def test_solve_returns_measures_state_and_constraint_status():
    code, r = call("/api/sketch/solve", {"sketch": {"points": RECT, "constraints": [C("length", 0, value=30.0), C("parallel", 0, 2)]}})
    assert code == 200 and r["ok"] and r["state"] == "under"
    assert math.isclose(r["measures"]["sides"][0], 30.0, abs_tol=1e-6)
    assert [c["status"] for c in r["constraints"]] == ["ok", "ok"]
    assert r["dof"] == 6 and r["convex"]


def test_solve_reports_conflicts_with_http_200():
    code, r = call("/api/sketch/solve", {"sketch": {"points": RECT, "constraints": [C("length", 0, value=20.0), C("length", 0, value=7.0)]}})
    assert code == 200 and not r["ok"] and r["state"] == "conflict" and "Nr. 2" in r["errors"][0]


def test_solve_drag():
    code, r = call("/api/sketch/solve", {"sketch": {"points": RECT, "constraints": []}, "drag": {"point": 2, "target": [25.0, 9.0]}})
    assert r["ok"] and r["sketch"]["points"][2] == pytest.approx([25.0, 9.0], abs=1e-6)


def test_gear_overlap_warning():
    code, r = call("/api/sketch/solve", {"sketch": {"points": [[-12, -26], [4, -26], [4, 0], [-12, 0]], "constraints": []}, "cd": 5.0, "gear": [6.0, 4.0]})
    assert r["ok"] and any("Zahnrad ragt" in w for w in r["warnings"])


def test_from_motor_builds_a_dimensioned_rectangle():
    code, r = call("/api/sketch/from-motor", {"motor": {"width": 12.0, "depth": 24.0}})
    assert code == 200 and r["ok"] and r["state"] == "under"
    sides = r["measures"]["sides"]
    assert sides == pytest.approx([12.0, 24.0, 12.0, 24.0], abs=1e-6)
    assert r["measures"]["angles"] == pytest.approx([90.0] * 4, abs=1e-6)
    # the housing lies below the gear, rod at the origin
    ys = [p[1] for p in r["sketch"]["points"]]
    assert max(ys) < 0


def test_from_motor_with_polygon_outline_and_without_constraints():
    code, r = call("/api/sketch/from-motor", {"motor": {"outline": [[-6, -12], [6, -12], [6, 2], [2, 12], [-2, 12], [-6, 2]]}, "constraints": False})
    assert r["ok"] and len(r["sketch"]["points"]) == 6 and r["sketch"]["constraints"] == []


def test_hull_insert_delete():
    sk = {"points": [[0, 0], [10, 0], [3, 3], [0, 10]], "constraints": []}
    code, r = call("/api/sketch/hull", {"sketch": sk})
    assert r["ok"] and len(r["sketch"]["points"]) == 3 and r["convex"]
    code, r = call("/api/sketch/insert", {"sketch": {"points": RECT, "constraints": []}, "side": 1})
    assert len(r["sketch"]["points"]) == 5
    code, r = call("/api/sketch/delete", {"sketch": {"points": RECT, "constraints": []}, "point": 0})
    assert len(r["sketch"]["points"]) == 3
    code, r = call("/api/sketch/delete", {"sketch": {"points": RECT[:3], "constraints": []}, "point": 0})
    assert not r["ok"] and r["errors"]


@pytest.mark.parametrize("body", [{}, {"sketch": 5}, {"sketch": {"points": [[0, 0], [1, 0], [0, 1]], "constraints": [{"type": "x"}]}}, {"sketch": {"points": "abc", "constraints": []}}])
def test_bad_bodies_do_not_crash(body):
    code, r = call("/api/sketch/solve", body)
    assert code == 400 or (code == 200 and not r["ok"])


def test_bad_arguments():
    sk = {"points": RECT, "constraints": []}
    assert call("/api/sketch/insert", {"sketch": sk, "side": "x"})[0] == 400
    assert call("/api/sketch/insert", {"sketch": sk, "side": True})[0] == 400
    assert call("/api/sketch/solve", {"sketch": sk, "gear": "x"})[0] == 400
    # NaN is not valid JSON and is rejected when reading, an invalid value by the solver
    code, body = call("/api/sketch/solve", {"sketch": sk, "cd": float("nan")})
    assert code == 400 and body["errors"]
    assert call("/api/sketch/solve", {"sketch": sk, "cd": -1})[1]["ok"] is False
    assert call("/api/sketch/solve", raw=b"[]")[0] == 400
    assert call("/api/sketch/solve", raw=b"{")[0] == 400
    assert call("/api/sketch/zzz", {"sketch": sk})[0] == 404


def test_many_constraints_hit_limits_not_hang():
    t = time.time()
    cons = [C("length", i % 4, value=20.0 + i * 0.01) for i in range(200)]
    code, r = call("/api/sketch/solve", {"sketch": {"points": RECT, "constraints": cons}})
    assert time.time() - t < 6 and not r["ok"] and r["errors"]


def test_svg_import_returns_sketch():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="30mm" viewBox="0 0 20 30"><path d="M0 0 L20 0 L20 20 L10 30 L0 20 Z"/></svg>'
    code, r = call("/api/svg-motor-import", {"svg": svg, "motor": {}})
    assert code == 200 and len(r["sketch"]["points"]) == 5
    code, s = call("/api/sketch/solve", {"sketch": r["sketch"]})
    assert s["ok"] and s["convex"]


def test_analyze_reports_sketch_problem_with_path():
    app = App()
    cfg = json.loads(app.handle("GET", "/api/default", {}, b"")[2])
    cfg["motor"]["sketch"] = {"points": [[0, 0], [10, 0], [3, 3], [0, 10]], "constraints": []}
    code, _, body = app.handle("POST", "/api/analyze", {}, json.dumps(cfg).encode())
    assert code == 400 and "motor.sketch" in json.loads(body)["errors"][0]
    cfg["motor"]["sketch"] = {"points": [[-11, -26], [1, -26], [3, -3], [-13, -3]], "constraints": []}
    code, _, body = app.handle("POST", "/api/analyze", {}, json.dumps(cfg).encode())
    assert code == 200
