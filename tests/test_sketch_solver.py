"""Solver of the motor sketch (Onshape like entities). All checks measure the result independently of the solver."""

import math
import random

import pytest

from blindsight import sketch as S
from blindsight.sketch.constraints import measured_angle

TOL = 1e-5


def c(t, refs, value=None, at=None, enabled=True):
    return {"type": t, "refs": refs, "value": value, "at": at, "enabled": enabled, "name": "", "label": None}


def pt(sk, ref):
    if ref == "o":
        return (0.0, 0.0)
    i = int(ref[1:])
    if ref[0] == "e":
        i = sk["entities"][i]["points"][0]
    return tuple(sk["points"][i])


def ends(sk, k):
    a, b = sk["entities"][k]["points"]
    return tuple(sk["points"][a]), tuple(sk["points"][b])


def length(sk, k):
    a, b = ends(sk, k)
    return math.hypot(b[0] - a[0], b[1] - a[1])


def radius(sk, k):
    e = sk["entities"][k]
    if e["type"] == "circle":
        return e["radius"]
    centre, start = (sk["points"][p] for p in e["points"][:2])
    return math.hypot(start[0] - centre[0], start[1] - centre[1])


def line_distance(p, a, b):
    return abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) / math.hypot(b[0] - a[0], b[1] - a[1])


def free_lines(n=2):
    """n loose lines in general position."""
    b = S.Builder()
    for i in range(n):
        b.line((i * 3.0, i * 2.0), (i * 3.0 + 7.0, i * 2.0 + 3.0 + i))
    return b


def solved(sk):
    res = S.solve(sk)
    assert res.ok, res.errors
    return res.sketch, res


# ---- single constraint types ------------------------------------------------------------------------
def test_coincident_point_point_line_and_curve():
    b = free_lines(2)
    circle_centre = len(b.points)
    b.points.append([20.0, 0.0])
    b.entities.append({"type": "circle", "points": [circle_centre], "radius": 4.0, "construction": False, "role": ""})
    b.constrain("coincident", ["p1", "p2"])  # end of line 0 on start of line 1
    b.constrain("coincident", ["p3", "e0"])  # end of line 1 on line 0
    b.constrain("coincident", ["p0", "e2"])  # start of line 0 on the circle
    sk, _ = solved(b.as_dict())
    assert math.dist(pt(sk, "p1"), pt(sk, "p2")) < TOL
    assert line_distance(pt(sk, "p3"), *ends(sk, 0)) < TOL
    assert abs(math.dist(pt(sk, "p0"), pt(sk, "p4")) - sk["entities"][2]["radius"]) < TOL


def test_horizontal_vertical_parallel_perpendicular_equal():
    b = free_lines(3)
    b.constrain("horizontal", ["e0"])
    b.constrain("perpendicular", ["e0", "e1"])
    b.constrain("parallel", ["e2", "e0"])
    b.constrain("equal", ["e1", "e2"])
    b.constrain("vertical", ["p0", "p4"])  # two points
    sk, _ = solved(b.as_dict())
    (a0, b0), (a1, b1), (a2, b2) = ends(sk, 0), ends(sk, 1), ends(sk, 2)
    assert abs(a0[1] - b0[1]) < TOL and abs(b1[0] - a1[0]) < TOL and abs(b2[1] - a2[1]) < TOL
    assert abs(length(sk, 1) - length(sk, 2)) < TOL
    assert abs(pt(sk, "p0")[0] - pt(sk, "p4")[0]) < TOL


def test_midpoint_and_concentric_with_origin():
    b = free_lines(1)
    b.point_entity(3.0, 4.0)
    b.points.append([5.0, 5.0])
    b.entities.append({"type": "circle", "points": [3], "radius": 2.0, "construction": False, "role": ""})
    b.constrain("midpoint", ["e1", "e0"])
    b.constrain("concentric", ["e2", "o"])
    sk, _ = solved(b.as_dict())
    a, e = ends(sk, 0)
    assert math.dist(pt(sk, "e1"), ((a[0] + e[0]) / 2, (a[1] + e[1]) / 2)) < TOL
    assert math.dist(pt(sk, "p3"), (0.0, 0.0)) < TOL


def test_dimensions_are_met():
    b = free_lines(3)
    b.points.append([20.0, 0.0])
    b.entities.append({"type": "circle", "points": [6], "radius": 4.0, "construction": False, "role": ""})
    b.constrain("length", ["e0"], 12.0)
    b.constrain("angle", ["e0", "e1"], 35.0)
    b.constrain("distance", ["p4", "e0"], 6.5)
    b.constrain("distance", ["o", "p0"], 3.0)
    b.constrain("hdistance", ["o", "p2"], 9.0)
    b.constrain("vdistance", ["o", "p5"], 4.0)
    b.constrain("diameter", ["e3"], 7.0)
    sk, _ = solved(b.as_dict())
    assert abs(length(sk, 0) - 12.0) < TOL
    assert abs(measured_angle(S.Vars(sk), S.Vars(sk).vector(), "e0", "e1") - 35.0) < 1e-4
    assert abs(line_distance(pt(sk, "p4"), *ends(sk, 0)) - 6.5) < TOL
    assert abs(math.dist(pt(sk, "p0"), (0, 0)) - 3.0) < TOL
    assert abs(abs(pt(sk, "p2")[0]) - 9.0) < TOL and abs(abs(pt(sk, "p5")[1]) - 4.0) < TOL
    assert abs(2 * sk["entities"][3]["radius"] - 7.0) < TOL


def test_angle_at_a_corner_is_the_angle_between_the_lines():
    b = S.Builder()
    b.line((0, 0), (10, 0))
    b.line((10, 0), (8, 9))
    b.constrain("coincident", ["p1", "p2"])
    b.constrain("angle", ["e0", "e1"], 60.0)
    sk, _ = solved(b.as_dict())
    d0 = (pt(sk, "p0")[0] - pt(sk, "p1")[0], pt(sk, "p0")[1] - pt(sk, "p1")[1])
    d1 = (pt(sk, "p3")[0] - pt(sk, "p2")[0], pt(sk, "p3")[1] - pt(sk, "p2")[1])
    corner = math.degrees(math.acos((d0[0] * d1[0] + d0[1] * d1[1]) / (math.hypot(*d0) * math.hypot(*d1))))
    assert abs(corner - 60.0) < 1e-4


def test_arc_keeps_one_radius_and_takes_dimensions():
    b = S.Builder()
    b.points += [[0.0, 0.0], [5.0, 0.0], [0.0, 6.0]]
    b.entities.append({"type": "arc", "points": [0, 1, 2], "radius": None, "construction": False, "role": ""})
    b.constrain("radius", ["e0"], 8.0)
    sk, _ = solved(b.as_dict())
    assert abs(math.dist(pt(sk, "p0"), pt(sk, "p1")) - 8.0) < TOL
    assert abs(math.dist(pt(sk, "p0"), pt(sk, "p2")) - 8.0) < TOL


def test_fix_keeps_a_point():
    b = free_lines(1)
    b.constraints.append(c("fix", ["p0"], at=[1.5, -2.0]))
    sk, _ = solved(b.as_dict())
    assert math.dist(pt(sk, "p0"), (1.5, -2.0)) < TOL


# ---- degrees of freedom, redundancy, conflict ------------------------------------------------------------
def test_motor_sketch_is_fully_defined_and_black():
    res = S.solve(S.sketch_from_motor(S_motor()))
    assert res.state == "full" and res.dof == 0
    assert all(res.defined_entities) and all(res.defined_points)


def S_motor():
    from blindsight.config import MotorSpec

    return MotorSpec()


def test_free_rectangle_has_four_degrees_of_freedom():
    b = S.Builder()
    b.rectangle(0, 0, 10, 6)
    res = S.solve(b.as_dict())
    assert res.state == "under" and res.dof == 4
    assert not any(res.defined_entities)
    b.constrain("length", ["e0"], 10.0)
    b.constrain("length", ["e1"], 6.0)
    b.constrain("coincident", ["p0", "o"])
    res = S.solve(b.as_dict())
    assert res.state == "full" and res.dof == 0 and all(res.defined_entities)


def test_partially_defined_entities_are_reported():
    b = S.Builder()
    b.line((0, 0), (10, 0))
    b.line((0, 5), (10, 5))
    b.constrain("coincident", ["p0", "o"])
    b.constrain("horizontal", ["e0"])
    b.constrain("length", ["e0"], 10.0)
    res = S.solve(b.as_dict())
    assert res.defined_entities == [True, False]
    assert res.defined_points[:2] == [True, True]


def test_redundant_and_conflicting_constraints():
    b = S.Builder()
    b.rectangle(0, 0, 10, 6)
    b.constrain("parallel", ["e0", "e2"])  # already given by two horizontals
    res = S.solve(b.as_dict())
    assert res.state == "over" and res.constraints[-1]["status"] == "redundant"
    b.constraints.pop()
    b.constrain("length", ["e0"], 10.0)
    b.constrain("length", ["e2"], 12.0)  # the opposite side of a rectangle cannot be longer
    res = S.solve(b.as_dict())
    assert res.state == "conflict" and not res.ok
    assert res.constraints[-1]["status"] == "conflict" and res.errors


def test_disabled_constraint_is_ignored():
    b = free_lines(1)
    b.constraints.append(c("length", ["e0"], 3.0, enabled=False))
    sk, res = solved(b.as_dict())
    assert res.constraints[0]["status"] == "disabled"
    assert abs(length(sk, 0) - 3.0) > 1.0


# ---- dragging ------------------------------------------------------------------------------------------------
def test_dragging_a_point_keeps_constraints():
    b = S.Builder()
    b.rectangle(0, 0, 10, 6)
    res = S.solve(b.as_dict(), drag={"ref": "p4", "target": [14.0, 9.0]})
    sk = res.sketch
    assert res.ok and math.dist(pt(sk, "p4"), (14.0, 9.0)) < 0.2
    for k in (0, 2):
        a, e = ends(sk, k)
        assert abs(a[1] - e[1]) < TOL


def test_dragging_a_line_moves_it_and_a_circle_radius():
    b = free_lines(1)
    b.points.append([20.0, 0.0])
    b.entities.append({"type": "circle", "points": [2], "radius": 3.0, "construction": False, "role": ""})
    sk0 = b.as_dict()
    res = S.solve(sk0, drag={"ref": "e0", "grab": [3.5, 1.5], "target": [5.5, 0.5]})
    assert math.dist(pt(res.sketch, "p0"), (2.0, -1.0)) < 0.05
    res = S.solve(sk0, drag={"ref": "e1", "grab": [23.0, 0.0], "target": [25.0, 0.0], "mode": "radius"})
    assert abs(res.sketch["entities"][1]["radius"] - 5.0) < 0.05


@pytest.mark.parametrize("drag", [{"ref": "o", "target": [1, 1]}, {"ref": "p99", "target": [1, 1]}, {"ref": "p0"}, {"target": [1, 1]}])
def test_bad_drag_is_rejected(drag):
    res = S.solve(free_lines(1).as_dict(), drag=drag)
    assert res.state == "invalid" and res.errors


# ---- structure ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("change, needle", [
    (lambda s: s["entities"].append({"type": "spline", "points": [], "radius": None, "construction": False, "role": ""}), "type"),
    (lambda s: s["entities"].append({"type": "line", "points": [0, 9], "radius": None, "construction": False, "role": ""}), "points"),
    (lambda s: s["entities"].append({"type": "circle", "points": [], "radius": 1, "construction": False, "role": ""}), "points"),
    (lambda s: s["constraints"].append(c("parallel", ["e0", "p0"])), "refs"),
    (lambda s: s["constraints"].append(c("length", ["e0"], -1.0)), "value"),
    (lambda s: s["constraints"].append(c("length", ["e0"])), "value"),
    (lambda s: s["constraints"].append(c("nope", ["e0"])), "type"),
    (lambda s: s["constraints"].append(c("equal", ["e0", "e0"])), "refs"),
    (lambda s: s["entities"][0].update(role="motor"), "role"),
])
def test_structure_errors_name_the_field(change, needle):
    sk = free_lines(1).as_dict()
    change(sk)
    res = S.solve(sk)
    assert res.state == "invalid" and any(needle in e for e in res.errors), res.errors


def test_delete_entities_renumbers_and_drops_constraints():
    b = free_lines(3)
    b.constrain("coincident", ["p1", "p2"])
    b.constrain("parallel", ["e0", "e2"])
    b.constrain("length", ["e2"], 5.0)
    sk = S.delete_entities(b.as_dict(), {1})
    assert len(sk["entities"]) == 2 and len(sk["points"]) == 4
    assert [x["refs"] for x in sk["constraints"]] == [["e0", "e1"], ["e1"]]
    assert sk["entities"][1]["points"] == [2, 3]
    assert S.solve(sk).ok


# ---- profile -----------------------------------------------------------------------------------------------------
def test_housing_is_the_hull_without_construction_and_gear():
    b = S.Builder()
    b.rectangle(-10, -20, 2, -4)
    b.line((-30, -30), (30, 30), construction=True)
    b.gear(5.0, 6.0, 4.0)
    res = S.solve(b.as_dict())
    prof = res.profile
    assert prof["bbox"] == pytest.approx({"xmin": -10, "ymin": -20, "xmax": 2, "ymax": -4})
    assert prof["gear"]["diameter"] == pytest.approx(6.0) and prof["gear"]["center_distance"] == pytest.approx(5.0)
    assert not res.warnings


def test_circle_and_arc_hull_is_conservative():
    b = S.Builder()
    b.points.append([-10.0, -20.0])
    b.entities.append({"type": "circle", "points": [0], "radius": 6.0, "construction": False, "role": ""})
    b.gear(5.0, 6.0, 4.0)
    prof = S.solve(b.as_dict()).profile
    for angle in range(0, 360, 7):
        x, y = -10 + 6 * math.cos(math.radians(angle)), -20 + 6 * math.sin(math.radians(angle))
        assert _inside(prof["housing"], (x, y), 1e-9)


def _inside(poly, p, tol):
    n = len(poly)
    return all((poly[(i + 1) % n][0] - poly[i][0]) * (p[1] - poly[i][1]) - (poly[(i + 1) % n][1] - poly[i][1]) * (p[0] - poly[i][0]) >= -tol
               for i in range(n))


@pytest.mark.parametrize("build, needle", [
    (lambda b: b.rectangle(-10, -20, 2, -4), "Kein Zahnrad"),
    (lambda b: b.gear(5.0, 6.0, 4.0), "Kein Gehäuse"),
    (lambda b: (b.rectangle(-10, -6, 2, 6), b.gear(5.0, 6.0, 4.0)), "ragt"),
])
def test_profile_problems(build, needle):
    b = S.Builder()
    build(b)
    res = S.solve(b.as_dict())
    assert any(needle in w for w in res.warnings), res.warnings


def test_gear_must_stay_on_the_x_axis():
    b = S.Builder()
    b.rectangle(-10, -20, 2, -4)
    b.gear(5.0, 6.0, 4.0)
    sk = b.as_dict()
    sk["constraints"] = [x for x in sk["constraints"] if not (x["type"] == "horizontal" and "o" in x["refs"])]
    res = S.solve(sk, drag={"ref": f"e{len(sk['entities']) - 1}", "target": [-5.0, 3.0]})
    assert any("x Achse" in w for w in res.warnings)


# ---- random check -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(12))
def test_random_polygons_with_measured_constraints_are_solved(seed):
    """Measure a random polygon, derive constraints and start from disturbed points. A solution provably exists."""
    rng = random.Random(seed)
    n = rng.randint(3, 6)
    pts = [(math.cos(2 * math.pi * i / n) * 10 + rng.uniform(-1.5, 1.5), math.sin(2 * math.pi * i / n) * 10 + rng.uniform(-1.5, 1.5))
           for i in range(n)]
    truth = S.Builder()
    lines = truth.closed(pts)
    exact = truth.as_dict()
    v = S.Vars(exact)
    x = v.vector()
    for k in lines:
        kind = rng.choice(["length", "angle", "horizontal", "none"])
        if kind == "length":
            truth.constrain("length", [f"e{k}"], length(exact, k))
        elif kind == "angle":
            other = lines[(k + 1) % n]
            truth.constrain("angle", [f"e{k}", f"e{other}"], measured_angle(v, x, f"e{k}", f"e{other}"))
    disturbed = truth.as_dict()
    disturbed["points"] = [[p[0] + rng.uniform(-0.3, 0.3), p[1] + rng.uniform(-0.3, 0.3)] for p in disturbed["points"]]
    disturbed["constraints"] = [x for x in disturbed["constraints"] if x["type"] != "horizontal"]
    res = S.solve(disturbed)
    assert res.ok, res.errors
    assert all(e["residual"] < S.TOL_OK for e in res.constraints)
