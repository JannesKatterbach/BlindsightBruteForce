"""2D and 2.5D geometry without external dependencies.

All parts are represented as prisms. A prism consists of a convex 2D footprint (circle or convex
polygon) and a z interval. The distance computation returns the true Euclidean minimum distance in
space (not just centre distances).

Conventions
  * Lengths in mm, angles in radians (parameters are called ``angle_rad``).
  * Polygons are oriented counter clockwise (positive area).
  * The helpers here are also used by the configuration and the sketch, so every formula
    (area, hull, convexity, SAT) exists only once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Point = tuple[float, float]
BBox = tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)

CIRCLE_OUTLINE_SEGMENTS = 48  # polygon approximation of a circle for display and export


class Footprint:
    """Convex 2D footprint.

    kind is ``"c"`` (circle with centre cx, cy and radius r) or ``"p"`` (polygon, corners in
    ``pts`` counter clockwise, cx, cy = mean of the corners). ``bbox`` is exact for both kinds.
    """

    __slots__ = ("kind", "pts", "cx", "cy", "r", "bbox")

    def __init__(self, kind: str, pts: tuple[Point, ...], cx: float, cy: float, r: float):
        self.kind = kind
        self.pts = pts
        self.cx = cx
        self.cy = cy
        self.r = r
        if kind == "c":
            self.bbox = (cx - r, cy - r, cx + r, cy + r)
        else:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            self.bbox = (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def circle(cx: float, cy: float, r: float) -> "Footprint":
        if r < 0:
            raise ValueError("radius must not be negative")
        return Footprint("c", (), cx, cy, r)

    @staticmethod
    def polygon(pts: Sequence[Point]) -> "Footprint":
        """Polygon from corner points. Points given clockwise are reversed."""
        pts = tuple((float(x), float(y)) for x, y in pts)
        if len(pts) < 3:
            raise ValueError("a polygon needs at least 3 points")
        if signed_area(pts) < 0:
            pts = tuple(reversed(pts))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return Footprint("p", pts, cx, cy, 0.0)

    @staticmethod
    def rect(cx: float, cy: float, w: float, d: float, angle_rad: float = 0.0) -> "Footprint":
        """Rectangle w (x) by d (y) centred at (cx, cy), rotated by angle_rad."""
        return Footprint.polygon(rect_corners(cx, cy, w, d, angle_rad))

    def outline(self) -> list[Point]:
        """Points of the outline (a circle is approximated by a polygon, for display only)."""
        if self.kind == "c":
            n = CIRCLE_OUTLINE_SEGMENTS
            return [
                (self.cx + self.r * math.cos(2 * math.pi * i / n), self.cy + self.r * math.sin(2 * math.pi * i / n))
                for i in range(n)
            ]
        return list(self.pts)


# ---------------------------------------------------------------------------
# Basic formulas
# ---------------------------------------------------------------------------
def cross(o: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    """z component of (a - o) x (b - o). Positive when o, a, b are counter clockwise."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def signed_area(pts: Sequence[Sequence[float]]) -> float:
    """Signed area (shoelace formula). Positive for counter clockwise polygons."""
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


_signed_area = signed_area  # name from earlier versions


def polygon_area(pts: Sequence[Point]) -> float:
    """Absolute area (0 for fewer than 3 points)."""
    return abs(signed_area(pts)) if len(pts) >= 3 else 0.0


def rotate(x: float, y: float, angle_rad: float) -> Point:
    """Rotate the vector (x, y) about the origin (counter clockwise)."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (x * c - y * s, x * s + y * c)


def rotate_point(px: float, py: float, ox: float, oy: float, angle_rad: float) -> Point:
    """Rotate (px, py) about the point (ox, oy) by angle_rad (counter clockwise)."""
    dx, dy = rotate(px - ox, py - oy, angle_rad)
    return (ox + dx, oy + dy)


def rect_corners(cx: float, cy: float, w: float, d: float, angle_rad: float = 0.0) -> list[Point]:
    """Corners of a rotated rectangle centred at (cx, cy) (counter clockwise)."""
    hw, hd = w / 2.0, d / 2.0
    out = []
    for lx, ly in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        rx, ry = rotate(lx, ly, angle_rad)
        out.append((cx + rx, cy + ry))
    return out


def convex_hull_indices(points: Sequence[Sequence[float]]) -> list[int]:
    """Indices of the convex hull (monotone chain), counter clockwise, without collinear points."""
    order = sorted(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    if len(order) <= 2:
        return order

    def half(indices):
        chain: list[int] = []
        for i in indices:
            while len(chain) >= 2 and cross(points[chain[-2]], points[chain[-1]], points[i]) <= 0:
                chain.pop()
            chain.append(i)
        return chain

    lower = half(order)
    upper = half(reversed(order))
    return lower[:-1] + upper[:-1]


def convex_hull(points: Sequence[Point]) -> list[Point]:
    """Convex hull as a list of points (duplicate points are removed first)."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts
    return [pts[i] for i in convex_hull_indices(pts)]


def is_convex_ccw(pts: Sequence[Sequence[float]], rel_tol: float = 1e-9) -> bool:
    """True if the (counter clockwise) polygon does not turn right at any corner.

    The tolerance is relative to the product of the edge lengths, collinear points are allowed."""
    n = len(pts)
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        d1 = (b[0] - a[0], b[1] - a[1])
        d2 = (c[0] - b[0], c[1] - b[1])
        turn = d1[0] * d2[1] - d1[1] * d2[0]
        if turn < -rel_tol * math.hypot(*d1) * math.hypot(*d2):
            return False
    return True


# ---------------------------------------------------------------------------
# Distance computation
# ---------------------------------------------------------------------------
def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = min(1.0, max(0.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_in_convex(px: float, py: float, pts: Sequence[Point]) -> bool:
    """True if the point lies inside (or on the boundary of) the convex polygon."""
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1) < 0.0:
            return False
    return True


def point_polygon_distance(px: float, py: float, pts: Sequence[Point]) -> float:
    """Distance of a point to a convex polygon (0 inside)."""
    if point_in_convex(px, py, pts):
        return 0.0
    n = len(pts)
    return min(_point_segment_distance(px, py, *pts[i], *pts[(i + 1) % n]) for i in range(n))


def sat_penetration(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """Smallest overlap of the projections of two convex polygons (separating axis theorem).

    0 or negative means separated or only touching, positive is the penetration depth in mm."""
    best = math.inf
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i][0], poly[i][1]
            x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
            nx, ny = y2 - y1, x1 - x2
            length = math.hypot(nx, ny)
            if length == 0:
                continue
            nx, ny = nx / length, ny / length
            proj_a = [nx * p[0] + ny * p[1] for p in a]
            proj_b = [nx * p[0] + ny * p[1] for p in b]
            overlap = min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b))
            if overlap < 0:
                return overlap
            best = min(best, overlap)
    return best if best != math.inf else 0.0


def polygon_distance(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Exact minimum distance of two convex polygons (0 when overlapping or touching)."""
    if sat_penetration(a, b) >= 0:
        return 0.0
    best = math.inf
    for poly_p, poly_q in ((a, b), (b, a)):
        n = len(poly_q)
        for px, py in poly_p:
            for i in range(n):
                best = min(best, _point_segment_distance(px, py, *poly_q[i], *poly_q[(i + 1) % n]))
    return best


def bbox_gap(a: BBox, b: BBox) -> float:
    """Lower bound of the distance of two footprints from their bounding boxes."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def footprint_distance(first: Footprint, second: Footprint) -> float:
    """Exact 2D minimum distance of two footprints (0 when overlapping)."""
    if first.kind == "c" and second.kind == "c":
        return max(0.0, math.hypot(first.cx - second.cx, first.cy - second.cy) - first.r - second.r)
    if first.kind == "c":
        return max(0.0, point_polygon_distance(first.cx, first.cy, second.pts) - first.r)
    if second.kind == "c":
        return max(0.0, point_polygon_distance(second.cx, second.cy, first.pts) - second.r)
    return polygon_distance(first.pts, second.pts)


@dataclass(frozen=True)
class Prism:
    """Extruded footprint with the z interval [z0, z1]."""

    fp: Footprint
    z0: float
    z1: float

    def __post_init__(self):
        if self.z1 < self.z0:
            raise ValueError("z1 must be >= z0")


def z_gap(z0a: float, z1a: float, z0b: float, z1b: float) -> float:
    """Vertical distance of two intervals (negative when overlapping)."""
    return max(z0a - z1b, z0b - z1a)


def prism_distance(a: Prism, b: Prism, cutoff: float = math.inf) -> float:
    """Euclidean minimum distance of two prisms in space.

    If a cheap lower bound (z distance, bounding box) is already >= cutoff, that bound is returned
    and the exact computation is skipped. Results >= cutoff are therefore only lower bounds,
    results < cutoff are exact.
    """
    zg = max(z_gap(a.z0, a.z1, b.z0, b.z1), 0.0)
    if zg >= cutoff:
        return zg
    lower = math.hypot(zg, bbox_gap(a.fp.bbox, b.fp.bbox))
    if lower >= cutoff:
        return lower
    return math.hypot(zg, footprint_distance(a.fp, b.fp))
