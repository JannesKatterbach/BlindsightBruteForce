"""Candidate generation. Regular patterns of rod positions.

Extending. A new pattern is a function ``(pitch, region) -> points`` and an entry in ``PATTERNS``.
The configuration checks ``search.patterns`` against this registry, the optimizer calls the function
through ``pattern_points``. New orders (how a block around the centre is filled) are an entry in
``ORDER_TABLE``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from .units import EPS

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1)
PointList = list[tuple[float, float]]

ROW_FACTOR_HEX = math.sqrt(3) / 2.0  # row distance of a hexagonal lattice relative to the pitch


def _count(span: float, step: float) -> int:
    """How many steps fit into the span (rounding noise is tolerated)."""
    return int(math.floor(span / step + EPS))


def _square(pitch: float, region: Rect) -> PointList:
    """Square grid, symmetric about the centre of the region."""
    x0, y0, x1, y1 = region
    nx, ny = _count(x1 - x0, pitch), _count(y1 - y0, pitch)
    ox = (x0 + x1) / 2.0 - nx * pitch / 2.0
    oy = (y0 + y1) / 2.0 - ny * pitch / 2.0
    return [(ox + i * pitch, oy + j * pitch) for j in range(ny + 1) for i in range(nx + 1)]


def _hex_rows(pitch: float, along: tuple[float, float], across: tuple[float, float]) -> list[tuple[float, float]]:
    """Hexagonal lattice in a local frame (u along the rows, v across them).

    All rows share one origin, every second row is shifted by pitch/2. So all neighbours are exactly
    pitch apart (equilateral triangles)."""
    u0, u1 = along
    v0, v1 = across
    row_gap = pitch * ROW_FACTOR_HEX
    n_rows = _count(v1 - v0, row_gap)
    n_cols = _count(u1 - u0, pitch)
    v_start = (v0 + v1) / 2.0 - n_rows * row_gap / 2.0
    u_start = (u0 + u1) / 2.0 - n_cols * pitch / 2.0
    out = []
    for j in range(n_rows + 1):
        if j % 2 == 0:
            us = [u_start + i * pitch for i in range(n_cols + 1)]
        else:
            us = [u_start + pitch / 2.0 + i * pitch for i in range(n_cols)]
        out.extend((u, v_start + j * row_gap) for u in us)
    return out


def _hex_x(pitch: float, region: Rect) -> PointList:
    """Hexagonal, rows along x, every second row shifted by pitch/2."""
    x0, y0, x1, y1 = region
    return _hex_rows(pitch, (x0, x1), (y0, y1))


def _hex_y(pitch: float, region: Rect) -> PointList:
    """Hexagonal, columns along y, every second column shifted by pitch/2."""
    x0, y0, x1, y1 = region
    return [(u, v) for v, u in _hex_rows(pitch, (y0, y1), (x0, x1))]


PATTERNS: dict[str, Callable[[float, Rect], PointList]] = {
    "square": _square,
    "hex_x": _hex_x,
    "hex_y": _hex_y,
}

# density relative to the square grid (points per area), for estimating the point count
PATTERN_DENSITY = {"square": 1.0, "hex_x": 1.0 / ROW_FACTOR_HEX, "hex_y": 1.0 / ROW_FACTOR_HEX}


def pattern_points(kind: str, pitch: float, region: Rect) -> PointList:
    """Lattice points of pattern ``kind`` in region = (x0, y0, x1, y1), centred in the region."""
    x0, y0, x1, y1 = region
    if x1 < x0 or y1 < y0 or pitch <= 0:
        return []
    try:
        generator = PATTERNS[kind]
    except KeyError:
        raise ValueError(f"unknown pattern {kind}") from None
    return generator(pitch, region)


def estimated_point_count(kind: str, pitch: float, region: Rect) -> float:
    """Rough estimate of the point count without generating the points."""
    x0, y0, x1, y1 = region
    if pitch <= 0 or x1 < x0 or y1 < y0:
        return 0.0
    return (math.floor((x1 - x0) / pitch) + 1) * (math.floor((y1 - y0) / pitch) + 1) * PATTERN_DENSITY.get(kind, 1.0)


# ---------------------------------------------------------------------------
# Order of the points. A block grows from the centre outwards.
#   euclid    roundish block (distance to the centre)
#   box A     rectangular block with aspect ratio A (width / height)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Order:
    name: str
    shape: str  # "euclid" or "box"
    aspect: float = 1.0


ORDER_TABLE = (
    Order("euclid", "euclid"),
    Order("box1", "box", 1.0),
    Order("box1.5", "box", 1.5),
    Order("box0.67", "box", 0.67),
)
ORDERS = tuple(o.name for o in ORDER_TABLE)  # names in a fixed order (the first two are the fast ones)
_ORDER_BY_NAME = {o.name: o for o in ORDER_TABLE}


def order_points(points: Iterable[tuple[float, float]], center: tuple[float, float], order: str) -> PointList:
    """Sort points from the centre outwards so that a compact block emerges."""
    cx, cy = center
    spec = _ORDER_BY_NAME[order]

    def radial(p):
        return math.hypot(p[0] - cx, p[1] - cy)

    def round_block(p):
        return (radial(p), p[1], p[0])

    def box_block(p):
        return (max(abs(p[0] - cx) / spec.aspect, abs(p[1] - cy)), radial(p), p[1], p[0])

    return sorted(points, key=round_block if spec.shape == "euclid" else box_block)
