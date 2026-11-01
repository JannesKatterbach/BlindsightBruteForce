"""Modes of phase 8. Edge strip for motors, goals of the modes holes and pattern, pattern with individually
turned motors (pattern_holes), tasks of the pattern mode and reading older files.

The goals are measured again here independently of scoring.py."""

import math

import pytest

from blindsight.config import MODE_FREE, MODE_HOLES, MODE_PATTERN, ConfigError, ObstacleSpec, Project, WeightsSpec, mode_of
from blindsight.export import build_geometry
from blindsight.layout import Placement, layout_from_placements
from blindsight.model import KIND_ROD, Model
from blindsight.optimizers import get_optimizer
from blindsight.scoring import evaluate
from blindsight.tiling import TilingError, tile_project


def grid(n, pitch, x0=30.0, y0=30.0):
    return [[x0 + i * pitch, y0 + j * pitch] for j in range(n) for i in range(n)]


def holes_project(holes, **weights):
    p = Project()
    p.search.optimizer = "fixed_holes"
    p.holes = holes
    p.search.time_limit_s = 4
    for key, value in weights.items():
        setattr(p.search.weights, key, value)
    return p


def reach_beyond(model, placements, margin):
    """Deepest reach of a housing or gear beyond the area board minus margin (own computation)."""
    b = model.project.bounds
    depth = 0.0
    for i, pl in enumerate(placements):
        for part in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            if part.kind == KIND_ROD:
                continue
            x0, y0, x1, y1 = part.prism.fp.bbox
            depth = max(depth, margin - x0, margin - y0, x1 - (b.width - margin), y1 - (b.height - margin))
    return depth


def test_modes_follow_the_optimizer():
    assert mode_of("fixed_holes") == MODE_HOLES
    assert mode_of("periodic_tile") == mode_of("pattern_holes") == MODE_PATTERN
    assert mode_of("pattern_greedy") == mode_of("anneal_free") == mode_of("exhaustive_small") == MODE_FREE


# --- Edge strip ---------------------------------------------------------------------------------------------------
def test_edge_strip_keeps_rods_inside_and_motors_on_the_board():
    p = Project()
    p.bounds.border, p.bounds.border_width = True, 10.0
    model = Model(p)
    messages = {model.within_bounds(model.unit_parts(0, 5.0, 60.0, 1, float(angle)), 1) for angle in range(0, 360, 15)}
    assert None not in messages and any("Randbereich" in m for m in messages)  # the rod lies in the strip
    # A rod 12 mm from the edge is fine, its motor may reach into the strip but not beyond the board
    for angle in range(0, 360, 15):
        parts = model.unit_parts(0, 12.0, 60.0, 1, float(angle))
        inside_board = all(part.prism.fp.bbox[0] >= -1e-9 for part in parts)
        assert (model.within_bounds(parts, 1) is None) == inside_board


def test_edge_strip_must_fit_on_the_board():
    p = Project()
    p.bounds.border, p.bounds.border_width = True, 70.0
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("bounds.border_width" in e for e in exc.value.errors)


# --- Goals ---------------------------------------------------------------------------------------------------------
def test_served_holes_count_more_than_the_goals():
    p = holes_project(grid(3, 30.0))
    model = Model(p)
    full = [Placement(x, y, 3, 0.0) for x, y in p.holes]  # deepest layer, worst for the goal few layers
    fewer = [Placement(x, y, 1, 0.0) for x, y in p.holes[:-1]]
    w = p.search.weights
    assert evaluate(model, full, w, 9).total > evaluate(model, fewer, w, 9).total


def test_goal_terms_are_measured_independently():
    p = holes_project(grid(3, 30.0))
    p.bounds.border, p.bounds.border_width = True, 20.0
    p.stack.layers_fixed = False
    model = Model(p)
    placements = [Placement(x, y, 1 + (k % 2), 90.0 * (k % 2)) for k, (x, y) in enumerate(p.holes)]
    terms = evaluate(model, placements, p.search.weights, 9).terms
    assert terms["count"] == 1.0
    assert terms["layers"] == pytest.approx(1 - (2 - 1) / (3 - 1))
    assert terms["border"] == pytest.approx(max(0.0, 1 - reach_beyond(model, placements, 20.0) / 20.0))
    uniform = [Placement(x, y, 2, 45.0) for x, y in p.holes]
    assert evaluate(model, uniform, p.search.weights, 9).terms["alignment"] == 1.0


def test_rows_alternating_count_as_clean_alignment():
    holes = grid(4, 30.0, 15.0, 15.0)
    model = Model(holes_project(holes))
    rows = [Placement(x, y, 1, 0.0 if round((y - 15.0) / 30.0) % 2 else 180.0) for x, y in holes]
    mixed = [Placement(x, y, 1, [0.0, 90.0, 180.0, 270.0, 45.0][k * 7 % 5]) for k, (x, y) in enumerate(holes)]
    w = WeightsSpec()
    assert evaluate(model, rows, w, 16).terms["alignment"] == 1.0
    assert evaluate(model, mixed, w, 16).terms["alignment"] < 0.6


def test_goal_few_layers_moves_motors_up():
    holes = grid(3, 32.0)
    p = holes_project(holes, layers=10, border=0, alignment=0)
    p.stack.layers_fixed = False
    model = Model(p)
    res = get_optimizer("fixed_holes").run(model)
    assert len(res.best.placements) == 9 and layout_from_placements(model, res.best.placements).is_valid()
    assert max(q.plane for q in res.best.placements) == 1
    free = Model(holes_project(holes, layers=0, border=0, alignment=1))
    spread = get_optimizer("fixed_holes").run(free).best.placements
    assert len(spread) == 9


def test_goal_alignment_gives_a_repeating_arrangement():
    holes = grid(3, 32.0)
    model = Model(holes_project(holes, layers=0, border=0, alignment=10))
    res = get_optimizer("fixed_holes").run(model)
    assert res.best.score.terms["alignment"] == 1.0


def test_goal_small_edge_turns_outer_motors_inwards():
    def edge(**weights):
        p = holes_project(grid(3, 34.0, 25.0, 25.0), **weights)
        p.bounds.border, p.bounds.border_width = True, 20.0
        model = Model(p)
        best = get_optimizer("fixed_holes").run(model).best.placements
        assert len(best) == 9 and layout_from_placements(model, best).is_valid()
        return reach_beyond(model, best, 20.0)
    small = edge(layers=0, border=10, alignment=0)
    assert small < edge(layers=0, border=0, alignment=10) and small < 20.0


# --- Pattern with individually turned motors (2b) -----------------------------------------------------------------
def pattern_project(count, distance, **search):
    p = Project()
    p.target_count = 10
    p.search.optimizer = "pattern_holes"
    p.search.pattern = "hex"
    p.search.pattern_count = count
    p.search.pattern_distance = distance
    p.search.time_limit_s = 5
    for key, value in search.items():
        setattr(p.search, key, value)
    return p


def nearest(points):
    return min(math.hypot(a.x - b.x, a.y - b.y) for i, a in enumerate(points) for b in points[i + 1:])


COMBINATIONS = [("fill", "smallest"), ("exact", "smallest"), ("exact", "largest"), ("fill", "fixed"), ("exact", "fixed")]


@pytest.mark.parametrize("optimizer", ["pattern_holes", "periodic_tile"])
@pytest.mark.parametrize("count, distance", COMBINATIONS)
def test_every_combination_of_the_two_questions_is_valid(optimizer, count, distance):
    p = pattern_project(count, distance, optimizer=optimizer, pattern_pitch=24.0 if distance == "fixed" else None)
    model = Model(p)
    best = get_optimizer(optimizer).run(model).best.placements
    assert layout_from_placements(model, best).is_valid()
    if count == "exact":
        assert len(best) == 10
    else:
        assert len(best) > 10  # the board is filled
    if distance == "fixed":
        assert nearest(best) == pytest.approx(24.0, abs=1e-6)


def test_smallest_is_tighter_than_largest():
    dense = get_optimizer("pattern_holes").run(Model(pattern_project("exact", "smallest"))).best.placements
    spread = get_optimizer("pattern_holes").run(Model(pattern_project("exact", "largest"))).best.placements
    assert nearest(dense) < nearest(spread)


def test_largest_needs_a_fixed_count():
    with pytest.raises(ConfigError) as exc:
        pattern_project("fill", "largest").validate()
    assert any("search.pattern_distance" in e for e in exc.value.errors)


def test_pattern_holes_needs_a_shape():
    p = pattern_project("exact", "smallest", pattern="free")
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("search.pattern" in e for e in exc.value.errors)


def test_fixed_distance_needs_a_distance():
    with pytest.raises(ConfigError) as exc:
        pattern_project("fill", "fixed").validate()
    assert any("search.pattern_pitch" in e for e in exc.value.errors)


# --- Older files -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("search, questions", [
    ({"optimizer": "periodic_tile", "layout_goal": "spread"}, ("exact", "largest")),
    ({"optimizer": "periodic_tile", "pattern_pitch": 20.0}, ("exact", "fixed")),
    ({"optimizer": "periodic_tile"}, ("exact", "smallest")),
    ({"optimizer": "pattern_holes", "pattern_task": "dense", "pattern_fill": True}, ("fill", "smallest")),
    ({"optimizer": "pattern_holes", "pattern_task": "count"}, ("exact", "largest")),
    ({"optimizer": "periodic_tile", "pattern_task": "pitch", "pattern_pitch": 20.0}, ("fill", "fixed")),
])
def test_older_pattern_files_get_the_two_questions(search, questions):
    p = Project.from_dict({"search": search})
    assert (p.search.pattern_count, p.search.pattern_distance) == questions


# --- Layers not fixed -------------------------------------------------------------------------------------------------
def test_layers_not_fixed_use_fewer_layers_and_shorter_stacks():
    holes = grid(3, 32.0)
    p = holes_project(holes, layers=80, border=10, alignment=10)
    p.stack.layers_fixed = False
    model = Model(p)
    best = get_optimizer("fixed_holes").run(model).best.placements
    assert len(best) == 9 and max(q.plane for q in best) == 1
    geometry = build_geometry(model, best)
    assert [pl["index"] for pl in geometry["planes"]] == [0, 1]  # only G0 and G1 are left
    fixed = holes_project(holes, border=10, alignment=10)
    assert len(build_geometry(Model(fixed), best)["planes"]) == 4  # a fixed count keeps all layers


def test_goal_few_layers_only_counts_when_the_count_is_not_fixed():
    p = holes_project(grid(2, 32.0))
    model = Model(p)
    placements = [Placement(x, y, 3, 0.0) for x, y in p.holes]
    assert "layers" not in evaluate(model, placements, p.search.weights, 4).terms
    p.stack.layers_fixed = False
    assert evaluate(Model(p), placements, p.search.weights, 4).terms["layers"] == 0.0


def test_default_weights_are_percent():
    w = WeightsSpec()
    assert w.count + w.area + w.uniformity + w.regularity == 100
    assert w.border + w.alignment + w.layers == 100


# --- Tiling of a repeating block ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def block_result():
    p = Project()
    p.target_count = 8
    p.search.optimizer = "periodic_tile"
    p.search.pattern = "centered_square"
    p.search.pattern_count = "exact"
    p.search.time_limit_s = 5
    p.bounds.border, p.bounds.border_width = True, 6.0
    p.obstacles = [ObstacleSpec(shape="circle", x=10.0, y=10.0, r=3.0)]
    return p, get_optimizer("periodic_tile").run(Model(p)).best.tile


@pytest.mark.parametrize("nx, ny", [(1, 1), (2, 3), (3, 3)])
def test_tiled_blocks_stay_valid_on_a_fitted_board(block_result, nx, ny):
    p, tile = block_result
    project, placements, notes = tile_project(p, tile, nx, ny)
    model = Model(project)
    assert len(placements) == nx * ny * len(tile["units"])
    assert layout_from_placements(model, placements).is_valid()  # also inside the board and the edge strip
    assert project.obstacles == [] and notes  # the old board's obstacles are gone, with a note
    bigger, _, _ = tile_project(p, tile, nx + 1, ny)
    assert bigger.bounds.width == pytest.approx(project.bounds.width + tile["width"])  # one more block, one block wider


def test_tiling_rejects_bad_input(block_result):
    p, tile = block_result
    for bad in ({}, {**tile, "width": -1}, {**tile, "units": []}):
        with pytest.raises(TilingError):
            tile_project(p, bad, 2, 2)
    with pytest.raises(TilingError):
        tile_project(p, tile, 0, 2)


def test_repeating_block_counts_as_clean_alignment():
    p = Project()
    p.target_count = 12
    p.search.optimizer = "periodic_tile"
    p.search.pattern = "centered_square"
    p.search.pattern_count = "exact"
    p.search.time_limit_s = 5
    model = Model(p)
    best = get_optimizer("periodic_tile").run(model).best
    assert len(best.placements) == 12 and best.score.terms["alignment"] == 1.0


def test_tile_endpoint_returns_a_fitted_valid_layout(block_result):
    import json
    from blindsight.web.server import App
    p, tile = block_result
    body = json.dumps({"project": p.to_dict(), "tile": tile, "nx": 2, "ny": 2}).encode()
    code, _, raw = App().handle("POST", "/api/tile", {}, body, {"Content-Type": "application/json"})
    data = json.loads(raw)
    assert code == 200 and data["valid"] and len(data["placements"]) == 4 * len(tile["units"])
    assert data["project"]["bounds"]["width"] > tile["width"] * 2
    code, _, raw = App().handle("POST", "/api/tile", {}, json.dumps({"project": p.to_dict(), "tile": tile, "nx": 0, "ny": 1}).encode(),
                                {"Content-Type": "application/json"})
    assert code == 400
