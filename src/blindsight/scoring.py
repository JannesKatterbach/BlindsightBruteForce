"""Scoring function. All objectives lie in [0, 1], 1 is best.

Every mode rates its own goals (GOALS_BY_MODE, weights from WeightsSpec normalised over these goals).
  count        placed number relative to the target number
  area         1 - used bounding box / available build area (share of free build area)
  uniformity   1 - 2 * coefficient of variation of the neighbour distances
  regularity   alignment of the neighbours to a square or hexagonal pattern
               (bond orientational order parameters psi4 and psi6)
  layers       1 - share of the motor layers needed (down to the deepest layer in use)
  border       1 - depth by which motors reach into the edge strip, relative to its width
  alignment    share of equal layer and rotation between neighbours one to four lattice steps apart along
               the two main directions of the holes (row by row alternation counts as regular)

Free mode. Total = weighted mean of count, area, uniformity and regularity.
Modes holes and pattern. Every served hole counts more than all goals together,
total = (count + weighted mean of layers, border, alignment) / (target + 1).

Uniformity counts as satisfied (1.0) for a single unit. Regularity needs at least 4 neighbours (psi4)
and is 0 otherwise, the same for every count. Earlier a single unit got 1.0 and two to four units 0,
which made results flip abruptly. A neutral value of 1.0 on the other hand would have preferred small
arrangements over complete ones.

Extending. A new objective is a function ``(LayoutStats) -> float`` in ``OBJECTIVES`` and a field of
the same name in ``config.WeightsSpec`` (plus a FIELD_META entry and catalog texts for the UI).
"""

from __future__ import annotations

import cmath
import math
from dataclasses import asdict, dataclass, field
from functools import cached_property
from typing import Callable, Optional

from collections import Counter

from .config import MODE_FREE, MODE_HOLES, MODE_PATTERN, WeightsSpec
from .geometry import BBox, convex_hull, polygon_area
from .layout import Placement
from .model import KIND_ROD, Model
from .units import EPS, EPS_AREA

UNIFORMITY_CV_FACTOR = 2.0  # a coefficient of variation of 0.5 gives uniformity 0
ORDER_NEIGHBORS = (4, 6)  # psi4 (square) and psi6 (hexagon)
GOALS_BY_MODE = {
    MODE_FREE: ("count", "area", "uniformity", "regularity"),
    MODE_HOLES: ("layers", "border", "alignment"),
    MODE_PATTERN: ("layers", "border", "alignment"),
}
ALIGNMENT_STEPS = 4  # repetition after up to this many lattice steps counts as regular
LATTICE_TOL = 0.05  # mm, two holes count as one lattice step apart within this tolerance
NEIGHBOR_SLACK = 1.02  # neighbours up to this factor times the nearest distance span the lattice directions


@dataclass
class Score:
    total: float
    terms: dict[str, float]
    weights: dict[str, float]
    metrics: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class LayoutStats:
    """Metrics of a layout from which the objectives are computed."""

    count: int
    target: int
    bounds_area: float
    footprint: BBox
    footprint_area: float
    hull_area: float
    nn_distances: list[float]  # distance of every rod to the nearest one
    order: dict[int, Optional[float]]  # k -> mean psi_k or None (too few neighbours)
    deepest_layer: int = 1  # deepest motor layer in use
    layer_count: int = 1  # motor layers available
    border_depth: float = 0.0  # mm, deepest reach of a motor into the edge strip
    border_width: float = 0.0  # mm, 0 without edge strip
    placements: list = field(default_factory=list, repr=False)

    @cached_property
    def alignment(self) -> float:
        """Only computed when a goal needs it (quadratic in the number of units)."""
        return _alignment(self.placements)

    @property
    def mean_nn(self) -> float:
        nn = self.nn_distances
        return sum(nn) / len(nn) if nn else 0.0

    @property
    def nn_cv(self) -> float:
        """Coefficient of variation of the neighbour distances (0 with fewer than two distances)."""
        nn = self.nn_distances
        if len(nn) < 2 or self.mean_nn <= 0:
            return 0.0
        var = sum((d - self.mean_nn) ** 2 for d in nn) / len(nn)
        return math.sqrt(var) / self.mean_nn


# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------
def _count_term(s: LayoutStats) -> float:
    return min(1.0, s.count / max(1, s.target))


def _area_term(s: LayoutStats) -> float:
    return max(0.0, 1.0 - s.footprint_area / s.bounds_area)


def _uniformity_term(s: LayoutStats) -> float:
    if len(s.nn_distances) < 2:
        return 1.0
    return max(0.0, 1.0 - UNIFORMITY_CV_FACTOR * s.nn_cv)


def _regularity_term(s: LayoutStats) -> float:
    values = [v for v in s.order.values() if v is not None]
    return max(values) if values else 0.0


def _layers_term(s: LayoutStats) -> float:
    return 1.0 - (s.deepest_layer - 1) / (s.layer_count - 1) if s.layer_count > 1 else 1.0


def _border_term(s: LayoutStats) -> float:
    return max(0.0, 1.0 - s.border_depth / s.border_width) if s.border_width > 0 else 1.0


OBJECTIVES: dict[str, Callable[[LayoutStats], float]] = {
    "count": _count_term,
    "area": _area_term,
    "uniformity": _uniformity_term,
    "regularity": _regularity_term,
    "layers": _layers_term,
    "border": _border_term,
    "alignment": lambda s: s.alignment,
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def footprint_bbox(model: Model, placements: list[Placement]) -> BBox:
    """Bounding box of all parts of all units in top view."""
    boxes = [model.unit_bbox(pl.x, pl.y, pl.plane, pl.angle, pl.cd) for pl in placements]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def hole_area(model: Model) -> BBox:
    """Area the rod axes may lie in (board minus the margins of the rods)."""
    bounds = model.project.bounds
    m = bounds.rod_margin
    return (bounds.xmin + m, bounds.ymin + m, bounds.xmax - m, bounds.ymax - m)


def _reach(area: BBox, box: BBox) -> float:
    """How far box reaches beyond area (mm, 0 or negative inside)."""
    return max(area[0] - box[0], area[1] - box[1], box[2] - area[2], box[3] - area[3])


def unit_edge_reach(model: Model, pl: Placement) -> float:
    """How far the housing and gear of one unit reach beyond the area of the holes (into the edge strip)."""
    area = hole_area(model)
    parts = model.unit_parts(-1, pl.x, pl.y, pl.plane, pl.angle, pl.cd)
    return max([0.0] + [_reach(area, p.prism.fp.bbox) for p in parts if p.kind != KIND_ROD])


def _hull_and_border(model: Model, placements: list[Placement]) -> tuple[float, float]:
    """Area of the convex hull of all housings and gears (rods as their centre) and the deepest reach of a
    housing or gear beyond the area of the holes (into the edge strip), in mm."""
    area = hole_area(model)
    points = []
    depth = 0.0
    for i, pl in enumerate(placements):
        for part in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            if part.kind == KIND_ROD:
                points.append((pl.x, pl.y))
                continue
            points.extend(part.prism.fp.outline())
            depth = max(depth, _reach(area, part.prism.fp.bbox))
    return polygon_area(convex_hull(points)), depth


def _lattice_directions(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The two most frequent independent neighbour vectors (pointing to positive x or up). Votes are counted on
    rounded vectors, the result is their exact mean (rounding errors would add up over several steps)."""
    votes: Counter = Counter()
    sums: dict[tuple[float, float], list[float]] = {}
    for i, (px, py) in enumerate(points):
        dists = [(math.hypot(qx - px, qy - py), qx - px, qy - py) for j, (qx, qy) in enumerate(points) if j != i]
        if not dists:
            continue
        nearest = min(d[0] for d in dists)
        for d, dx, dy in dists:
            if d <= nearest * NEIGHBOR_SLACK:
                if dx < -LATTICE_TOL or (abs(dx) <= LATTICE_TOL and dy < 0):
                    dx, dy = -dx, -dy
                key = (round(dx, 1), round(dy, 1))
                votes[key] += 1
                total = sums.setdefault(key, [0.0, 0.0])
                total[0] += dx
                total[1] += dy
    out: list[tuple[float, float]] = []
    for key, count in votes.most_common():
        vector = (sums[key][0] / count, sums[key][1] / count)
        if not out or abs(out[0][0] * vector[1] - out[0][1] * vector[0]) > LATTICE_TOL * math.hypot(*vector):
            out.append(vector)
        if len(out) == 2:
            break
    return out


PairGroups = list[list[list[tuple[int, int]]]]  # per main direction, per step count the pairs of hole indices


def lattice_pairs(points: list[tuple[float, float]]) -> PairGroups:
    """Pairs of holes that lie 1 to ALIGNMENT_STEPS steps apart along the two main lattice directions.
    Depends only on the positions, so a search over fixed holes computes it once."""
    cells: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(points):
        cells.setdefault((round(x), round(y)), []).append(i)

    def find(x: float, y: float) -> Optional[int]:
        for cx in (math.floor(x), math.ceil(x)):
            for cy in (math.floor(y), math.ceil(y)):
                for j in cells.get((cx, cy), ()):
                    if abs(points[j][0] - x) <= LATTICE_TOL and abs(points[j][1] - y) <= LATTICE_TOL:
                        return j
        return None

    groups: PairGroups = []
    for dx, dy in _lattice_directions(points):
        by_step = []
        for step in range(1, ALIGNMENT_STEPS + 1):
            pairs = [(i, find(x + step * dx, y + step * dy)) for i, (x, y) in enumerate(points)]
            by_step.append([(i, j) for i, j in pairs if j is not None])
        groups.append(by_step)
    return groups


def alignment_value(groups: PairGroups, keys: list) -> float:
    """Share of equal keys (layer, rotation, centre distance) along the lattice pairs. Per main direction
    the best step count counts, so rows alternating with period two are regular. 1.0 without pairs."""
    shares = []
    for by_step in groups:
        values = [sum(keys[i] == keys[j] for i, j in pairs) / len(pairs) for pairs in by_step if pairs]
        if values:
            shares.append(max(values))
    return sum(shares) / len(shares) if shares else 1.0


def unit_key(pl: Placement) -> tuple:
    """What has to repeat for a clean alignment. Layer, rotation and centre distance."""
    return (pl.plane, round(pl.angle, 3), pl.cd)


def _alignment(placements: list[Placement]) -> float:
    return alignment_value(lattice_pairs([(p.x, p.y) for p in placements]), [unit_key(p) for p in placements])


def _neighbor_stats(points: list[tuple[float, float]]) -> tuple[list[float], dict[int, Optional[float]]]:
    """Nearest neighbour distances and mean order parameters psi_k per k in ORDER_NEIGHBORS."""
    nn: list[float] = []
    psi: dict[int, list[float]] = {k: [] for k in ORDER_NEIGHBORS}
    for i, (px, py) in enumerate(points):
        neighbors = sorted((math.hypot(px - qx, py - qy), j) for j, (qx, qy) in enumerate(points) if j != i)
        if not neighbors:
            continue
        nn.append(neighbors[0][0])
        for k in ORDER_NEIGHBORS:
            if len(neighbors) < k:
                continue
            acc = sum(cmath.exp(1j * k * math.atan2(points[j][1] - py, points[j][0] - px)) for _, j in neighbors[:k])
            psi[k].append(abs(acc) / k)
    order = {k: (sum(v) / len(v) if v else None) for k, v in psi.items()}
    return nn, order


def layout_stats(model: Model, placements: list[Placement], target: int) -> LayoutStats:
    project = model.project
    bounds = project.bounds
    box = footprint_bbox(model, placements)
    nn, order = _neighbor_stats([(pl.x, pl.y) for pl in placements])
    hull_area, border_depth = _hull_and_border(model, placements)
    return LayoutStats(
        count=len(placements),
        target=target,
        bounds_area=bounds.width * bounds.height,
        footprint=box,
        footprint_area=max((box[2] - box[0]) * (box[3] - box[1]), EPS_AREA),
        hull_area=hull_area,
        nn_distances=nn,
        order=order,
        deepest_layer=max(pl.plane for pl in placements),
        layer_count=project.stack.n_motor_planes,
        border_depth=border_depth,
        border_width=bounds.border_width if bounds.border else 0.0,
        placements=placements,
    )


def normalized_weights(weights: WeightsSpec, goals: tuple[str, ...] = GOALS_BY_MODE[MODE_FREE]) -> dict[str, float]:
    """Weights of the goals as shares summing to 1 (equal shares if all are 0)."""
    raw = weights.as_dict()
    total = sum(raw[name] for name in goals)
    return {name: raw[name] / total if total > 0 else 1.0 / len(goals) for name in goals}


def evaluate(model: Model, placements: list[Placement], weights: WeightsSpec, target: int) -> Score:
    """Score a layout with the goals of the mode. Returns total, objectives, normalised weights and metrics."""
    mode = model.project.mode
    goals = GOALS_BY_MODE[mode]
    wn = normalized_weights(weights, goals)
    names = goals if mode == MODE_FREE else ("count", *goals)
    if not placements:
        return Score(0.0, {k: 0.0 for k in names}, wn, {"count": 0})
    stats = layout_stats(model, placements, target)
    terms = {name: OBJECTIVES[name](stats) for name in names}
    goal_value = sum(wn[k] * terms[k] for k in goals)
    total = goal_value if mode == MODE_FREE else (min(stats.count, target) + goal_value) / (target + 1)
    return Score(total, terms, wn, _metrics(stats, placements))


def _metrics(stats: LayoutStats, placements: list[Placement]) -> dict[str, float]:
    x0, y0, x1, y1 = stats.footprint
    planes_used: dict[int, int] = {}
    for pl in placements:
        planes_used[pl.plane] = planes_used.get(pl.plane, 0) + 1
    return {
        "count": stats.count,
        "target": stats.target,
        "footprint_width": x1 - x0,
        "footprint_height": y1 - y0,
        "footprint_area": stats.footprint_area,
        "hull_area": stats.hull_area,
        "mean_nn_distance": stats.mean_nn,
        "nn_cv": stats.nn_cv,
        "psi4": stats.order[4] or 0.0,
        "psi6": stats.order[6] or 0.0,
        "layers_used": stats.deepest_layer,
        "border_depth": stats.border_depth,
        **{f"plane_{k}_units": v for k, v in sorted(planes_used.items())},
    }


def upper_bound_count(model: Model) -> int:
    """Strict upper bound of the number of rods (Oler's inequality).

    Any two rod axes are at least d = rod diameter + safety clearance apart (all rods overlap in
    height). The axes lie in the rectangle of permitted centres (build area minus rod margin and rod
    radius) with area A and perimeter P. For points with minimum distance d in a convex region
        N <= 2 / sqrt(3) * A / d^2 + P / (2 d) + 1
    Motors are ignored, so the bound is usually far from reality.
    """
    bounds = model.project.bounds
    rod_d = model.project.rod.diameter
    d = rod_d + model.gap
    w = bounds.width - 2 * bounds.rod_margin - rod_d
    h = bounds.height - 2 * bounds.rod_margin - rod_d
    if w < -EPS or h < -EPS:
        return 0
    w, h = max(w, 0.0), max(h, 0.0)
    bound = 2.0 / math.sqrt(3.0) * (w * h) / d ** 2 + (2.0 * (w + h)) / (2.0 * d) + 1.0
    return int(math.floor(bound + 1e-9))
