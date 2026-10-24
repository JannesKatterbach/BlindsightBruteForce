"""Scoring function. All objectives lie in [0, 1], 1 is best.

Total score = weighted mean (weights from WeightsSpec, normalised).
  count        placed number relative to the target number
  area         1 - used bounding box / available build area (share of free build area)
  uniformity   1 - 2 * coefficient of variation of the neighbour distances
  regularity   alignment of the neighbours to a square or hexagonal pattern
               (bond orientational order parameters psi4 and psi6)

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
from typing import Callable, Optional

from .config import WeightsSpec
from .geometry import BBox, convex_hull, polygon_area
from .layout import Placement
from .model import KIND_ROD, Model
from .units import EPS, EPS_AREA

UNIFORMITY_CV_FACTOR = 2.0  # a coefficient of variation of 0.5 gives uniformity 0
ORDER_NEIGHBORS = (4, 6)  # psi4 (square) and psi6 (hexagon)


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


OBJECTIVES: dict[str, Callable[[LayoutStats], float]] = {
    "count": _count_term,
    "area": _area_term,
    "uniformity": _uniformity_term,
    "regularity": _regularity_term,
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def footprint_bbox(model: Model, placements: list[Placement]) -> BBox:
    """Bounding box of all parts of all units in top view."""
    boxes = [model.unit_bbox(pl.x, pl.y, pl.plane, pl.angle, pl.cd) for pl in placements]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _hull_area(model: Model, placements: list[Placement]) -> float:
    """Area of the convex hull of all housings and gears (rods as their centre)."""
    points = []
    for i, pl in enumerate(placements):
        for part in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            points.extend([(pl.x, pl.y)] if part.kind == KIND_ROD else part.prism.fp.outline())
    return polygon_area(convex_hull(points))


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
    bounds = model.project.bounds
    box = footprint_bbox(model, placements)
    nn, order = _neighbor_stats([(pl.x, pl.y) for pl in placements])
    return LayoutStats(
        count=len(placements),
        target=target,
        bounds_area=bounds.width * bounds.height,
        footprint=box,
        footprint_area=max((box[2] - box[0]) * (box[3] - box[1]), EPS_AREA),
        hull_area=_hull_area(model, placements),
        nn_distances=nn,
        order=order,
    )


def normalized_weights(weights: WeightsSpec) -> dict[str, float]:
    raw = weights.as_dict()
    total = sum(raw.values())
    return {name: raw[name] / total for name in OBJECTIVES}


def evaluate(model: Model, placements: list[Placement], weights: WeightsSpec, target: int) -> Score:
    """Score a layout. Returns total, objectives, normalised weights and metrics."""
    wn = normalized_weights(weights)
    if not placements:
        return Score(0.0, {k: 0.0 for k in OBJECTIVES}, wn, {"count": 0})
    stats = layout_stats(model, placements, target)
    terms = {name: fn(stats) for name, fn in OBJECTIVES.items()}
    total = sum(wn[k] * terms[k] for k in terms)
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
        **{f"plane_{k}_units": v for k, v in sorted(planes_used.items())},
    }


def upper_bound_count(model: Model) -> int:
    """Strict upper bound of the number of rods (Oler's inequality).

    Any two rod axes are at least d = rod diameter + safety clearance apart (all rods overlap in
    height). The axes lie in the rectangle of permitted centres (build area minus edge margin and rod
    radius) with area A and perimeter P. For points with minimum distance d in a convex region
        N <= 2 / sqrt(3) * A / d^2 + P / (2 d) + 1
    Motors are ignored, so the bound is usually far from reality.
    """
    bounds = model.project.bounds
    rod_d = model.project.rod.diameter
    d = rod_d + model.gap
    w = bounds.width - 2 * bounds.edge_margin - rod_d
    h = bounds.height - 2 * bounds.edge_margin - rod_d
    if w < -EPS or h < -EPS:
        return 0
    w, h = max(w, 0.0), max(h, 0.0)
    bound = 2.0 / math.sqrt(3.0) * (w * h) / d ** 2 + (2.0 * (w + h)) / (2.0 * d) + 1.0
    return int(math.floor(bound + 1e-9))
