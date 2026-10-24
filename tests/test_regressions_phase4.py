"""Regressionstests fuer Fehler, die bei der Ueberarbeitung (Version 0.4.0) gefunden wurden."""

import math

import pytest

from blindsight.config import ConfigError, Project
from blindsight.diagnose import single_unit_report
from blindsight.layout import Placement, layout_signature
from blindsight.model import Model, PlaneStack
from blindsight.patterns import estimated_point_count, pattern_points


def _nearest_neighbor_distances(points):
    out = []
    for i, (x, y) in enumerate(points):
        out.append(min(math.hypot(x - u, y - v) for j, (u, v) in enumerate(points) if j != i))
    return out


@pytest.mark.parametrize("kind", ["hex_x", "hex_y"])
def test_hex_lattice_neighbors_have_pitch_distance(kind):
    # Frueher wurde jede Reihe einzeln zentriert. Nachbarn lagen dann nur 0.9 x Teilung auseinander
    pts = pattern_points(kind, 10.0, (0.0, 0.0, 95.0, 87.0))
    assert len(pts) > 20
    for dist in _nearest_neighbor_distances(pts):
        assert dist == pytest.approx(10.0, abs=1e-9)


def test_estimated_point_count_is_close():
    region = (0.0, 0.0, 200.0, 150.0)
    for kind in ("square", "hex_x", "hex_y"):
        real = len(pattern_points(kind, 7.0, region))
        assert 0.8 * real <= estimated_point_count(kind, 7.0, region) <= 1.25 * real


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError):
        pattern_points("triangle", 5.0, (0.0, 0.0, 10.0, 10.0))


@pytest.mark.parametrize("value", ["no", 0, 1, None])
def test_bool_fields_are_type_checked(value):
    # Frueher galt "enabled": "no" als aktiv
    data = Project().to_dict()
    data["motor"]["sketch"] = {
        "points": [[-20, -10], [-2, -10], [-2, 10], [-20, 10]],
        "constraints": [{"type": "length", "a": 0, "value": 18.0, "enabled": value}],
    }
    with pytest.raises(ConfigError) as exc:
        Project.from_dict(data)
    assert any("true oder false" in e for e in exc.value.errors)


def test_overlapping_planes_fail_validation():
    p = Project()
    p.stack.mode = "distances"
    p.stack.distances = [10.0, 11.0, 30.0]  # G1 und G2 liegen naeher als die Plattendicke
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("ueberlappen" in e for e in exc.value.errors)


def test_unknown_stack_mode_is_reported():
    p = Project()
    p.stack.mode = "spiral"
    with pytest.raises(ConfigError):
        p.validate()
    with pytest.raises(ConfigError):
        p.stack.plane_tops()


def test_free_height_above_g0_is_infinite():
    stack = PlaneStack(Project())
    assert stack.free_height_above(0) == math.inf
    assert stack.free_height_above(1) > 0


def test_center_distance_min_without_max_is_an_error():
    p = Project()
    p.motor.center_distance_min = 4.0
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("zusammen" in e for e in exc.value.errors)


def test_nominal_center_distance_outside_range_is_an_error():
    p = Project()
    p.motor.center_distance = 5.0
    p.motor.center_distance_min = 6.0
    p.motor.center_distance_max = 8.0
    p.motor.center_distance_steps = 3
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("ausserhalb des Bereichs" in e for e in exc.value.errors)


def test_angle_list_has_no_duplicate_zero_and_360():
    p = Project()
    p.search.allowed_angles = [0.0, 90.0, 360.0, -90.0, 270.0]
    assert p.allowed_angle_list() == [0.0, 90.0, 270.0]
    p.search.allowed_angles = None
    p.search.angle_min, p.search.angle_max, p.search.angle_step = 0.0, 360.0, 90.0
    assert p.allowed_angle_list() == [0.0, 90.0, 180.0, 270.0]


def test_diagnose_probes_the_whole_center_distance_range():
    # Nur der nominale Achsabstand scheitert. Frueher meldete die Diagnose "keine Einzeleinheit moeglich"
    p = Project()
    p.motor.own_clearance = 6.0
    p.motor.center_distance = 5.0
    p.motor.center_distance_min = 5.0
    p.motor.center_distance_max = 15.0
    p.motor.center_distance_steps = 3
    model = Model(p)
    assert model.cd_problem(5.0)
    assert not model.cd_problem(15.0)
    assert single_unit_report(model) == []


def test_placement_rejects_negative_center_distance():
    with pytest.raises(ValueError):
        Placement.from_dict({"x": 1, "y": 2, "plane": 1, "angle": 0, "cd": -1}, 3)
    assert Placement.from_dict({"x": 1, "y": 2, "plane": 1, "angle": 0, "cd": None}, 3).cd is None


def test_layout_signature_distinguishes_center_distance():
    a = [Placement(1.0, 2.0, 1, 0.0, 5.0)]
    b = [Placement(1.0, 2.0, 1, 0.0, 6.0)]
    assert layout_signature(a) != layout_signature(b)
    assert layout_signature(a + b) == layout_signature(b + a)


def test_model_unit_bbox_matches_parts():
    model = Model(Project())
    parts = model.unit_parts(0, 50.0, 40.0, 1, 30.0)
    xs = [x for p in parts for x, _ in p.prism.fp.outline()]
    box = model.unit_bbox(50.0, 40.0, 1, 30.0)
    assert box[0] == pytest.approx(min(xs), abs=0.05)
    assert box[2] == pytest.approx(max(xs), abs=0.05)


# ---------------------------------------------------------------------------
# Skizze
# ---------------------------------------------------------------------------
from blindsight import sketch as S  # noqa: E402
from blindsight.sketch import motor as sketch_motor  # noqa: E402


def _c(t, a=None, b=None, value=None, value2=None, ref="rod", enabled=True):
    return {"type": t, "a": a, "b": b, "value": value, "value2": value2, "ref": ref, "enabled": enabled, "name": ""}


SQUARE = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]


def test_solver_ok_always_matches_errors_on_random_sketches():
    # Frueher lieferte die Konfliktdiagnose ok=False ohne Fehlermeldung (Residuum nicht neu bestimmt)
    import random

    rng = random.Random(7)
    for _ in range(80):
        n = rng.randint(3, 6)
        pts = [[math.cos(2 * math.pi * i / n) * 10 + rng.uniform(-1, 1), math.sin(2 * math.pi * i / n) * 10
                + rng.uniform(-1, 1)] for i in range(n)]
        cons = []
        for _ in range(rng.randint(1, 5)):
            t = rng.choice(["length", "horizontal", "vertical", "parallel", "equal", "coord_x"])
            a = rng.randrange(n)
            b = (a + rng.randint(1, n - 1)) % n
            cons.append(_c(t, a, b, value=rng.uniform(2, 15)))
        res = S.solve({"points": pts, "constraints": cons})
        assert res.ok == (not res.errors)
        if res.ok:
            assert all(e.get("residual", 0.0) < S.TOL_OK for e in res.constraints)


def test_drag_on_clockwise_sketch_moves_the_dragged_point():
    clockwise = list(reversed(SQUARE))  # Punkt 0 ist (0, 10)
    res = S.solve({"points": clockwise, "constraints": []}, drag={"point": 0, "target": [-3.0, 13.0]})
    assert res.ok and res.reoriented
    assert [-3.0, 13.0] in [[round(x, 6), round(y, 6)] for x, y in res.sketch["points"]]
    assert [0.0, 10.0] not in [[round(x, 6), round(y, 6)] for x, y in res.sketch["points"]]


def test_rejected_drag_returns_the_unchanged_sketch():
    # Punkt 0 liegt auf der Stange, die Startlage wird intern leicht verschoben. Der Widerspruch
    # erzwingt die Ablehnung. Frueher kam die verschobene Startlage zurueck
    pts = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    cons = [_c("dist_point", 0, value=0.0), _c("length", 1, value=10.0), _c("length", 1, value=12.0)]
    res = S.solve({"points": pts, "constraints": cons}, drag={"point": 2, "target": [12.0, 12.0]})
    assert not res.ok and res.errors
    assert res.sketch["points"] == pts


def test_conflict_without_diagnosis_reports_an_error():
    cons = [_c("length", 0, value=10.0), _c("length", 0, value=12.0)]
    res = S.solve({"points": SQUARE, "constraints": cons}, diagnose=False)
    assert not res.ok and res.errors
    assert res.sketch["points"] == SQUARE


def test_self_intersection_is_always_reported():
    star = [[math.cos(math.radians(90 + 144 * i)) * 10, math.sin(math.radians(90 + 144 * i)) * 10] for i in range(5)]
    report = S.polygon_report(star)
    assert not report["simple"]
    assert any("schneidet sich selbst" in p for p in report["problems"])


@pytest.mark.parametrize("bad", [{"points": 5, "constraints": []}, {"points": [], "constraints": 3}, {"points": None}])
def test_solve_rejects_non_list_input_without_crash(bad):
    res = S.solve(bad)
    assert not res.ok and res.state == "invalid" and res.errors


@pytest.mark.parametrize("t", [float("nan"), 0.0, 1.0, -0.5, 1.5, "0.5"])
def test_insert_point_checks_parameter(t):
    with pytest.raises(S.SketchError):
        S.insert_point({"points": SQUARE, "constraints": []}, 0, t)


def test_constraint_enabled_must_be_bool():
    res = S.solve({"points": SQUARE, "constraints": [_c("length", 0, value=10.0, enabled="no")]})
    assert not res.ok and any("enabled" in e for e in res.errors)


def test_motor_sketch_is_solved_once(monkeypatch):
    calls = []
    original = sketch_motor.solve

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(sketch_motor, "solve", counting)
    sketch_motor._motor_cache.clear()
    p = Project()
    p.motor.sketch = S.legacy_to_sketch(p.motor)
    data = p.to_dict()
    data["motor"]["sketch"] = S.legacy_to_sketch(p.motor)
    project = Project.from_dict(data)
    project.validate()
    Model(project)
    assert len(calls) == 1


def test_constraint_registry_matches_spec_and_schema():
    assert set(S.SPEC) == set(S.CONSTRAINT_TYPES) == {t["name"] for t in S.constraint_schema()}
    for name, ctype in S.CONSTRAINT_TYPES.items():
        assert ctype.index_fields, name
        assert ctype.value in (None, "len", "deg")


# ---------------------------------------------------------------------------
# Bewertung und Optimierer
# ---------------------------------------------------------------------------
import dataclasses  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402

from blindsight.config import META_BY_PATH, WeightsSpec  # noqa: E402
from blindsight.layout import Counter  # noqa: E402
from blindsight.optimizers import OPTIMIZERS  # noqa: E402
from blindsight.optimizers.base import OptimizationResult, Solution, StopToken, describe_result  # noqa: E402
from blindsight.optimizers.common import SearchBase  # noqa: E402
from blindsight.optimizers.exhaustive_small import windows_by_size  # noqa: E402
from blindsight.optimizers.parallel import _combined_status, _jobs  # noqa: E402
from blindsight.optimizers.pattern_greedy import MAX_PATTERN_POINTS, PatternSearch  # noqa: E402
from blindsight.scoring import OBJECTIVES, evaluate, upper_bound_count  # noqa: E402


def test_upper_bound_is_at_least_one_when_a_single_rod_fits():
    # Frueher ergab die Flaechenschranke fuer kleine Bereiche 0, obwohl eine Stange passt
    p = Project()
    p.bounds.xmax = p.bounds.xmin + p.rod.diameter + 2 * p.bounds.edge_margin + 0.5
    p.bounds.ymax = p.bounds.ymin + p.rod.diameter + 2 * p.bounds.edge_margin + 0.5
    assert upper_bound_count(Model(p)) >= 1


def test_upper_bound_counts_rods_on_a_line():
    p = Project()
    d = p.rod.diameter + p.required_gap
    p.bounds.xmax = p.bounds.xmin + p.rod.diameter + 2 * p.bounds.edge_margin + 4 * d  # 5 Stangen in einer Reihe
    p.bounds.ymax = p.bounds.ymin + p.rod.diameter + 2 * p.bounds.edge_margin
    assert upper_bound_count(Model(p)) >= 5


def test_regularity_has_no_jump_between_one_and_few_units():
    # Frueher 1.0 fuer eine Einheit und 0 fuer zwei bis vier Einheiten
    model = Model(Project())
    weights = WeightsSpec()
    one = evaluate(model, [Placement(60, 60, 1, 0.0)], weights, 4)
    few = evaluate(model, [Placement(30 + 30 * i, 60, 1, 0.0) for i in range(3)], weights, 4)
    assert one.terms["regularity"] == few.terms["regularity"] == 0.0


def test_result_note_uses_the_largest_count_found():
    model = Model(Project())
    weights = WeightsSpec()
    four = [Placement(30 + 20 * i, 60, 1, 0.0) for i in range(4)]
    six = [Placement(20 + 15 * i, 60, 1, 0.0) for i in range(6)]
    res = OptimizationResult(target=6, upper_bound=50)
    res.solutions = [Solution(four, evaluate(model, four, weights, 6)), Solution(six, evaluate(model, six, weights, 6))]
    describe_result(res)
    assert not any("Nur" in m for m in res.messages)
    assert "Zielanzahl 6 erreicht" in res.optimality_note
    assert any("bestbewertete Anordnung hat 4" in m for m in res.messages)


def test_stagnation_waits_for_the_best_rated_solution_to_reach_the_target():
    model = Model(Project())
    model.project.search.stagnation_s = 0.0
    counter = Counter()
    search = SearchBase(model, counter, StopToken(60, 10**9, counter), random.Random(1))
    search.max_count, search.best_count = search.target, search.target - 1
    assert not search.stagnated()
    search.best_count = search.target
    assert search.stagnated()


def test_pattern_points_are_limited_before_generation():
    p = Project()
    p.bounds.xmax = p.bounds.ymax = 100_000.0
    p.search.layout_goal = "spread"
    model = Model(p)
    counter = Counter()
    search = PatternSearch(model, counter, StopToken(60, 10**9, counter), random.Random(1))
    t0 = time.monotonic()
    points = search._points("square", 5.0)
    assert 0 < len(points) <= MAX_PATTERN_POINTS
    assert time.monotonic() - t0 < 10.0


def test_window_generator_matches_sorted_list_and_is_lazy():
    nx, ny, target = 6, 4, 5
    expected = sorted((w * h, w, h) for w in range(1, nx + 1) for h in range(1, ny + 1) if w * h >= target)
    assert list(windows_by_size(nx, ny, target)) == expected
    t0 = time.monotonic()
    assert next(windows_by_size(10**6, 10**6, 7)) == (7, 1, 7)
    assert time.monotonic() - t0 < 1.0


def test_parallel_seeds_stay_valid_and_status_survives():
    p = Project()
    p.search.seed = 2**31 - 1
    p.search.workers = 3
    seeds = [job["search"]["seed"] for job in _jobs(p)]
    assert seeds == [2**31 - 1, 0, 1]
    counter = Counter()
    assert _combined_status(StopToken(60, 10**9, counter), ["completed", "stagnation"]) == "stagnation"
    assert _combined_status(StopToken(60, 10**9, counter), ["completed"]) == "completed"


def test_registries_match_configuration_options():
    optimizer_options = {value for value, _ in META_BY_PATH["search.optimizer"].options}
    assert set(OPTIMIZERS) == optimizer_options
    assert set(OBJECTIVES) == {f.name for f in dataclasses.fields(WeightsSpec)}
    assert not OPTIMIZERS["exhaustive_small"].supports_parallel
