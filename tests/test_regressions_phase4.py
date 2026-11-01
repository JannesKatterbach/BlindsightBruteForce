"""Regression tests for bugs found during the rework (version 0.4.0)."""

import math
from pathlib import Path

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
    # Every row used to be centred on its own. Neighbours were then only 0.9 x pitch apart
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
    # "enabled": "no" used to count as active
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
    p.stack.distances = [10.0, 11.0, 30.0]  # G1 and G2 are closer than the board thickness
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("überlappen" in e for e in exc.value.errors)


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
    assert any("außerhalb des Bereichs" in e for e in exc.value.errors)


def test_angle_list_has_no_duplicate_zero_and_360():
    p = Project()
    p.search.allowed_angles = [0.0, 90.0, 360.0, -90.0, 270.0]
    assert p.allowed_angle_list() == [0.0, 90.0, 270.0]
    p.search.allowed_angles = None
    p.search.angle_min, p.search.angle_max, p.search.angle_step = 0.0, 360.0, 90.0
    assert p.allowed_angle_list() == [0.0, 90.0, 180.0, 270.0]


def test_diagnose_probes_the_whole_center_distance_range():
    # Only the nominal centre distance fails. The diagnosis used to report "no single unit possible"
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
# Sketch
# ---------------------------------------------------------------------------
from blindsight import sketch as S  # noqa: E402
from blindsight.sketch import motor as sketch_motor  # noqa: E402


def _c(t, refs, value=None, enabled=True):
    return {"type": t, "refs": refs, "value": value, "at": None, "enabled": enabled, "name": "", "label": None}


def _square():
    b = S.Builder()
    b.closed([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    return b.as_dict()


def test_solver_ok_always_matches_errors_on_random_sketches():
    # The conflict diagnosis used to return ok=False without a message (residual not determined again)
    import random

    rng = random.Random(7)
    for _ in range(60):
        sk = _square()
        for _ in range(rng.randint(1, 5)):
            t = rng.choice(["length", "horizontal", "vertical", "parallel", "equal", "hdistance"])
            a, b = rng.sample(range(4), 2)
            refs = {"length": [f"e{a}"], "horizontal": [f"e{a}"], "vertical": [f"e{a}"], "parallel": [f"e{a}", f"e{b}"],
                    "equal": [f"e{a}", f"e{b}"], "hdistance": ["o", f"p{2 * a}"]}[t]
            sk["constraints"].append(_c(t, refs, rng.uniform(2, 15) if t in ("length", "hdistance") else None))
        res = S.solve(sk)
        assert res.ok == (not res.errors)
        if res.ok:
            assert all(e.get("residual", 0.0) < S.TOL_OK for e in res.constraints)


def test_rejected_drag_returns_the_unchanged_sketch():
    sk = _square()
    sk["constraints"] += [_c("length", ["e1"], 10.0), _c("length", ["e1"], 12.0)]
    res = S.solve(sk, drag={"ref": "p4", "target": [12.0, 12.0]})
    assert not res.ok and res.errors
    assert res.sketch["points"] == sk["points"]


def test_conflict_without_diagnosis_reports_an_error():
    sk = _square()
    sk["constraints"] += [_c("length", ["e0"], 10.0), _c("length", ["e0"], 12.0)]
    res = S.solve(sk, diagnose=False)
    assert not res.ok and res.errors
    assert res.sketch["points"] == sk["points"]


@pytest.mark.parametrize("bad", [{"points": 5, "entities": [], "constraints": []}, {"points": [], "entities": [], "constraints": 3},
                                 {"points": None}])
def test_solve_rejects_non_list_input_without_crash(bad):
    res = S.solve(bad)
    assert not res.ok and res.state == "invalid" and res.errors


def test_constraint_enabled_must_be_bool():
    sk = _square()
    sk["constraints"].append(_c("length", ["e0"], 10.0, enabled="no"))
    res = S.solve(sk)
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
    data = p.to_dict()
    data["motor"]["sketch"] = S.sketch_from_motor(p.motor)
    project = Project.from_dict(data)
    project.validate()
    Model(project)
    assert len(calls) == 1


def test_constraint_registry_matches_schema():
    assert set(S.CONSTRAINT_TYPES) == {t["name"] for t in S.constraint_schema()}
    for name, ctype in S.CONSTRAINT_TYPES.items():
        assert ctype.signatures, name
        assert ctype.value in (None, "len", "deg")


# ---------------------------------------------------------------------------
# Scoring and optimizers
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
    # The area bound used to give 0 for small regions although one rod fits
    p = Project()
    p.bounds.width = p.rod.diameter + 2 * p.bounds.edge_margin + 0.5
    p.bounds.height = p.rod.diameter + 2 * p.bounds.edge_margin + 0.5
    assert upper_bound_count(Model(p)) >= 1


def test_upper_bound_counts_rods_on_a_line():
    p = Project()
    d = p.rod.diameter + p.required_gap
    p.bounds.width = p.rod.diameter + 2 * p.bounds.edge_margin + 4 * d  # 5 rods in a row
    p.bounds.height = p.rod.diameter + 2 * p.bounds.edge_margin
    assert upper_bound_count(Model(p)) >= 5


def test_regularity_has_no_jump_between_one_and_few_units():
    # Used to be 1.0 for one unit and 0 for two to four units
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
    p.bounds.width = p.bounds.height = 100_000.0
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
    optimizer_options = set(META_BY_PATH["search.optimizer"].options)
    assert set(OPTIMIZERS) == optimizer_options
    assert set(OBJECTIVES) == {f.name for f in dataclasses.fields(WeightsSpec)}
    assert not OPTIMIZERS["exhaustive_small"].supports_parallel


# ---------------------------------------------------------------------------
# Server, import, export, service, CLI
# ---------------------------------------------------------------------------
import json  # noqa: E402

from blindsight import __version__  # noqa: E402
from blindsight.cli import main as cli_main  # noqa: E402
from blindsight.config import MotorSpec  # noqa: E402
from blindsight.export import EXPORTERS, SvgExporter, build_geometry  # noqa: E402
from blindsight.export.svg import _f  # noqa: E402
from blindsight.motor_import import SvgImportError, motor_from_svg, outline_from_svg  # noqa: E402
from blindsight.service import JobManager, JobNotFound  # noqa: E402
from blindsight.web.server import App, _url_host  # noqa: E402


def _strict_json(payload: bytes):
    def reject(name):
        raise AssertionError(f"ungueltiges JSON mit {name}")
    return json.loads(payload, parse_constant=reject)


def _post(app, path, obj=None, raw=None):
    body = raw if raw is not None else json.dumps(obj).encode()
    code, ctype, payload = app.handle("POST", path, {}, body)
    return code, _strict_json(payload)


SQUARE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="10" height="20"/></svg>'


@pytest.mark.parametrize("body", [
    {"svg": ["<svg/>"]}, {"svg": 5}, {"svg": SQUARE_SVG, "mm_per_unit": "abc"}, {"svg": SQUARE_SVG, "mm_per_unit": True},
    {"svg": SQUARE_SVG, "mm_per_unit": -1}, [],
])
def test_svg_import_rejects_bad_input_with_400(body):
    # The handler used to crash with lists, numbers and text as scale
    code, payload = _post(App(), "/api/svg-motor-import", body)
    assert code == 400 and payload["errors"] and payload["error"]


def test_svg_path_with_curves_is_rejected():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 0 C 12 5 12 15 10 20 L0 20 Z"/></svg>'
    with pytest.raises(SvgImportError, match="nicht unterstützt"):
        outline_from_svg(svg, 1.0)


def test_motor_from_svg_does_not_share_lists_with_base():
    base = MotorSpec(outline=[[0, 0], [1, 0], [0, 1]])
    spec = motor_from_svg(SQUARE_SVG, 8.0, 1.0, base)
    spec.outline.append([9, 9])
    assert base.outline == [[0, 0], [1, 0], [0, 1]]


@pytest.mark.parametrize("target", [None, "nan", "x", [1, None]])
def test_sketch_drag_with_bad_target_answers_valid_json(target):
    code, payload = _post(App(), "/api/sketch/solve", {"sketch": _square(), "drag": {"ref": "p0", "target": target}})
    # Earlier. float(None) crashed, "nan" produced invalid JSON with NaN
    assert code == 200
    assert payload["ok"] is False and payload["errors"]


def test_deeply_nested_json_is_a_400():
    code, payload = _post(App(), "/api/start", raw=b"[" * 200_000 + b"]" * 200_000)
    assert code == 400 and payload["errors"]


def test_origin_null_is_rejected():
    assert not App().host_ok("127.0.0.1:8765", "null")


def test_ipv6_hosts_are_compared_without_brackets():
    app = App({"fe80::1"})
    assert app.host_ok("[fe80::1]:8765", "http://[fe80::1]:8765")
    assert App().host_ok("[::1]:8765", None)
    assert _url_host("::1") == "[::1]" and _url_host("localhost") == "localhost"


def test_errors_have_one_form_and_internal_errors_are_500(monkeypatch):
    app = App()
    code, _, payload = app.handle("GET", "/api/nope", {}, b"")
    assert code == 404 and set(_strict_json(payload)) == {"error", "errors"}

    def boom(self, req):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(App, "default_project", boom)
    code, _, payload = app.handle("GET", "/api/default", {}, b"")
    assert code == 500 and "kaputt" in _strict_json(payload)["error"]


def test_export_of_unknown_job_has_no_attachment_header():
    response = App().dispatch("GET", "/api/export/zzz.svg", {}, b"")
    assert response.code == 404 and "Content-Disposition" not in response.headers


def test_placement_limit_is_checked_before_parsing():
    project = Project().to_dict()
    code, payload = _post(App(), "/api/validate", {"project": project, "placements": [{"bad": 1}] * 5001})
    assert code == 400 and "Zu viele" in payload["error"]


def test_static_javascript_has_fixed_type():
    code, ctype, _ = App().handle("GET", "/static/js/core/util.js", {}, b"")
    assert code == 200 and ctype == "text/javascript; charset=utf-8"


def test_schema_lists_constraint_types_and_exporters():
    code, _, payload = App().handle("GET", "/api/schema", {}, b"")
    data = _strict_json(payload)
    assert {e["name"] for e in data["exporters"]} == set(EXPORTERS)
    assert {c["name"] for c in data["sketch_constraints"]} == set(S.CONSTRAINT_TYPES)


def test_svg_distance_lines_are_drawn_once_per_pair():
    model = Model(Project())
    geo = build_geometry(model, [Placement(30, 60, 1, 0.0), Placement(90, 60, 2, 0.0)])
    svg = SvgExporter().export(geo)
    distances = svg.split('<g id="distances"', 1)[1].split("</g>", 1)[0]
    assert distances.count("<line") == 1
    assert _f(-0.00001) == "0" and _f(12.5) == "12.5" and _f(120.0) == "120"


def test_job_manager_reports_unknown_jobs_and_shuts_down():
    jm = JobManager()
    with pytest.raises(JobNotFound):
        jm.get("zzz")
    p = Project()
    p.search.time_limit_s = 60
    job = jm.start(p)
    jm.shutdown(timeout=30)
    assert not job.thread.is_alive()
    assert job.state == "cancelled"


def _cli_config(tmp_path, **search):
    p = Project()
    p.target_count = 2
    p.search.time_limit_s = 1
    for k, v in search.items():
        setattr(p.search, k, v)
    path = tmp_path / "cfg.json"
    path.write_text(p.to_json(), encoding="utf-8")
    return path


def test_cli_exit_codes(tmp_path):
    cfg = _cli_config(tmp_path)
    assert cli_main([str(cfg), "--time", "0", "--quiet"]) == 2  # used to be ignored silently
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe\x00")
    assert cli_main([str(bad), "--quiet"]) == 2
    assert cli_main([str(cfg), "--quiet", "--svg", str(tmp_path)]) == 3  # directory instead of a file
    assert cli_main([str(cfg), "--quiet", "--svg", str(tmp_path / "out.svg")]) == 0


def test_version_has_one_source():
    text = open(Path(__file__).resolve().parents[1] / "pyproject.toml", encoding="utf-8").read()
    assert 'dynamic = ["version"]' in text and "blindsight.__version__" in text
    assert __version__ == "0.8.0"
    assert 'blindsight = "blindsight.web.server:main"' in text
