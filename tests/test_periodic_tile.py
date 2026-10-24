"""Optimizer with a repeating pattern (periodic_tile)."""

import math

import pytest

from blindsight.config import ObstacleSpec, Project
from blindsight.layout import Counter, Layout, Placement, layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import get_optimizer
from blindsight.optimizers.periodic_tile import PeriodicChecker, TileShape, tile_shapes


def project(**search):
    p = Project()
    p.target_count = 8
    p.search.optimizer = "periodic_tile"
    p.search.time_limit_s = 6
    for key, value in search.items():
        setattr(p.search, key, value)
    return p


def run(p):
    model = Model(p)
    return model, get_optimizer("periodic_tile").run(model)


def test_tile_shapes_cover_all_sub_grids():
    shapes = {(s.rows, s.cols, s.offset) for s in tile_shapes(4)}
    assert {(1, 4, False), (2, 2, False), (2, 2, True), (4, 1, False), (4, 1, True)} <= shapes
    assert TileShape(2, 2, True).positions(10, 8) == [(0, 0), (10, 0), (5, 8), (15, 8)]


def test_found_tile_is_valid_on_a_large_patch():
    model, res = run(project(tile_rods=2))
    tile = res.best.tile
    assert tile and tile["rods"] == 2
    # 5 x 5 copies of the tile in an unbounded model must be collision free
    checker = PeriodicChecker(model, Counter())
    c = checker.center
    placements = [
        Placement(c + i * tile["width"] + u["x"], c + j * tile["height"] + u["y"], u["plane"], u["angle"], u.get("cd"))
        for i in range(-2, 3) for j in range(-2, 3) for u in tile["units"]
    ]
    assert layout_from_placements(checker.model, placements).all_collisions() == []


def test_layout_repeats_the_tile_and_uses_whole_tiles_only():
    model, res = run(project(tile_rods=2))
    best = res.best
    tile = best.tile
    assert len(best.placements) == len(tile["origins"]) * 2 == 8
    assert layout_from_placements(model, best.placements).is_valid()
    # Every rod sits at its pattern position of one placed tile, with the tile's plane and angle
    expected = sorted(
        (round(x + u["x"], 6), round(y + u["y"], 6), u["plane"], u["angle"]) for x, y in tile["origins"] for u in tile["units"]
    )
    actual = sorted((round(q.x, 6), round(q.y, 6), q.plane, q.angle) for q in best.placements)
    assert actual == expected


def test_rods_are_spaced_evenly_inside_the_tile():
    _, res = run(project(tile_rods=3))
    tile = res.best.tile
    xs = sorted({round(u["x"], 6) for u in tile["units"]})
    ys = sorted({round(u["y"], 6) for u in tile["units"]})
    steps = [b - a for a, b in zip(xs, xs[1:])] + [b - a for a, b in zip(ys, ys[1:])]
    assert all(math.isclose(s, steps[0]) for s in steps[: len(xs) - 1])


def test_fixed_tile_size_is_used():
    _, res = run(project(tile_rods=1, tile_width=26.0, tile_height=22.0))
    tile = res.best.tile
    assert (tile["width"], tile["height"]) == (26.0, 22.0)


def test_target_is_rounded_down_to_whole_tiles():
    p = project(tile_rods=2)
    p.target_count = 7
    _, res = run(p)
    assert len(res.best.placements) == 6
    assert any("kein Vielfaches" in m and "nächstes Vielfaches 8" in m for m in res.messages)


def test_target_below_rods_per_tile_is_reported():
    p = project(tile_rods=4)
    p.target_count = 3
    _, res = run(p)
    assert res.status == "infeasible" and not res.solutions
    assert any("kleiner als die Schrauben je Kachel" in m for m in res.messages)


def test_too_small_fixed_tile_reports_no_tile():
    _, res = run(project(tile_rods=2, tile_width=6.0, tile_height=6.0))
    assert not res.solutions
    assert any("keine gültige Kachel" in m for m in res.messages)


def test_obstacles_skip_whole_tiles():
    p = project(tile_rods=2)
    p.obstacles = [ObstacleSpec(shape="circle", x=60.0, y=60.0, r=15.0)]
    model, res = run(p)
    best = res.best
    assert layout_from_placements(model, best.placements).is_valid()
    assert len(best.placements) % 2 == 0
    assert all(math.hypot(q.x - 60.0, q.y - 60.0) > 15.0 for q in best.placements)


@pytest.mark.parametrize("goal", ["compact", "spread"])
def test_layout_goals_give_valid_layouts(goal):
    model, res = run(project(tile_rods=2, layout_goal=goal))
    assert res.best and len(res.best.placements) == 8
    for solution in res.solutions:
        assert layout_from_placements(model, solution.placements).is_valid()
