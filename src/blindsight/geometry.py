"""2D und 2.5D Geometrie ohne externe Abhaengigkeiten.

Alle Bauteile werden als Prismen dargestellt. Ein Prisma besteht aus einem
konvexen 2D Grundriss (Kreis oder konvexes Polygon) und einem Z Intervall.
Die Abstandsberechnung liefert den echten euklidischen Mindestabstand im Raum
(nicht nur Mittelpunktabstaende).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Point = tuple[float, float]


class Footprint:
    """Konvexer 2D Grundriss. kind ist 'c' (Kreis) oder 'p' (Polygon, CCW)."""

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
            raise ValueError("Radius darf nicht negativ sein")
        return Footprint("c", (), cx, cy, r)

    @staticmethod
    def polygon(pts: Sequence[Point]) -> "Footprint":
        pts = tuple((float(x), float(y)) for x, y in pts)
        if len(pts) < 3:
            raise ValueError("Polygon braucht mindestens 3 Punkte")
        if _signed_area(pts) < 0:
            pts = tuple(reversed(pts))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return Footprint("p", pts, cx, cy, 0.0)

    @staticmethod
    def rect(cx: float, cy: float, w: float, d: float, angle: float = 0.0) -> "Footprint":
        """Um (cx, cy) zentriertes Rechteck w (x) mal d (y), gedreht um angle (rad)."""
        return Footprint.polygon(rect_corners(cx, cy, w, d, angle))

    def outline(self) -> list[Point]:
        """Punkte der Kontur (Kreis wird als 48-Eck angenaehert, nur fuer Darstellung)."""
        if self.kind == "c":
            return [
                (self.cx + self.r * math.cos(2 * math.pi * i / 48), self.cy + self.r * math.sin(2 * math.pi * i / 48))
                for i in range(48)
            ]
        return list(self.pts)


def _signed_area(pts: Sequence[Point]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def rect_corners(cx: float, cy: float, w: float, d: float, angle: float = 0.0) -> list[Point]:
    c, s = math.cos(angle), math.sin(angle)
    hw, hd = w / 2.0, d / 2.0
    out = []
    for lx, ly in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        out.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return out


def rotate_point(px: float, py: float, ox: float, oy: float, angle: float) -> Point:
    """Dreht (px, py) um den Punkt (ox, oy) um angle (rad, gegen den Uhrzeigersinn)."""
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = px - ox, py - oy
    return (ox + dx * c - dy * s, oy + dx * s + dy * c)


# ---------------------------------------------------------------------------
# Abstandsberechnung
# ---------------------------------------------------------------------------

def _point_seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_in_convex(px: float, py: float, pts: Sequence[Point]) -> bool:
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1) < 0.0:
            return False
    return True


def point_polygon_distance(px: float, py: float, pts: Sequence[Point]) -> float:
    if point_in_convex(px, py, pts):
        return 0.0
    n = len(pts)
    best = math.inf
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        d = _point_seg_dist(px, py, x1, y1, x2, y2)
        if d < best:
            best = d
    return best


def _sat_overlap(a: Sequence[Point], b: Sequence[Point]) -> bool:
    """True, wenn sich zwei konvexe Polygone (auch beruehrend) ueberlappen."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            nx, ny = y2 - y1, x1 - x2
            amin = min(nx * p[0] + ny * p[1] for p in a)
            amax = max(nx * p[0] + ny * p[1] for p in a)
            bmin = min(nx * p[0] + ny * p[1] for p in b)
            bmax = max(nx * p[0] + ny * p[1] for p in b)
            if amax < bmin or bmax < amin:
                return False
    return True


def polygon_distance(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Exakter Mindestabstand zweier konvexer Polygone (0 bei Ueberlappung)."""
    if _sat_overlap(a, b):
        return 0.0
    best = math.inf
    for poly_p, poly_q in ((a, b), (b, a)):
        n = len(poly_q)
        for px, py in poly_p:
            for i in range(n):
                x1, y1 = poly_q[i]
                x2, y2 = poly_q[(i + 1) % n]
                d = _point_seg_dist(px, py, x1, y1, x2, y2)
                if d < best:
                    best = d
    return best


def bbox_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Untere Schranke des Abstands zweier Grundrisse aus den Bounding Boxen."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def footprint_distance(f: Footprint, g: Footprint) -> float:
    """Exakter 2D Mindestabstand zweier Grundrisse (0 bei Ueberlappung)."""
    if f.kind == "c" and g.kind == "c":
        return max(0.0, math.hypot(f.cx - g.cx, f.cy - g.cy) - f.r - g.r)
    if f.kind == "c":
        return max(0.0, point_polygon_distance(f.cx, f.cy, g.pts) - f.r)
    if g.kind == "c":
        return max(0.0, point_polygon_distance(g.cx, g.cy, f.pts) - g.r)
    return polygon_distance(f.pts, g.pts)


@dataclass(frozen=True)
class Prism:
    """Extrudierter Grundriss mit Z Intervall [z0, z1]."""

    fp: Footprint
    z0: float
    z1: float

    def __post_init__(self):
        if self.z1 < self.z0:
            raise ValueError("z1 muss >= z0 sein")


def z_gap(z0a: float, z1a: float, z0b: float, z1b: float) -> float:
    """Vertikaler Abstand zweier Intervalle (negativ bei Ueberlappung, dann 0 nutzen)."""
    return max(z0a - z1b, z0b - z1a)


def prism_distance(a: Prism, b: Prism, cutoff: float = math.inf) -> float:
    """Euklidischer Mindestabstand im Raum.

    Ist bereits eine untere Schranke >= cutoff, wird diese zurueckgegeben und
    auf die exakte Berechnung verzichtet (schnelles Verwerfen).
    """
    zg = max(z_gap(a.z0, a.z1, b.z0, b.z1), 0.0)
    if zg >= cutoff:
        return zg
    lb = bbox_gap(a.fp.bbox, b.fp.bbox)
    if math.hypot(zg, lb) >= cutoff:
        return math.hypot(zg, lb)
    return math.hypot(zg, footprint_distance(a.fp, b.fp))


def convex_hull(points: Sequence[Point]) -> list[Point]:
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_area(pts: Sequence[Point]) -> float:
    return abs(_signed_area(pts)) if len(pts) >= 3 else 0.0
