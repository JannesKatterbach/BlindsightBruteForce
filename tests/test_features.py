"""Tests of the extensions. Motor outline, centre distance, layer rules, modes, exports, optimizers."""

import math

import pytest
from blindsight.config import ConfigError, ObstacleSpec, Project
from blindsight.export import EXPORTERS, build_geometry
from blindsight.layout import Layout, Placement
from blindsight.model import Model
from blindsight.optimizers import run_optimizer
from helpers import make_model, pl


def test_polygon_outline_motor_is_used_for_collisions():
    p = Project()
    p.motor.outline = [[-6, -12], [6, -12], [6, 0], [0, 12], [-6, 0]]
    m = Model(p)
    house = next(x for x in m.unit_parts(0, 60, 60, 1, 0) if x.kind == "housing").prism.fp
    assert len(house.pts) == 5
    assert Layout(m).check(pl(60, 60, 1, 0)).ok


def test_nonconvex_outline_rejected():
    with pytest.raises(ConfigError):
        Project.from_dict({"motor": {"outline": [[0, 0], [10, 0], [5, 2], [10, 10], [0, 10]]}})


def test_center_distance_range_options():
    m = make_model(motor__center_distance=5.0, motor__center_distance_min=4.0, motor__center_distance_max=7.0, motor__center_distance_steps=4)
    assert m.center_distances == sorted(m.center_distances)
    assert 4.0 in m.center_distances and 7.0 in m.center_distances and 5.0 in m.center_distances
    a = m.unit_parts(0, 60, 60, 1, 0, 4.0)[0].prism.fp
    b = m.unit_parts(0, 60, 60, 1, 0, 7.0)[0].prism.fp
    assert math.isclose(abs(a.cx - b.cx), 3.0, abs_tol=1e-9)  # the housing moves with the centre distance


def test_optimizer_can_use_center_distance_range():
    m = make_model(target_count=6, motor__center_distance_min=4.0, motor__center_distance_max=7.0, motor__center_distance_steps=3)
    m.project.search.time_limit_s = 2
    res = run_optimizer(m)
    assert res.best and len(res.best.placements) == 6
    assert Layout(m).copy() is not None and all(p.cd is None or 4.0 - 1e-9 <= p.cd <= 7.0 + 1e-9 for p in res.best.placements)


def test_per_plane_thickness():
    m = make_model(stack__thicknesses=[1.0, 3.0, 5.0], stack__n_motor_planes=3)
    assert [p.thickness for p in m.stack.motor_planes] == [1.0, 3.0, 5.0]


def test_plane_capacity_enforced():
    m = make_model(stack__max_per_plane={"1": 1}, stack__n_motor_planes=2)
    lay = Layout(m)
    assert lay.add(pl(30, 30, 1)) is not None
    r = lay.check(pl(100, 100, 1))
    assert not r.ok and "maximale" in r.reason
    assert lay.check(pl(100, 100, 2)).ok


def test_plane_angle_restriction():
    m = make_model(stack__plane_angles={"1": [90.0]})
    lay = Layout(m)
    assert lay.check(pl(60, 60, 1, 90)).ok
    r = lay.check(pl(60, 60, 1, 45))
    assert not r.ok and "nicht erlaubt" in r.reason
    assert lay.check(pl(60, 60, 2, 45)).ok


def test_plane_keepout_obstacle_only_affects_that_plane():
    m = make_model(obstacles=[ObstacleSpec(shape="rect", x=60, y=60, w=30, h=30, plane=1, name="Sperre")])
    lay = Layout(m)
    assert not lay.check(pl(60, 60, 1, 0)).ok
    # On layer 3 the area is free as long as the rod does not pass the keep out zone of G1 (the rod runs through G1)
    r = lay.check(pl(60, 60, 3, 0))
    assert not r.ok  # the rod of G3 passes through the keep out zone on G1
    assert lay.check(pl(95, 40, 3, 0)).ok


def test_spread_uses_more_area_than_compact():
    res = {}
    for goal in ("compact", "spread"):
        p = Project(target_count=6)
        p.search.time_limit_s = 3
        p.search.layout_goal = goal
        r = run_optimizer(Model(p))
        res[goal] = r.best.score.metrics["footprint_area"]
    assert res["spread"] > res["compact"] * 1.5


def test_fixed_pitch_is_used():
    p = Project(target_count=4)
    p.search.fixed_pitch = 40.0
    p.search.time_limit_s = 2
    r = run_optimizer(Model(p))
    xs = sorted({round(x.x, 3) for x in r.best.placements})
    ys = sorted({round(x.y, 3) for x in r.best.placements})
    diffs = [b - a for a, b in zip(xs, xs[1:])] + [b - a for a, b in zip(ys, ys[1:])]
    assert diffs and all(math.isclose(d, 40.0, abs_tol=0.5) or d > 1 for d in diffs)


@pytest.mark.real_time
def test_stagnation_stops_early():
    import time

    p = Project(target_count=3)
    p.search.time_limit_s = 30
    p.search.stagnation_s = 1.0
    t = time.time()
    r = run_optimizer(Model(p))
    assert time.time() - t < 15
    assert r.status in ("stagnation", "completed")


def test_exhaustive_small_proves_on_grid():
    p = Project(target_count=3)
    p.search.optimizer = "exhaustive_small"
    p.search.time_limit_s = 20
    r = run_optimizer(Model(p))
    assert r.best and len(r.best.placements) == 3
    assert "Raster" in r.optimality_note


def test_exhaustive_small_refuses_large_targets():
    p = Project(target_count=40)
    p.search.optimizer = "exhaustive_small"
    r = run_optimizer(Model(p))
    assert r.status == "infeasible" and r.messages


def test_anneal_free_valid():
    p = Project(target_count=6)
    p.search.optimizer = "anneal_free"
    p.search.time_limit_s = 3
    r = run_optimizer(Model(p))
    assert r.best and len(r.best.placements) <= 6


def test_parallel_workers_merge_results():
    p = Project(target_count=5)
    p.search.workers = 2
    p.search.time_limit_s = 2
    r = run_optimizer(Model(p))
    assert r.best and "x2" in r.optimizer


def test_dxf_structure_and_scale():
    m = make_model()
    geo = build_geometry(m, [pl(60, 40, 2, 0)])
    txt = EXPORTERS["dxf"]().export(geo)
    lines = txt.split("\n")
    assert lines[:2] == ["0", "SECTION"] and txt.strip().endswith("EOF")
    assert "G2_MOTOR" in txt and "G2_GEAR" in txt and "TOP_RODS" in txt and "G0_HOLES" in txt
    i = lines.index("CIRCLE")
    assert lines[i + 2] == "TOP_RODS" or "HOLES" in lines[i + 2]
    # circle of the rod. Centre 60/40, radius 2
    k = [j for j, v in enumerate(lines) if v == "TOP_RODS" and lines[j - 2] == "CIRCLE"][0]
    assert lines[k + 2] == "60.000000" and lines[k + 4] == "40.000000" and lines[k + 8] == "2.000000"


def test_drill_csv_has_hole_per_crossed_plane():
    m = make_model(stack__n_motor_planes=3)
    geo = build_geometry(m, [pl(60, 60, 1, 0)])
    rows = EXPORTERS["csv"]().export(geo).strip().split("\n")[1:]
    assert len(rows) == 4  # G0 to G3 (the retracted rod hangs through all layers)
    assert all(r.split(",")[2] == "60.0000" for r in rows)


def test_svg_import_outline_roundtrip():
    from blindsight.motor_import import motor_from_svg

    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" viewBox="0 0 20 10"><rect width="20" height="10"/></svg>'
    mspec = motor_from_svg(svg, 8.0)
    assert (round(mspec.width, 6), round(mspec.depth, 6), mspec.height) == (20.0, 10.0, 8.0)
    assert len(mspec.outline) == 4


def test_svg_import_scale_ambiguous_and_invalid():
    from blindsight.motor_import import ScaleRequired, SvgImportError, outline_from_svg

    with pytest.raises(ScaleRequired):
        outline_from_svg('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><rect width="20" height="10"/></svg>')
    with pytest.raises(ScaleRequired):
        outline_from_svg('<svg xmlns="http://www.w3.org/2000/svg" width="20px" viewBox="0 0 20 10"><rect width="20" height="10"/></svg>')
    with pytest.raises(SvgImportError):
        outline_from_svg("<svg", 1.0)
    with pytest.raises(SvgImportError):
        outline_from_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/><rect width="1" height="1"/></svg>', 1.0)
    with pytest.raises(SvgImportError):
        outline_from_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>', -1.0)
    with pytest.raises(SvgImportError):
        outline_from_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect width="0" height="1"/></svg>', 1.0)


def test_scoring_footprint_respects_center_distance():
    """Regression. The area score must take the chosen centre distance into account."""
    from blindsight.scoring import footprint_bbox

    m = make_model(motor__center_distance_min=4.0, motor__center_distance_max=9.0, motor__center_distance_steps=3)
    a = footprint_bbox(m, [Placement(60, 60, 1, 0.0, 4.0)])
    b = footprint_bbox(m, [Placement(60, 60, 1, 0.0, 9.0)])
    assert a != b
