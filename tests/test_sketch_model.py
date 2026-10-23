"""Skizze im Modell. Stangenrahmen, Rueckwaertskompatibilitaet, Validierung, Optimierung, Export."""

import copy
import math
import random

import pytest
from blindsight import sketch as S
from blindsight.config import ConfigError, Project
from blindsight.export import EXPORTERS, build_geometry
from blindsight.geometry import Footprint, rotate_point
from blindsight.layout import Layout, Placement, layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import run_optimizer


def old_world_parts(m, x, y, angle_deg, cd):
    """Unabhaengige Nachbildung der frueheren Formel (Gehaeusesystem, Drehung um die Stange)."""
    mo = m.project.motor
    a = math.radians(angle_deg)
    rx, ry = mo.rod_local(cd)
    world = lambda lx, ly: rotate_point(x + (lx - rx), y + (ly - ry), x, y, a)
    poly = Footprint.polygon(mo.outline).pts if mo.outline else Footprint.rect(0, 0, mo.width, mo.depth).pts
    housing = [world(px, py) for px, py in poly]
    gear = Footprint.rect(*world(mo.shaft_x, mo.gear_center_y), mo.gear_diameter, mo.gear_width, a).pts
    return housing, gear


def pts_close(a, b, tol=1e-9):
    a, b = sorted((round(p[0] / tol), round(p[1] / tol)) for p in a), sorted((round(p[0] / tol), round(p[1] / tol)) for p in b)
    return all(abs(p[0] - q[0]) <= 2 and abs(p[1] - q[1]) <= 2 for p, q in zip(a, b)) and len(a) == len(b)


def random_motor_project(rng):
    p = Project()
    mo = p.motor
    mo.width, mo.depth = rng.uniform(6, 18), rng.uniform(10, 30)
    mo.shaft_x = rng.uniform(-2, 2)
    mo.gear_diameter, mo.gear_width = rng.uniform(3, 8), rng.uniform(2, 6)
    mo.gear_gap = rng.uniform(0, 3)
    mo.center_distance = rng.uniform(3, 8)
    mo.center_distance_min, mo.center_distance_max, mo.center_distance_steps = 3.0, 9.0, 4
    mo.axis_height = 5.0
    return p


def test_golden_legacy_rectangle_matches_old_formula():
    rng = random.Random(5)
    for _ in range(40):
        p = random_motor_project(rng)
        m = Model(p)
        for _ in range(5):
            x, y, ang = rng.uniform(20, 90), rng.uniform(20, 90), rng.choice([0, 17, 90, 133, 270, 359])
            cd = rng.choice([None, 4.0, 6.5, 9.0])
            parts = {q.kind: q for q in m.unit_parts(0, x, y, 1, ang, cd)}
            housing, gear = old_world_parts(m, x, y, ang, p.motor.center_distance if cd is None else cd)
            assert pts_close(parts["housing"].prism.fp.pts, housing)
            assert pts_close(parts["gear"].prism.fp.pts, gear)
            assert (parts["rod"].prism.fp.cx, parts["rod"].prism.fp.cy) == (x, y)


def test_golden_legacy_polygon_outline_matches_old_formula():
    p = Project()
    p.motor.outline = [[-6, -12], [6, -12], [6, 2], [2, 12], [-2, 12], [-6, 2]]
    m = Model(p)
    for ang in (0, 45, 200):
        parts = {q.kind: q for q in m.unit_parts(0, 50, 60, 1, ang)}
        housing, gear = old_world_parts(m, 50, 60, ang, p.motor.center_distance)
        assert pts_close(parts["housing"].prism.fp.pts, housing)
        assert pts_close(parts["gear"].prism.fp.pts, gear)


def test_sketch_from_legacy_rectangle_is_equivalent_to_the_rectangle():
    rng = random.Random(8)
    for _ in range(20):
        p = random_motor_project(rng)
        legacy = Model(p)
        sk = Model(Project.from_dict(_with_sketch(p, S.legacy_to_sketch(p.motor))))
        for ang in (0, 77, 181):
            for cd in (None, 4.0, 9.0):
                a = {k.kind: k for k in legacy.unit_parts(0, 40, 50, 1, ang, cd)}
                b = {k.kind: k for k in sk.unit_parts(0, 40, 50, 1, ang, cd)}
                assert pts_close(a["housing"].prism.fp.pts, b["housing"].prism.fp.pts, 1e-7)
                assert pts_close(a["gear"].prism.fp.pts, b["gear"].prism.fp.pts, 1e-7)
        assert math.isclose(legacy.unit_radius, sk.unit_radius, abs_tol=1e-6)


def _with_sketch(p, sketch):
    d = p.to_dict()
    d["motor"]["sketch"] = sketch
    d["motor"]["outline"] = None
    return d


def test_uncentered_legacy_outline_places_gear_behind_outline_top():
    """Regression. Ein nicht zentrierter Umriss platzierte das Zahnrad frueher falsch (es hing an depth / 2)."""
    p = Project()
    p.motor.outline = [[-6, 0], [6, 0], [6, 30], [-6, 30]]  # y von 0 bis 30, Mitte bei 15
    p.motor.depth = 30.0
    m = Model(p)
    gear = next(q for q in m.unit_parts(0, 0, 0, 1, 0) if q.kind == "gear")
    house = next(q for q in m.unit_parts(0, 0, 0, 1, 0) if q.kind == "housing")
    top = max(y for _, y in house.prism.fp.pts)
    bottom_gear = min(y for _, y in gear.prism.fp.pts)
    assert math.isclose(bottom_gear - top, p.motor.gear_gap, abs_tol=1e-9)


# ---- Skizzenmotor ---------------------------------------------------------------------------------
def sketch_project(points=None, constraints=None, **motor):
    p = Project()
    p.stack.n_motor_planes = 3
    p.motor.sketch = None
    d = p.to_dict()
    d["motor"]["sketch"] = {
        "points": points or TRAP_MOTOR,
        "constraints": constraints or [],
    }
    d["motor"].update(motor)
    return Project.from_dict(d)


# Gehaeuse unterhalb der Zahnradachse (Zahnrad liegt bei (-5, 0), Welle zeigt nach +y, Gehaeuse dahinter)
TRAP_MOTOR = [[-11, -26], [1, -26], [3, -3], [-13, -3]]


def test_sketch_motor_rotates_about_the_rod():
    p = sketch_project(TRAP_MOTOR)
    m = Model(p)
    radii = None
    for ang in (0, 30, 90, 215):
        parts = {q.kind: q for q in m.unit_parts(0, 55, 65, 1, ang)}
        r = sorted(round(math.hypot(x - 55, y - 65), 6) for x, y in parts["housing"].prism.fp.pts)
        assert radii is None or r == radii
        radii = r
        assert (parts["rod"].prism.fp.cx, parts["rod"].prism.fp.cy) == (55, 65)
    # Bei 0 Grad liegen die Eckpunkte exakt wie in der Skizze relativ zur Stange
    parts = {q.kind: q for q in m.unit_parts(0, 55, 65, 1, 0)}
    assert pts_close(parts["housing"].prism.fp.pts, [(55 + x, 65 + y) for x, y in TRAP_MOTOR], 1e-9)


def test_sketch_gear_is_at_minus_center_distance():
    p = sketch_project(TRAP_MOTOR)
    m = Model(p)
    gear = next(q for q in m.unit_parts(0, 0, 0, 1, 0) if q.kind == "gear").prism.fp
    assert math.isclose(gear.cx, -p.motor.center_distance, abs_tol=1e-9) and math.isclose(gear.cy, 0, abs_tol=1e-9)
    gear90 = next(q for q in m.unit_parts(0, 0, 0, 1, 90) if q.kind == "gear").prism.fp
    assert math.isclose(gear90.cx, 0, abs_tol=1e-9) and math.isclose(gear90.cy, -p.motor.center_distance, abs_tol=1e-9)


def test_sketch_center_distance_shifts_housing_with_gear():
    p = sketch_project(TRAP_MOTOR, center_distance=5.0, center_distance_min=4.0, center_distance_max=7.0, center_distance_steps=4)
    m = Model(p)
    a = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 5.0) if q.kind == "housing").prism.fp
    b = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 7.0) if q.kind == "housing").prism.fp
    assert math.isclose(a.cx - b.cx, 2.0, abs_tol=1e-9)
    g = next(q for q in m.unit_parts(0, 0, 0, 1, 0, 7.0) if q.kind == "gear").prism.fp
    assert math.isclose(g.cx, -7.0, abs_tol=1e-9)


def test_unit_radius_covers_all_part_points():
    p = sketch_project(TRAP_MOTOR, center_distance_min=4.0, center_distance_max=8.0, center_distance_steps=3)
    m = Model(p)
    for cd in (None, 4.0, 6.0, 8.0):
        for q in m.unit_parts(0, 0, 0, 1, 33, cd):
            if q.kind == "rod":
                continue
            assert all(math.hypot(x, y) <= m.unit_radius + 1e-9 for x, y in q.prism.fp.pts)


def test_own_clearance_uses_housing_distance_to_rod():
    # Gehaeuse nur 0.1 mm von der Stange (Radius 2) entfernt -> Eigenabstand 0.2 verletzt
    pts = [[-12, -26], [4, -26], [4, -2.1], [-12, -2.1]]
    p = sketch_project(pts)
    m = Model(p)
    assert "eigene Stange" in m.cd_problem(None)
    lay = Layout(m)
    assert not lay.check(Placement(60, 60, 1, 0.0)).ok


def test_sketch_errors_are_reported_with_paths():
    with pytest.raises(ConfigError) as e:
        sketch_project([[0, 0], [10, 0], [3, 3], [0, 10]])
    assert "motor.sketch" in " ".join(e.value.errors) and "konvex" in " ".join(e.value.errors)
    with pytest.raises(ConfigError) as e:
        sketch_project(TRAP_MOTOR, [{"type": "length", "a": 0, "value": 20.0}, {"type": "length", "a": 0, "value": 7.0}, {"type": "parallel", "a": 0, "b": 2}])
    assert "widerspricht" in " ".join(e.value.errors)
    with pytest.raises(ConfigError) as e:
        sketch_project(TRAP_MOTOR, [{"type": "bogus"}])
    assert "constraints[0].type" in " ".join(e.value.errors)
    with pytest.raises(ConfigError) as e:
        Project.from_dict({"motor": {"sketch": {"points": "x", "constraints": []}}})
    assert e.value.errors


def test_gear_overlapping_housing_is_rejected():
    pts = [[-12, -26], [4, -26], [4, 0], [-12, 0]]  # reicht bis y = 0, das Zahnrad belegt y von -2 bis 2
    with pytest.raises(ConfigError) as e:
        sketch_project(pts)
    assert "Zahnrad ragt" in " ".join(e.value.errors)


def test_sketch_config_roundtrip_json():
    cons = [{"type": "length", "a": 1, "value": 24.0}, {"type": "parallel", "a": 0, "b": 2}]
    p = sketch_project(TRAP_MOTOR, cons)
    q = Project.from_json(p.to_json())
    assert q.to_dict() == p.to_dict()
    assert q.motor.sketch.constraints[0].type == "length"


def test_constraints_are_enforced_when_the_model_is_built():
    """Die gespeicherten Punkte genuegen den Constraints nicht ganz. Das Modell nutzt die geloeste Kontur."""
    pts = TRAP_MOTOR
    p = sketch_project(pts, [{"type": "length", "a": 0, "value": 15.0}])
    m = Model(p)
    poly = m.housing_nominal
    assert math.isclose(math.dist(poly[0], poly[1]), 15.0, abs_tol=1e-6)


def test_optimizer_with_sketch_motor_yields_valid_layouts():
    p = sketch_project(TRAP_MOTOR, [{"type": "parallel", "a": 0, "b": 2}], center_distance=5.0)
    d = p.to_dict()
    d["target_count"] = 8
    d["search"]["time_limit_s"] = 3
    p = Project.from_dict(d)
    m = Model(p)
    res = run_optimizer(m)
    assert res.best and len(res.best.placements) == 8
    assert layout_from_placements(m, res.best.placements).all_collisions() == []


def test_exports_use_the_solved_sketch_contour():
    p = sketch_project(TRAP_MOTOR)
    m = Model(p)
    geo = build_geometry(m, [Placement(60, 60, 1, 0.0)])
    house = next(q for q in geo["units"][0]["parts"] if q["kind"] == "housing")
    assert pts_close([tuple(v) for v in house["outline"]], [(60 + x, 60 + y) for x, y in TRAP_MOTOR], 1e-9)
    svg = EXPORTERS["svg"]().export(geo)
    dxf = EXPORTERS["dxf"]().export(geo)
    assert "G1_MOTOR" in dxf and "<polygon" in svg


def test_sketch_ignores_legacy_fields():
    a = Model(sketch_project(TRAP_MOTOR)).housing_nominal
    b = Model(sketch_project(TRAP_MOTOR, width=40.0, depth=80.0, shaft_x=3.0, gear_gap=7.0)).housing_nominal
    assert a == b


def test_sketch_from_outline_is_equivalent_to_the_legacy_outline():
    """SVG Import und gezeichnete Konturen landen an derselben Stelle wie ein Umriss ohne Skizze."""
    outline = [[-6, -12], [6, -12], [6, 2], [2, 12], [-2, 12], [-6, 2]]
    p = Project()
    p.motor.outline = outline
    legacy = Model(p)
    q = Project.from_dict(_with_sketch(Project(), S.sketch_from_outline(outline, p.motor)))
    sk = Model(q)
    for ang in (0, 45, 300):
        a = {k.kind: k for k in legacy.unit_parts(0, 40, 50, 1, ang)}
        b = {k.kind: k for k in sk.unit_parts(0, 40, 50, 1, ang)}
        assert pts_close(a["housing"].prism.fp.pts, b["housing"].prism.fp.pts, 1e-7)
        assert pts_close(a["gear"].prism.fp.pts, b["gear"].prism.fp.pts, 1e-7)


def test_sketch_from_uncentered_outline_places_gear_behind_the_top_edge():
    outline = [[-6, 0], [6, 0], [6, 30], [-6, 30]]
    p = Project()
    sk = S.sketch_from_outline(outline, p.motor)
    top = max(y for _, y in sk["points"])
    assert math.isclose(-top, p.motor.gear_gap + p.motor.gear_width / 2, abs_tol=1e-9)
