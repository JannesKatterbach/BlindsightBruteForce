"""Optimizer with a repeating hole pattern (periodic_tile)."""

import math

import pytest

from blindsight.config import ConfigError, CustomTileSpec, ObstacleSpec, Project
from blindsight.layout import Counter, Placement, layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import get_optimizer
from blindsight.optimizers.periodic_tile import PeriodicChecker, TileShape, blocks_up_to, pattern_cell, tile_shapes


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


def neighbour_distances(cell, count):
    """Distances from the first hole to its count nearest neighbours in the infinite lattice."""
    x0, y0 = cell.holes[0]
    points = [(x + i * cell.width, y + j * cell.height) for x, y in cell.holes for i in range(-3, 4) for j in range(-3, 4)]
    return sorted(math.hypot(x - x0, y - y0) for x, y in points if (x, y) != (x0, y0))[:count]


@pytest.mark.parametrize("pattern, neighbours", [("square", 4), ("centered_square", 4), ("hex", 6), ("hex_rotated", 6), ("staggered", 6)])
def test_patterns_have_equal_hole_distances(pattern, neighbours):
    cell = pattern_cell(pattern, 12.0, None)
    assert math.isclose(cell.nearest_distance(), 12.0)
    assert all(math.isclose(d, 12.0) for d in neighbour_distances(cell, neighbours))


def test_rectangle_and_staggered_use_the_second_distance():
    assert neighbour_distances(pattern_cell("rectangle", 10.0, 16.0), 4) == pytest.approx([10, 10, 16, 16])
    staggered = pattern_cell("staggered", 10.0, 14.0)
    assert (staggered.width, staggered.height) == (10.0, 28.0) and staggered.holes[1] == (5.0, 14.0)


def test_custom_tile_scales_evenly():
    cell = pattern_cell("custom", 40.0, None, CustomTileSpec(20.0, 10.0, [[0, 0], [10, 5]], True))
    assert (cell.width, cell.height, cell.holes) == (40.0, 20.0, ((0.0, 0.0), (20.0, 10.0)))


def test_blocks_grow_by_hole_count():
    blocks = blocks_up_to(2, 8)
    assert blocks[0] == (1, 1) and all(m * n * 2 <= 8 for m, n in blocks)
    assert [m * n for m, n in blocks] == sorted(m * n for m, n in blocks)


def test_tile_shapes_cover_all_sub_grids():
    shapes = {(s.rows, s.cols, s.offset) for s in tile_shapes(4)}
    assert {(1, 4, False), (2, 2, False), (2, 2, True), (4, 1, False), (4, 1, True)} <= shapes
    assert TileShape(2, 2, True).positions(10, 8) == [(0, 0), (10, 0), (5, 8), (15, 8)]


def test_found_block_is_valid_on_a_large_patch():
    model, res = run(project(pattern="centered_square"))
    tile = res.best.tile
    assert tile and tile["pattern"] == "centered_square"
    checker = PeriodicChecker(model, Counter())
    c = checker.center
    placements = [
        Placement(c + i * tile["width"] + u["x"], c + j * tile["height"] + u["y"], u["plane"], u["angle"], u.get("cd"))
        for i in range(-2, 3) for j in range(-2, 3) for u in tile["units"]
    ]
    assert layout_from_placements(checker.model, placements).all_collisions() == []


def test_exact_target_count_on_a_regular_lattice():
    p = project(pattern="square", pattern_pitch=25.0)
    p.target_count = 7
    model, res = run(p)
    best = res.best
    assert len(best.placements) == 7 and layout_from_placements(model, best.placements).is_valid()
    x0, y0 = best.placements[0].x, best.placements[0].y
    for q in best.placements:  # every hole on the 25 mm lattice
        assert math.isclose((q.x - x0) / 25.0, round((q.x - x0) / 25.0), abs_tol=1e-6)
        assert math.isclose((q.y - y0) / 25.0, round((q.y - y0) / 25.0), abs_tol=1e-6)
    assert "Lochabstand 25.00 mm" in res.messages[0]


def test_free_pattern_keeps_a_fixed_tile_size():
    _, res = run(project(pattern="free", tile_rods=1, tile_width=26.0, tile_height=22.0))
    tile = res.best.tile
    assert (tile["width"], tile["height"]) == (26.0, 22.0)


def test_fixed_custom_tile_is_used_as_given():
    custom = CustomTileSpec(40.0, 34.0, [[0.0, 0.0], [20.0, 17.0]], False)
    model, res = run(project(pattern="custom", custom_tile=custom))
    tile = res.best.tile
    assert tile["cell"] == [40.0, 34.0]
    assert layout_from_placements(model, res.best.placements).is_valid()


def test_custom_pattern_needs_a_tile():
    p = project(pattern="custom")
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("search.custom_tile" in e for e in exc.value.errors)
    p.search.custom_tile = CustomTileSpec(10.0, 10.0, [[12.0, 0.0]], False)
    with pytest.raises(ConfigError):
        p.validate()


def test_too_small_fixed_distance_is_reported():
    _, res = run(project(pattern="square", pattern_pitch=6.0))
    assert not res.solutions
    assert any("festen Abstand 6.00 mm" in m for m in res.messages)


def test_obstacles_skip_single_holes():
    p = project(pattern="hex")
    p.obstacles = [ObstacleSpec(shape="circle", x=60.0, y=60.0, r=15.0)]
    model, res = run(p)
    best = res.best
    assert len(best.placements) == 8 and layout_from_placements(model, best.placements).is_valid()
    assert all(math.hypot(q.x - 60.0, q.y - 60.0) > 15.0 for q in best.placements)


@pytest.mark.parametrize("goal", ["compact", "spread"])
def test_layout_goals_give_valid_layouts(goal):
    model, res = run(project(pattern="hex", layout_goal=goal))
    assert res.best and len(res.best.placements) == 8
    for solution in res.solutions:
        assert layout_from_placements(model, solution.placements).is_valid()


def test_spread_uses_a_larger_distance_than_compact():
    _, compact = run(project(pattern="square", layout_goal="compact"))
    _, spread = run(project(pattern="square", layout_goal="spread"))
    assert spread.best.tile["pitch"] > compact.best.tile["pitch"]
