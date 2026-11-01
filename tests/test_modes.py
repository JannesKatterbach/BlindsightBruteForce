"""Modes of phase 8. Edge strip for motors, goals of the modes holes and pattern, pattern with individually
turned motors (pattern_holes), tasks of the pattern mode and reading older files.

The goals are measured again here independently of scoring.py."""

import math

import pytest

from blindsight.config import MODE_FREE, MODE_HOLES, MODE_PATTERN, ConfigError, Project, WeightsSpec, mode_of
from blindsight.layout import Placement, layout_from_placements
from blindsight.model import KIND_ROD, Model
from blindsight.optimizers import get_optimizer
from blindsight.scoring import evaluate


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
    model = Model(holes_project(holes, layers=10, border=0, alignment=0))
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
def pattern_project(task, **search):
    p = Project()
    p.target_count = 10
    p.search.optimizer = "pattern_holes"
    p.search.pattern = "hex"
    p.search.pattern_task = task
    p.search.time_limit_s = 5
    for key, value in search.items():
        setattr(p.search, key, value)
    return p


def nearest(points):
    return min(math.hypot(a.x - b.x, a.y - b.y) for i, a in enumerate(points) for b in points[i + 1:])


@pytest.mark.parametrize("task, extra", [("dense", {}), ("dense", {"pattern_fill": True}), ("count", {}), ("pitch", {"pattern_pitch": 24.0})])
def test_pattern_holes_tasks_give_valid_lattices(task, extra):
    model = Model(pattern_project(task, **extra))
    res = get_optimizer("pattern_holes").run(model)
    best = res.best.placements
    assert layout_from_placements(model, best).is_valid()
    if task in ("dense", "count") and not extra:
        assert len(best) == 10
    if task == "pitch":
        assert nearest(best) == pytest.approx(24.0, abs=1e-6)
    else:
        assert len(best) >= 10


def test_dense_is_tighter_than_count():
    dense = get_optimizer("pattern_holes").run(Model(pattern_project("dense"))).best.placements
    spread = get_optimizer("pattern_holes").run(Model(pattern_project("count"))).best.placements
    assert nearest(dense) < nearest(spread)


def test_pattern_holes_needs_a_shape():
    p = pattern_project("dense", pattern="free")
    with pytest.raises(ConfigError) as exc:
        p.validate()
    assert any("search.pattern" in e for e in exc.value.errors)


def test_check_fixed_distance_needs_a_distance():
    with pytest.raises(ConfigError) as exc:
        pattern_project("pitch").validate()
    assert any("search.pattern_pitch" in e for e in exc.value.errors)


# --- Older files -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("search, task", [
    ({"layout_goal": "spread"}, "count"),
    ({"pattern_pitch": 20.0}, "pitch"),
    ({}, "dense"),
])
def test_older_pattern_files_get_a_task(search, task):
    p = Project.from_dict({"search": {"optimizer": "periodic_tile", **search}})
    assert p.search.pattern_task == task


def test_repeating_block_counts_as_clean_alignment():
    p = Project()
    p.target_count = 12
    p.search.optimizer = "periodic_tile"
    p.search.pattern = "centered_square"
    p.search.time_limit_s = 5
    model = Model(p)
    best = get_optimizer("periodic_tile").run(model).best
    assert len(best.placements) == 12 and best.score.terms["alignment"] == 1.0
