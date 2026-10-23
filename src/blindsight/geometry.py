"""2D und 2.5D Geometrie ohne externe Abhaengigkeiten.

Alle Bauteile werden als Prismen dargestellt. Ein Prisma besteht aus einem
konvexen 2D Grundriss (Kreis oder konvexes Polygon) und einem Z Intervall.
Die Abstandsberechnung liefert den echten euklidischen Mindestabstand im Raum
(nicht nur Mittelpunktabstaende).

Konventionen
  * Laengen in mm, Winkel in Radiant (Parameter heissen ``angle_rad``).
  * Polygone sind gegen den Uhrzeigersinn orientiert (positive Flaeche).
  * Die Hilfen hier werden auch von Konfiguration und Skizze genutzt, damit es
    jede Formel (Flaeche, Huelle, Konvexitaet, SAT) nur einmal gibt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Point = tuple[float, float]
BBox = tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)

CIRCLE_OUTLINE_SEGMENTS = 48  # Naeherung eines Kreises fuer Darstellung und Export


class Footprint:
    """Konvexer 2D Grundriss.

    kind ist ``"c"`` (Kreis mit Mittelpunkt cx, cy und Radius r) oder ``"p"``
    (Polygon, Eckpunkte in ``pts`` gegen den Uhrzeigersinn, cx, cy = Eckenmittel).
    ``bbox`` ist bei beiden Arten exakt.
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
            raise ValueError("Radius darf nicht negativ sein")
        return Footprint("c", (), cx, cy, r)

    @staticmethod
    def polygon(pts: Sequence[Point]) -> "Footprint":
        """Polygon aus Eckpunkten. Im Uhrzeigersinn uebergebene Punkte werden umgedreht."""
        pts = tuple((float(x), float(y)) for x, y in pts)
        if len(pts) < 3:
            raise ValueError("Polygon braucht mindestens 3 Punkte")
        if signed_area(pts) < 0:
            pts = tuple(reversed(pts))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return Footprint("p", pts, cx, cy, 0.0)

    @staticmethod
    def rect(cx: float, cy: float, w: float, d: float, angle_rad: float = 0.0) -> "Footprint":
        """Um (cx, cy) zentriertes Rechteck w (x) mal d (y), gedreht um angle_rad."""
        return Footprint.polygon(rect_corners(cx, cy, w, d, angle_rad))

    def outline(self) -> list[Point]:
        """Punkte der Kontur (ein Kreis wird als Vieleck angenaehert, nur fuer Darstellung)."""
        if self.kind == "c":
            n = CIRCLE_OUTLINE_SEGMENTS
            return [
                (self.cx + self.r * math.cos(2 * math.pi * i / n), self.cy + self.r * math.sin(2 * math.pi * i / n))
                for i in range(n)
            ]
        return list(self.pts)


# ---------------------------------------------------------------------------
# Grundformeln
# ---------------------------------------------------------------------------
def cross(o: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    """z Komponente von (a - o) x (b - o). Positiv, wenn o, a, b gegen den Uhrzeigersinn liegen."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def signed_area(pts: Sequence[Sequence[float]]) -> float:
    """Vorzeichenbehaftete Flaeche (Gausssche Trapezformel). Positiv gegen den Uhrzeigersinn."""
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


_signed_area = signed_area  # Name aus frueheren Versionen


def polygon_area(pts: Sequence[Point]) -> float:
    """Betrag der Flaeche (0 fuer weniger als 3 Punkte)."""
    return abs(signed_area(pts)) if len(pts) >= 3 else 0.0


def rotate(x: float, y: float, angle_rad: float) -> Point:
    """Dreht den Vektor (x, y) um den Ursprung (gegen den Uhrzeigersinn)."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (x * c - y * s, x * s + y * c)


def rotate_point(px: float, py: float, ox: float, oy: float, angle_rad: float) -> Point:
    """Dreht (px, py) um den Punkt (ox, oy) um angle_rad (gegen den Uhrzeigersinn)."""
    dx, dy = rotate(px - ox, py - oy, angle_rad)
    return (ox + dx, oy + dy)


def rect_corners(cx: float, cy: float, w: float, d: float, angle_rad: float = 0.0) -> list[Point]:
    """Ecken eines um (cx, cy) zentrierten, gedrehten Rechtecks (gegen den Uhrzeigersinn)."""
    hw, hd = w / 2.0, d / 2.0
    out = []
    for lx, ly in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        rx, ry = rotate(lx, ly, angle_rad)
        out.append((cx + rx, cy + ry))
    return out


def convex_hull_indices(points: Sequence[Sequence[float]]) -> list[int]:
    """Indizes der konvexen Huelle (Monotone Chain), gegen den Uhrzeigersinn, ohne kollineare Punkte."""
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
    """Konvexe Huelle als Punktliste (doppelte Punkte werden vorher entfernt)."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts
    return [pts[i] for i in convex_hull_indices(pts)]


def is_convex_ccw(pts: Sequence[Sequence[float]], rel_tol: float = 1e-9) -> bool:
    """True, wenn das (gegen den Uhrzeigersinn orientierte) Polygon an keiner Ecke nach rechts abknickt.

    Die Toleranz ist relativ zum Produkt der Kantenlaengen, kollineare Punkte sind erlaubt."""
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
# Abstandsberechnung
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
    """True, wenn der Punkt im (oder auf dem Rand des) konvexen Polygon liegt."""
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1) < 0.0:
            return False
    return True


def point_polygon_distance(px: float, py: float, pts: Sequence[Point]) -> float:
    """Abstand eines Punktes zu einem konvexen Polygon (0 innerhalb)."""
    if point_in_convex(px, py, pts):
        return 0.0
    n = len(pts)
    return min(_point_segment_distance(px, py, *pts[i], *pts[(i + 1) % n]) for i in range(n))


def sat_penetration(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """Kleinste Ueberlappung der Projektionen zweier konvexer Polygone (Satz der trennenden Achsen).

    0 oder negativ heisst getrennt oder nur beruehrend, positiv ist die Eindringtiefe in mm."""
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
    """Exakter Mindestabstand zweier konvexer Polygone (0 bei Ueberlappung oder Beruehrung)."""
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
    """Untere Schranke des Abstands zweier Grundrisse aus den Bounding Boxen."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def footprint_distance(first: Footprint, second: Footprint) -> float:
    """Exakter 2D Mindestabstand zweier Grundrisse (0 bei Ueberlappung)."""
    if first.kind == "c" and second.kind == "c":
        return max(0.0, math.hypot(first.cx - second.cx, first.cy - second.cy) - first.r - second.r)
    if first.kind == "c":
        return max(0.0, point_polygon_distance(first.cx, first.cy, second.pts) - first.r)
    if second.kind == "c":
        return max(0.0, point_polygon_distance(second.cx, second.cy, first.pts) - second.r)
    return polygon_distance(first.pts, second.pts)


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
    """Vertikaler Abstand zweier Intervalle (negativ bei Ueberlappung)."""
    return max(z0a - z1b, z0b - z1a)


def prism_distance(a: Prism, b: Prism, cutoff: float = math.inf) -> float:
    """Euklidischer Mindestabstand zweier Prismen im Raum.

    Ist eine guenstige untere Schranke (Z Abstand, Bounding Box) bereits >= cutoff, wird
    diese Schranke zurueckgegeben und die exakte Rechnung gespart. Ergebnisse >= cutoff sind
    daher nur untere Schranken, Ergebnisse < cutoff sind exakt.
    """
    zg = max(z_gap(a.z0, a.z1, b.z0, b.z1), 0.0)
    if zg >= cutoff:
        return zg
    lower = math.hypot(zg, bbox_gap(a.fp.bbox, b.fp.bbox))
    if lower >= cutoff:
        return lower
    return math.hypot(zg, footprint_distance(a.fp, b.fp))
