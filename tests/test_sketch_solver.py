"""Solver der Motor Skizze. Alle Pruefungen messen das Ergebnis unabhaengig vom Solver nach."""

import math
import random

import pytest
from blindsight import sketch as S


def C(t, a=None, b=None, value=None, value2=None, ref="rod", enabled=True, name=""):
    return {"type": t, "a": a, "b": b, "value": value, "value2": value2, "ref": ref, "enabled": enabled, "name": name}


def side(pts, i):
    n = len(pts)
    return pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]


def length(pts, i):
    return math.hypot(*side(pts, i))


def interior(pts, i):
    n = len(pts)
    p, q, r = pts[i - 1], pts[i], pts[(i + 1) % n]
    a, b = (p[0] - q[0], p[1] - q[1]), (r[0] - q[0], r[1] - q[1])
    ang = math.degrees(math.atan2(b[0] * a[1] - b[1] * a[0], a[0] * b[0] + a[1] * b[1]))
    return ang % 360.0


def cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


RECT = [[-14, -20], [10, -20], [10, 2], [-14, 2]]
TRAP = [[0, 0], [20, 0], [16, 9], [3, 8]]
PENT = [[1, 1], [10, 0], [14, 7], [6, 13], [-3, 7]]


def run(points, cons, **kw):
    r = S.solve({"points": points, "constraints": cons}, **kw)
    return r


# ---- einzelne Constraint Typen -------------------------------------------------------------
def test_length():
    r = run(RECT, [C("length", 0, value=30.0)])
    assert r.ok and math.isclose(length(r.sketch["points"], 0), 30.0, abs_tol=1e-8)


def test_angle_adjacent():
    r = run(TRAP, [C("angle", 1, value=75.0)])
    assert r.ok and math.isclose(interior(r.sketch["points"], 1), 75.0, abs_tol=1e-6)


def test_angle_sides_any_two():
    r = run(TRAP, [C("angle_sides", 0, 2, value=20.0)])
    p = r.sketch["points"]
    a, b = side(p, 0), side(p, 2)
    ang = math.degrees(math.atan2(abs(cross(a, b)), a[0] * b[0] + a[1] * b[1]))
    assert r.ok and math.isclose(ang, 20.0, abs_tol=1e-6)


def test_parallel():
    r = run(TRAP, [C("parallel", 1, 3)])
    p = r.sketch["points"]
    a, b = side(p, 1), side(p, 3)
    assert r.ok and abs(cross(a, b)) / (math.hypot(*a) * math.hypot(*b)) < 1e-8


def test_parallel_trapezoid_opposite_sides():
    """Trapez. Seiten 0 und 2 parallel, Laengen und Winkel gesetzt."""
    r = run(TRAP, [C("parallel", 0, 2), C("length", 0, value=20.0), C("length", 2, value=12.0), C("angle", 0, value=80.0), C("angle", 1, value=80.0)])
    p = r.sketch["points"]
    assert r.ok
    assert abs(cross(side(p, 0), side(p, 2))) < 1e-7
    assert math.isclose(length(p, 2), 12.0, abs_tol=1e-7)
    assert math.isclose(interior(p, 0), 80.0, abs_tol=1e-6) and math.isclose(interior(p, 1), 80.0, abs_tol=1e-6)
    assert r.convex


def test_perpendicular_equal():
    r = run(TRAP, [C("perpendicular", 0, 3), C("equal", 0, 1)])
    p = r.sketch["points"]
    assert r.ok
    a, b = side(p, 0), side(p, 3)
    assert abs(a[0] * b[0] + a[1] * b[1]) < 1e-6
    assert math.isclose(length(p, 0), length(p, 1), abs_tol=1e-7)


def test_horizontal_vertical():
    r = run(TRAP, [C("horizontal", 0), C("vertical", 3)])
    p = r.sketch["points"]
    assert r.ok and abs(side(p, 0)[1]) < 1e-8 and abs(side(p, 3)[0]) < 1e-8


def test_fix_and_coords():
    r = run(TRAP, [C("fix", 0, value=-3.0, value2=-4.0), C("coord_x", 1, value=17.0), C("coord_y", 2, value=11.0)])
    p = r.sketch["points"]
    assert r.ok and p[0] == pytest.approx([-3.0, -4.0], abs=1e-8) and p[1][0] == pytest.approx(17.0, abs=1e-8) and p[2][1] == pytest.approx(11.0, abs=1e-8)


def test_distance_to_rod_and_gear():
    r = run(PENT, [C("dist_point", 0, value=12.0, ref="rod"), C("dist_point", 1, value=15.0, ref="gear")], cd=6.0)
    p = r.sketch["points"]
    assert r.ok
    assert math.isclose(math.hypot(*p[0]), 12.0, abs_tol=1e-7)
    assert math.isclose(math.hypot(p[1][0] + 6.0, p[1][1]), 15.0, abs_tol=1e-7)


def test_distance_side_to_rod_keeps_side_of_line():
    """Rechteck rechts neben der Stange. Seite 3 (links) soll 4 mm von der Stange entfernt sein."""
    box = [[4, -10], [16, -10], [16, 10], [4, 10]]
    r = run(box, [C("dist_side", 3, value=7.0, ref="rod")])
    p = r.sketch["points"]
    # Lotabstand der Geraden durch Seite 3 zum Ursprung
    d = side(p, 3)
    dist = abs(cross(d, (0 - p[3][0], 0 - p[3][1]))) / math.hypot(*d)
    assert r.ok and math.isclose(dist, 7.0, abs_tol=1e-7)
    assert p[3][0] > 0 and p[0][0] > 0  # Die Seite bleibt rechts der Stange


# ---- Reihenfolge, Orientierung --------------------------------------------------------------
def test_clockwise_input_is_reoriented_with_constraints_remapped():
    cw = [list(reversed(RECT))[i] for i in range(4)]
    n = 4
    # Constraint auf die Seite, die in CCW "Seite 0" waere. In CW Reihenfolge ist es Seite n-2-0 = 2
    r = run(cw, [C("length", 2, value=31.0)])
    p = r.sketch["points"]
    assert r.reoriented and r.ok
    assert S.signed_area(p) > 0
    assert math.isclose(length(p, 0), 31.0, abs_tol=1e-7)


# ---- Freiheitsgrade, Redundanz, Widerspruch ----------------------------------------------------
def test_dof_counting():
    r = run(RECT, [])
    assert r.dof == 8 and r.state == "under"
    r = run(RECT, [C("fix", i, value=RECT[i][0], value2=RECT[i][1]) for i in range(4)])
    assert r.dof == 0 and r.state == "full"
    r = run(RECT, [C("length", 0, value=24.0), C("length", 1, value=22.0)])
    assert r.dof == 6


def test_fully_defined_rectangle_with_dimensions():
    cons = [C("horizontal", 0), C("length", 0, value=12.0), C("length", 1, value=24.0), C("angle", 1, value=90.0),
            C("parallel", 0, 2), C("parallel", 1, 3), C("fix", 0, value=-6.0, value2=-20.0)]
    r = run([[-6.5, -19], [6, -20.5], [5.5, 4], [-7, 4.5]], cons)
    assert r.ok and r.state == "full" and r.dof == 0
    p = r.sketch["points"]
    assert p[1] == pytest.approx([6.0, -20.0], abs=1e-6) and p[2] == pytest.approx([6.0, 4.0], abs=1e-6) and p[3] == pytest.approx([-6.0, 4.0], abs=1e-6)


def test_redundant_constraint_marked_not_failing():
    cons = [C("angle", 0, value=90.0), C("angle", 1, value=90.0), C("angle", 2, value=90.0), C("angle", 3, value=90.0)]
    r = run(RECT, cons)
    assert r.ok and r.state == "over"
    assert [c["status"] for c in r.constraints].count("redundant") >= 1


def test_duplicate_constraint_is_redundant():
    r = run(RECT, [C("length", 0, value=20.0), C("length", 0, value=20.0)])
    assert r.ok and r.constraints[1]["status"] == "redundant"


def test_conflict_names_the_first_offending_constraint():
    cons = [C("length", 0, value=20.0), C("parallel", 0, 2), C("length", 0, value=7.0)]
    r = run(TRAP, cons)
    assert not r.ok and r.state == "conflict"
    assert r.constraints[2]["status"] == "conflict" and r.constraints[0]["status"] == "ok"
    assert "Nr. 3" in r.errors[0]
    # Rueckgabe ist die letzte widerspruchsfreie Loesung
    assert math.isclose(length(r.sketch["points"], 0), 20.0, abs_tol=1e-6)


def test_conflicting_angles_in_triangle():
    tri = [[0, 0], [10, 0], [4, 8]]
    r = run(tri, [C("angle", 0, value=100.0), C("angle", 1, value=100.0)])
    assert not r.ok and r.state == "conflict"


def test_disabled_constraint_is_ignored():
    r = run(RECT, [C("length", 0, value=3.0, enabled=False)])
    assert r.ok and r.constraints[0]["status"] == "disabled" and math.isclose(length(r.sketch["points"], 0), 24.0)


# ---- Ziehen --------------------------------------------------------------------------------
def test_drag_free_vertex_follows_target():
    r = run(RECT, [], drag={"point": 2, "target": [20.0, 10.0]})
    assert r.ok and r.sketch["points"][2] == pytest.approx([20.0, 10.0], abs=1e-6)


def test_drag_keeps_constraints():
    cons = [C("parallel", 0, 2), C("parallel", 1, 3), C("angle", 1, value=90.0), C("length", 0, value=24.0)]
    r = run(RECT, cons, drag={"point": 2, "target": [30.0, 15.0]})
    p = r.sketch["points"]
    assert r.ok
    assert abs(cross(side(p, 0), side(p, 2))) < 1e-6 * length(p, 0) * length(p, 2)
    assert math.isclose(interior(p, 1), 90.0, abs_tol=1e-5)
    assert math.isclose(length(p, 0), 24.0, abs_tol=1e-6)
    # Das Rechteck wurde in y verlaengert (Zielpunkt liegt oberhalb), die Breite blieb
    assert p[2][1] > 2.0


def test_drag_fully_defined_does_not_move():
    cons = [C("fix", i, value=RECT[i][0], value2=RECT[i][1]) for i in range(4)]
    r = run(RECT, cons, drag={"point": 1, "target": [50.0, 50.0]})
    assert r.ok and r.sketch["points"][1] == pytest.approx(RECT[1], abs=1e-6)


def test_drag_rejects_bad_arguments():
    assert not run(RECT, [], drag={"point": 9, "target": [1, 1]}).ok
    assert not run(RECT, [], drag={"point": 1, "target": ["a", 1]}).ok
    assert not run(RECT, [], drag={"target": [1, 1]}).ok


# ---- Struktur und Randfaelle --------------------------------------------------------------------
@pytest.mark.parametrize("points", [[[0, 0], [1, 0]], [[0, 0]] * 3, [[0, 0], [1, 0], [float("nan"), 1]], [[0, 0], [1, 0], [float("inf"), 1]], [[0, 0], [1], [2, 2]], [[0, 0], ["a", 0], [1, 1]]])
def test_bad_points_are_reported(points):
    r = run(points, [])
    assert not r.ok and r.errors


def test_too_many_points():
    pts = [[math.cos(2 * math.pi * i / 41) * 10, math.sin(2 * math.pi * i / 41) * 10] for i in range(41)]
    assert not run(pts, []).ok
    assert run(pts[:40], []).ok


@pytest.mark.parametrize("bad", [
    C("nope", 0), C("length", 9, value=1.0), C("length", -1, value=1.0), C("length", 0), C("length", 0, value=0.0), C("length", 0, value=float("nan")),
    C("angle", 0, value=0.0), C("angle", 0, value=180.0), C("angle", 0, value=-5.0), C("parallel", 0, 0), C("parallel", 0), C("fix", 0, value=1.0),
    C("dist_point", 0, value=-1.0), C("dist_point", 0, value=1.0, ref="moon"), C("length", True, value=1.0), C("length", 0.5, value=1.0),
])
def test_bad_constraints_are_reported(bad):
    r = run(RECT, [bad])
    assert not r.ok and r.errors
    assert "constraints[0]" in r.errors[0]


def test_degenerate_polygon_flagged_not_crashing():
    sq = [[0, 0], [10, 0], [10, 0], [0, 10]]
    r = run(sq, [])
    assert r.warnings and not r.convex


def test_point_on_reference_can_still_be_dimensioned():
    tri = [[0, 0], [10, 0], [5, 8]]
    r = run(tri, [C("dist_point", 0, value=4.0, ref="rod")])
    assert r.ok and math.isclose(math.hypot(*r.sketch["points"][0]), 4.0, abs_tol=1e-7)


def test_nonconvex_detected():
    dart = [[0, 0], [10, 0], [3, 3], [0, 10]]
    r = run(dart, [])
    assert r.ok and not r.convex and r.warnings


def test_self_intersection_detected():
    bow = [[0, 0], [10, 10], [10, 0], [0, 10]]
    rep = S.polygon_report(S.normalize_orientation({"points": bow, "constraints": []})[0]["points"])
    assert not rep["simple"]


def test_determinism():
    cons = [C("parallel", 0, 2), C("angle", 0, value=77.0), C("length", 1, value=11.0)]
    a = run(TRAP, cons).sketch["points"]
    b = run(TRAP, cons).sketch["points"]
    assert a == b


def test_solver_is_fast_enough_for_dragging():
    import time

    pts = [[10 * math.cos(2 * math.pi * i / 12), 10 * math.sin(2 * math.pi * i / 12)] for i in range(12)]
    cons = [C("length", i, value=length(pts, i)) for i in range(0, 12, 2)] + [C("parallel", 0, 6)]
    t = time.time()
    for _ in range(10):
        run(pts, cons, drag={"point": 3, "target": [12.0, 5.0]})
    assert (time.time() - t) / 10 < 0.25


# ---- Index Umrechnung ----------------------------------------------------------------------------
def base_sketch():
    return {"points": [list(p) for p in PENT], "constraints": [C("length", 0, value=10.0), C("angle", 2, value=100.0), C("parallel", 1, 3), C("fix", 4, value=-3.0, value2=7.0), C("equal", 0, 2)]}


def test_insert_point_shifts_indices():
    sk = S.insert_point(base_sketch(), 1)
    assert len(sk["points"]) == 6
    types = [(c["type"], c["a"], c["b"]) for c in sk["constraints"]]
    assert ("length", 0, None) in types  # Seite 0 unveraendert
    assert ("angle", 3, None) in types  # Punkt 2 wurde Punkt 3
    assert ("fix", 5, None) in types
    # parallel(1,3) bezieht sich auf die Gerade der Seite 1. Beide Haelften (1 und 2) werden an Seite 4 gebunden
    assert ("parallel", 1, 4) in types and ("parallel", 2, 4) in types
    # equal(0,2) wird zu equal(0,3)
    assert ("equal", 0, 3) in types
    assert S.solve(sk).ok


def test_insert_point_drops_length_of_split_side():
    sk = S.insert_point(base_sketch(), 0)
    assert not [c for c in sk["constraints"] if c["type"] == "length"]


def test_delete_point_drops_dependent_constraints():
    sk = S.delete_point(base_sketch(), 2)
    assert len(sk["points"]) == 4
    types = [c["type"] for c in sk["constraints"]]
    assert "angle" not in types  # Punkt 2 entfernt
    assert "parallel" not in types  # Seite 1 und 2 verschmolzen, Seite 3 bleibt, aber Seite 1 entfaellt
    assert "length" in types
    assert S.solve(sk).ok


def test_delete_point_limits():
    sk = {"points": [[0, 0], [1, 0], [0, 1]], "constraints": []}
    with pytest.raises(S.SketchError):
        S.delete_point(sk, 0)
    with pytest.raises(S.SketchError):
        S.delete_point(base_sketch(), 99)


def test_hull_drops_inner_points():
    sk = {"points": [[0, 0], [10, 0], [3, 3], [0, 10]], "constraints": [C("length", 0, value=10.0), C("angle", 2, value=100.0)]}
    h = S.hull_sketch(sk)
    assert len(h["points"]) == 3
    assert [c["type"] for c in h["constraints"]] == ["length"]
    assert S.polygon_report(h["points"])["convex"]


# ---- Zufallspruefung ------------------------------------------------------------------------------
def random_convex(rng, n):
    angs = sorted(rng.uniform(0, 2 * math.pi) for _ in range(n))
    for _ in range(50):
        if all((angs[(i + 1) % n] - angs[i]) % (2 * math.pi) > 0.35 for i in range(n)):
            break
        angs = sorted(rng.uniform(0, 2 * math.pi) for _ in range(n))
    return [[math.cos(a) * rng.uniform(8, 15) + rng.uniform(-1, 1), math.sin(a) * rng.uniform(8, 15)] for a in angs]


def test_random_constraints_derived_from_a_real_polygon_are_always_satisfiable():
    """Misst ein zufaelliges Polygon, leitet daraus Constraints ab und startet mit gestoerten Punkten.
    Der Solver muss alle Constraints erfuellen (es existiert nachweislich eine Loesung)."""
    rng = random.Random(1234)
    solved = 0
    for _ in range(60):
        n = rng.randint(3, 7)
        true = random_convex(rng, n)
        if S.signed_area(true) <= 0 or not S.polygon_report(true)["convex"]:
            continue
        cons = []
        for i in rng.sample(range(n), rng.randint(1, n)):
            cons.append(C("length", i, value=length(true, i)))
        for i in rng.sample(range(n), rng.randint(0, n)):
            cons.append(C("angle", i, value=interior(true, i)))
        cons.append(C("fix", 0, value=true[0][0], value2=true[0][1]))
        start = [[x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4)] for x, y in true]
        r = run(start, cons)
        if not r.ok:
            continue  # sehr selten, schlechte Startlage. Wird unten gezaehlt
        p = r.sketch["points"]
        for c in cons:
            if c["type"] == "length":
                assert math.isclose(length(p, c["a"]), c["value"], abs_tol=1e-6)
            elif c["type"] == "angle":
                assert math.isclose(interior(p, c["a"]), c["value"], abs_tol=1e-5)
            else:
                assert p[0] == pytest.approx([c["value"], c["value2"]], abs=1e-6)
        solved += 1
    assert solved >= 40


def test_random_parallel_and_perpendicular_relations():
    rng = random.Random(99)
    for _ in range(30):
        n = rng.choice([4, 6])
        true = random_convex(rng, n)
        if not S.polygon_report(true)["convex"]:
            continue
        i, j = rng.sample(range(n), 2)
        a, b = side(true, i), side(true, j)
        cons = [C("angle_sides", i, j, value=math.degrees(math.atan2(abs(cross(a, b)), a[0] * b[0] + a[1] * b[1])))]
        r = run([[x + 0.2, y - 0.1] for x, y in true], cons)
        assert r.ok


def test_solver_moves_points_minimally():
    """Eine kleine Aenderung der Laenge darf die Kontur nur wenig verschieben."""
    r = run(RECT, [C("length", 0, value=25.0)])
    moved = max(math.dist(a, b) for a, b in zip(RECT, r.sketch["points"]))
    assert r.ok and moved < 1.01


def test_time_limit_returns_error_instead_of_hanging():
    cons = [C("length", i % 4, value=20.0 + i * 0.01) for i in range(120)]
    r = S.solve({"points": RECT, "constraints": cons}, time_limit=0.05)
    assert not r.ok and r.errors


# ---- Fuzz mit unabhaengiger Pruefung aller Constraint Typen -------------------------------------------------
def satisfied(p, c, cd):
    """Misst einen Constraint ohne den Solver (eigene Formeln). Rueckgabe Abweichung."""
    t, a, b, v, v2 = c["type"], c["a"], c["b"], c["value"], c["value2"]
    ref = (0.0, 0.0) if c["ref"] == "rod" else (-cd, 0.0)
    if t == "length":
        return abs(length(p, a) - v)
    if t == "angle":
        d = abs(interior(p, a) - v)
        return min(d, 360 - d) * math.pi / 180
    if t == "angle_sides":
        u, w = side(p, a), side(p, b)
        ang = math.degrees(math.atan2(abs(cross(u, w)), u[0] * w[0] + u[1] * w[1]))
        return abs(ang - v) * math.pi / 180
    if t == "parallel":
        u, w = side(p, a), side(p, b)
        return abs(cross(u, w)) / (math.hypot(*u) * math.hypot(*w))
    if t == "perpendicular":
        u, w = side(p, a), side(p, b)
        return abs(u[0] * w[0] + u[1] * w[1]) / (math.hypot(*u) * math.hypot(*w))
    if t == "equal":
        return abs(length(p, a) - length(p, b))
    if t == "horizontal":
        return abs(side(p, a)[1])
    if t == "vertical":
        return abs(side(p, a)[0])
    if t == "fix":
        return max(abs(p[a][0] - v), abs(p[a][1] - v2))
    if t == "coord_x":
        return abs(p[a][0] - v)
    if t == "coord_y":
        return abs(p[a][1] - v)
    if t == "dist_point":
        return abs(math.hypot(p[a][0] - ref[0], p[a][1] - ref[1]) - v)
    if t == "dist_side":
        d = side(p, a)
        return abs(abs(cross(d, (ref[0] - p[a][0], ref[1] - p[a][1])) / math.hypot(*d)) - v)
    raise AssertionError(t)


def random_constraint(rng, n, true):
    t = rng.choice(list(S.SPEC))
    sides, verts, nv, nv2 = S.SPEC[t]
    c = C(t)
    if len(sides) == 2:
        c["a"], c["b"] = rng.sample(range(n), 2)
    elif sides:
        c["a"] = rng.randrange(n)
    else:
        c["a"] = rng.randrange(n)
    c["ref"] = rng.choice(["rod", "gear"])
    return c


def test_fuzz_random_constraint_sets_never_crash_and_ok_results_are_correct():
    import time

    rng = random.Random(2025)
    ok_count = conflict_count = 0
    t0 = time.time()
    for _ in range(120):
        n = rng.randint(3, 8)
        true = random_convex(rng, n)
        if S.signed_area(true) <= 0 or not S.polygon_report(true)["convex"]:
            continue
        cons = []
        for _ in range(rng.randint(0, 6)):
            c = random_constraint(rng, n, true)
            # Wert aus dem echten Polygon messen (meist erfuellbar), manchmal absichtlich verfaelscht
            mm = S.measures(true)
            t = c["type"]
            if t == "length":
                c["value"] = mm["sides"][c["a"]]
            elif t == "angle":
                c["value"] = mm["angles"][c["a"]]
            elif t == "angle_sides":
                u, w = side(true, c["a"]), side(true, c["b"])
                c["value"] = math.degrees(math.atan2(abs(cross(u, w)), u[0] * w[0] + u[1] * w[1]))
            elif t == "fix":
                c["value"], c["value2"] = true[c["a"]]
            elif t in ("coord_x", "coord_y"):
                c["value"] = true[c["a"]][0 if t == "coord_x" else 1]
            elif t == "dist_point":
                r = (0, 0) if c["ref"] == "rod" else (-5.0, 0)
                c["value"] = math.hypot(true[c["a"]][0] - r[0], true[c["a"]][1] - r[1])
            elif t == "dist_side":
                r = (0, 0) if c["ref"] == "rod" else (-5.0, 0)
                d = side(true, c["a"])
                c["value"] = abs(cross(d, (r[0] - true[c["a"]][0], r[1] - true[c["a"]][1]))) / math.hypot(*d)
            if rng.random() < 0.15 and c["value"] is not None:
                c["value"] = abs(c["value"]) * rng.uniform(0.3, 2.0) + 0.5
                if t == "angle":
                    c["value"] = min(c["value"], 170.0)
            cons.append(c)
        start = [[x + rng.uniform(-0.3, 0.3), y + rng.uniform(-0.3, 0.3)] for x, y in true]
        r = S.solve({"points": start, "constraints": cons}, cd=5.0)
        assert r.state in ("under", "full", "over", "conflict", "invalid")
        assert len(r.constraints) == len(cons)
        if r.ok:
            ok_count += 1
            p = r.sketch["points"]
            for c in r.sketch["constraints"]:
                assert satisfied(p, c, 5.0) < 1e-5, (c, p)
            assert 0 <= r.dof <= 2 * n
        elif r.state == "conflict":
            conflict_count += 1
            assert r.errors and any(c["status"] == "conflict" for c in r.constraints)
    assert ok_count > 40
    assert time.time() - t0 < 60
