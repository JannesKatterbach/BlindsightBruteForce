"""API of the motor sketch."""

import json
import time

import pytest
from blindsight import sketch as S
from blindsight.config import MotorSpec
from blindsight.web.server import App


def call(path, obj=None, raw=None, method="POST", headers=None):
    body = raw if raw is not None else json.dumps(obj).encode()
    code, ctype, payload = App().handle(method, path, {}, body, headers)
    return code, json.loads(payload)


def rect_sketch():
    b = S.Builder()
    b.rectangle(-14, -20, 10, -4)
    b.gear(5.0, 6.0, 4.0)
    return b.as_dict()


def test_solve_returns_state_profile_and_constraint_status():
    code, r = call("/api/sketch/solve", {"sketch": rect_sketch()})
    assert code == 200 and r["ok"] and r["state"] == "under" and r["dof"] == 4
    assert len(r["constraints"]) == len(rect_sketch()["constraints"])
    assert r["profile"]["gear"]["center_distance"] == pytest.approx(5.0)
    assert r["profile"]["bbox"] == pytest.approx({"xmin": -14, "ymin": -20, "xmax": 10, "ymax": -4})
    assert len(r["defined_entities"]) == len(rect_sketch()["entities"])


def test_solve_reports_conflicts_with_http_200():
    sk = rect_sketch()
    sk["constraints"] += [{"type": "length", "refs": ["e0"], "value": 10.0}, {"type": "length", "refs": ["e2"], "value": 12.0}]
    code, r = call("/api/sketch/solve", {"sketch": sk}, headers={"X-Language": "en"})
    assert code == 200 and not r["ok"] and r["state"] == "conflict" and "contradicts" in r["errors"][0]


def test_solve_drag():
    code, r = call("/api/sketch/solve", {"sketch": rect_sketch(), "drag": {"ref": "p4", "target": [14.0, -2.0]}})
    assert code == 200 and r["ok"] and r["sketch"]["points"][4] == pytest.approx([14.0, -2.0], abs=0.2)


def test_from_motor_builds_a_fully_defined_sketch():
    code, r = call("/api/sketch/from-motor", {"motor": {"width": 14, "depth": 20}})
    assert code == 200 and r["ok"] and r["state"] == "full" and r["dof"] == 0
    assert r["profile"]["bbox"]["xmax"] - r["profile"]["bbox"]["xmin"] == pytest.approx(14)
    assert r["profile"]["gear"]["diameter"] == pytest.approx(MotorSpec().gear_diameter)


@pytest.mark.parametrize("body", [{}, {"sketch": 5}, {"sketch": {"points": "x"}}, {"sketch": {"points": [], "entities": [{"type": 1}], "constraints": []}}])
def test_bad_bodies_do_not_crash(body):
    code, r = call("/api/sketch/solve", body)
    assert code == 400 or (code == 200 and not r["ok"])


def test_bad_arguments():
    assert call("/api/sketch/solve", raw=b"[]")[0] == 400
    assert call("/api/sketch/solve", raw=b"{")[0] == 400
    assert call("/api/sketch/zzz", {"sketch": rect_sketch()})[0] == 404
    assert call("/api/sketch/solve", {"sketch": rect_sketch(), "drag": {"ref": "o", "target": [1, 1]}})[1]["ok"] is False


def test_many_constraints_hit_limits_not_hang():
    sk = rect_sketch()
    sk["constraints"] += [{"type": "length", "refs": [f"e{i % 4}"], "value": 20.0 + i * 0.01} for i in range(200)]
    t = time.time()
    code, r = call("/api/sketch/solve", {"sketch": sk})
    assert time.time() - t < 8 and not r["ok"] and r["errors"]


def test_svg_import_returns_a_sketch_with_gear():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="30mm" viewBox="0 0 20 30"><path d="M0 0 L20 0 L20 20 L10 30 L0 20 Z"/></svg>'
    code, r = call("/api/svg-motor-import", {"svg": svg, "motor": {}})
    assert code == 200
    roles = [e["role"] for e in r["sketch"]["entities"]]
    assert roles.count("") == 5 and roles.count("gear") == 6
    code, s = call("/api/sketch/solve", {"sketch": r["sketch"]})
    assert s["ok"] and not s["warnings"]


def test_analyze_reports_sketch_problem_with_path():
    app = App()
    cfg = json.loads(app.handle("GET", "/api/default", {}, b"")[2])
    b = S.Builder()
    b.rectangle(-14, -20, 10, -4)  # no gear
    cfg["motor"]["sketch"] = b.as_dict()
    code, _, body = app.handle("POST", "/api/analyze", {}, json.dumps(cfg).encode())
    assert code == 400 and "motor.sketch" in json.loads(body)["errors"][0]
    cfg["motor"]["sketch"] = rect_sketch()
    code, _, body = app.handle("POST", "/api/analyze", {}, json.dumps(cfg).encode())
    assert code == 200


def test_schema_lists_constraint_types_with_signatures():
    code, _, body = App().handle("GET", "/api/schema", {}, b"", {"X-Language": "fr"})
    types = {t["name"]: t for t in json.loads(body)["sketch_constraints"]}
    assert types["coincident"]["label"] == "Coïncident" and ["point", "line"] in types["coincident"]["signatures"]
    assert types["diameter"]["value"] == "len" and types["angle"]["value"] == "deg"
