"""Sketch in the model. Rod frame, housing hull, gear from the sketch, validation, optimization, export."""

import math

import pytest
from blindsight import sketch as S
from blindsight.config import ConfigError, Project
from blindsight.export import EXPORTERS, build_geometry
from blindsight.geometry import Footprint, rotate_point
from blindsight.layout import Layout, Placement, layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import run_optimizer

# housing below the gear axis (gear at (-5, 0), shaft points to +y, housing behind it)
TRAP_MOTOR = [[-11, -26], [1, -26], [3, -3], [-13, -3]]


def pts_close(a, b, tol=1e-9):
    a, b = sorted((round(p[0] / tol), round(p[1] / tol)) for p in a), sorted((round(p[0] / tol), round(p[1] / tol)) for p in b)
    return all(abs(p[0] - q[0]) <= 2 and abs(p[1] - q[1]) <= 2 for p, q in zip(a, b)) and len(a) == len(b)


def sketch(outline, constraints=(), cd=5.0, diameter=6.0, gear_width=4.0):
    b = S.Builder()
    b.closed([tuple(p) for p in outline])
    for c in constraints:
        b.constrain(*c)
    b.gear(cd, diameter, gear_width)
    return b.as_dict()


def sketch_project(outline, constraints=(), cd=5.0, diameter=6.0, gear_width=4.0, **motor):
    data = Project().to_dict()
    data["motor"].update(motor)
    data["motor"]["sketch"] = sketch(outline, constraints, cd, diameter, gear_width)
    return Project.from_dict(data)


def test_motor_fields_come_from_the_sketch():
    p = sketch_project(TRAP_MOTOR, cd=6.5, diameter=7.0, gear_width=3.0, gear_diameter=99.0, width=40.0)
    mo = p.motor
    assert (mo.gear_diameter, mo.gear_width, mo.center_distance) == pytest.approx((7.0, 3.0, 6.5))
    assert (mo.width, mo.depth) == pytest.approx((16.0, 23.0))
    assert Project.from_json(p.to_json()).motor.gear_diameter == pytest.approx(7.0)


def test_sketch_motor_rotates_about_the_rod():
    m = Model(sketch_project(TRAP_MOTOR))
    radii = None
    for ang in (0, 30, 90, 215):
        parts = {q.kind: q for q in m.unit_parts(0, 55, 65, 1, ang)}
        r = sorted(round(math.hypot(x - 55, y - 65), 6) for x, y in parts["housing"].prism.fp.pts)
        assert radii is None or r == radii
        radii = r
        assert (parts["rod"].prism.fp.cx, parts["rod"].prism.fp.cy) == (55, 65)
    parts = {q.kind: q for q in m.unit_parts(0, 55, 65, 1, 0)}
    assert pts_close(parts["housing"].prism.fp.pts, [(55 + x, 65 + y) for x, y in TRAP_MOTOR], 1e-9)


def test_gear_sits_where_it_is_drawn():
    p = sketch_project(TRAP_MOTOR, cd=6.0, diameter=5.0, gear_width=3.0)
    m = Model(p)
    gear = next(q for q in m.unit_parts(0, 0, 0, 1, 0) if q.kind == "gear").prism.fp
    assert pts_close(gear.pts, [(-8.5, -1.5), (-3.5, -1.5), (-3.5, 1.5), (-8.5, 1.5)], 1e-9)
    gear90 = next(q for q in m.unit_parts(0, 0, 0, 1, 90) if q.kind == "gear").prism.fp
    assert math.isclose(gear90.cx, 0, abs_tol=1e-9) and math.isclose(gear90.cy, -6.0, abs_tol=1e-9)


def test_variable_center_distance_shifts_housing_with_gear():
    p = sketch_project(TRAP_MOTOR, center_distance_min=4.0, center_distance_max=7.0, center_distance_steps=4)
    m = Model(p)
    a = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 5.0) if q.kind == "housing").prism.fp
    b = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 7.0) if q.kind == "housing").prism.fp
    assert math.isclose(a.cx - b.cx, 2.0, abs_tol=1e-9)
    g = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 7.0) if q.kind == "gear").prism.fp
    assert math.isclose(g.cx, -7.0, abs_tol=1e-9)


def test_circle_housing_is_a_round_motor():
    b = S.Builder()
    b.points.append([-12.0, -16.0])
    b.entities.append({"type": "circle", "points": [0], "radius": 10.0, "construction": False, "role": ""})
    b.gear(5.0, 6.0, 4.0)
    data = Project().to_dict()
    data["motor"]["sketch"] = b.as_dict()
    m = Model(Project.from_dict(data))
    housing = next(q for q in m.unit_parts(0, 0, 0, 1, 0) if q.kind == "housing").prism.fp
    assert all(math.hypot(x + 12, y + 16) >= 10.0 - 1e-9 for x, y in housing.pts)
    assert all(math.hypot(x + 12, y + 16) <= 10.2 for x, y in housing.pts)


def test_unit_radius_covers_all_part_points():
    p = sketch_project(TRAP_MOTOR, center_distance_min=4.0, center_distance_max=8.0, center_distance_steps=3)
    m = Model(p)
    for cd in (None, 4.0, 6.0, 8.0):
        for q in m.unit_parts(0, 0, 0, 1, 33, cd):
            if q.kind != "rod":
                assert all(math.hypot(x, y) <= m.unit_radius + 1e-9 for x, y in q.prism.fp.pts)


def test_own_clearance_uses_housing_distance_to_rod():
    # housing only 0.1 mm from the rod (radius 2) -> own clearance 0.2 violated
    m = Model(sketch_project([[-12, -26], [4, -26], [4, -2.1], [-12, -2.1]], cd=8.0, gear_width=3.0))
    assert "eigene Stange" in m.cd_problem(None)
    assert not Layout(m).check(Placement(60, 60, 1, 0.0)).ok


def test_sketch_errors_are_reported_with_paths():
    with pytest.raises(ConfigError) as e:
        sketch_project(TRAP_MOTOR, [("length", ["e0"], 20.0), ("length", ["e0"], 7.0)])
    assert "widerspricht" in " ".join(e.value.errors) and "motor.sketch" in " ".join(e.value.errors)
    with pytest.raises(ConfigError) as e:
        sketch_project(TRAP_MOTOR, [("bogus", ["e0"])])
    assert "constraints[4].type" in " ".join(e.value.errors)
    with pytest.raises(ConfigError) as e:
        Project.from_dict({"motor": {"sketch": {"points": "x", "entities": [], "constraints": []}}})
    assert e.value.errors


def test_gear_overlapping_housing_is_rejected():
    with pytest.raises(ConfigError) as e:
        sketch_project([[-12, -26], [4, -26], [4, 0], [-12, 0]])  # reaches up to y = 0, the gear occupies -2 to 2
    assert "Zahnrad ragt" in " ".join(e.value.errors)


def test_constraints_are_enforced_when_the_model_is_built():
    """The stored points do not quite satisfy the constraints. The model uses the solved outline."""
    p = sketch_project(TRAP_MOTOR, [("length", ["e0"], 15.0), ("horizontal", ["e0"])])
    poly = Model(p).housing_nominal
    xs = sorted(x for x, y in poly if abs(y - min(q[1] for q in poly)) < 1e-6)
    assert math.isclose(xs[-1] - xs[0], 15.0, abs_tol=1e-6)


def test_optimizer_with_sketch_motor_yields_valid_layouts():
    d = sketch_project(TRAP_MOTOR, [("parallel", ["e0", "e2"])]).to_dict()
    d["target_count"] = 8
    d["search"]["time_limit_s"] = 3
    m = Model(Project.from_dict(d))
    res = run_optimizer(m)
    assert res.best and len(res.best.placements) == 8
    assert layout_from_placements(m, res.best.placements).all_collisions() == []


def test_exports_use_the_solved_sketch_contour():
    m = Model(sketch_project(TRAP_MOTOR))
    geo = build_geometry(m, [Placement(60, 60, 1, 0.0)])
    house = next(q for q in geo["units"][0]["parts"] if q["kind"] == "housing")
    assert pts_close([tuple(v) for v in house["outline"]], [(60 + x, 60 + y) for x, y in TRAP_MOTOR], 1e-9)
    assert "G1_MOTOR" in EXPORTERS["dxf"]().export(geo) and "<polygon" in EXPORTERS["svg"]().export(geo)


def test_sketch_from_motor_is_equivalent_to_the_rectangle():
    """Housing and gear of the sketch built from the motor fields lie where the plain rectangle puts them."""
    p = Project()
    plain = Model(p)
    q = Project.from_dict({**p.to_dict(), "motor": {**p.to_dict()["motor"], "sketch": S.sketch_from_motor(p.motor)}})
    sk = Model(q)
    for ang in (0, 45, 300):
        a = {k.kind: k for k in plain.unit_parts(0, 40, 50, 1, ang)}
        b = {k.kind: k for k in sk.unit_parts(0, 40, 50, 1, ang)}
        assert pts_close(a["housing"].prism.fp.pts, b["housing"].prism.fp.pts, 1e-7)
        assert pts_close(a["gear"].prism.fp.pts, b["gear"].prism.fp.pts, 1e-7)


def test_sketch_from_outline_is_equivalent_to_the_outline():
    """SVG import ends up at the same place as an outline without a sketch."""
    outline = [[-6, -12], [6, -12], [6, 2], [2, 12], [-2, 12], [-6, 2]]
    p = Project()
    p.motor.outline = outline
    legacy = Model(p)
    q = Project.from_dict({**Project().to_dict(), "motor": {**Project().to_dict()["motor"], "sketch": S.sketch_from_outline(outline, p.motor)}})
    sk = Model(q)
    for ang in (0, 45, 300):
        a = {k.kind: k for k in legacy.unit_parts(0, 40, 50, 1, ang)}
        b = {k.kind: k for k in sk.unit_parts(0, 40, 50, 1, ang)}
        assert pts_close(a["housing"].prism.fp.pts, b["housing"].prism.fp.pts, 1e-7)
        assert pts_close(a["gear"].prism.fp.pts, b["gear"].prism.fp.pts, 1e-7)
