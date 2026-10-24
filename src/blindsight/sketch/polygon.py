"""Evaluation of the sketch outline. Measures, validity (self intersection, convexity) and gear overlap."""

from __future__ import annotations

import math

from ..geometry import cross, is_convex_ccw, sat_penetration, signed_area
from ..i18n import tr
from ..units import EPS_AREA
from .constraints import EPS_LEN

INTERSECT_TOL = 1e-12  # orientation test of the side intersection (mm^2)
WINDING_TOL = 1e-6  # deviation of the total turn from 360 degrees (rad)
GEAR_OVERLAP_TOL = 1e-6  # from this penetration depth (mm) on the gear reaches into the housing


def _segments_cross(p1, p2, p3, p4) -> bool:
    """True if the segments p1p2 and p3p4 properly intersect (touching does not count)."""
    def opposite(u: float, v: float) -> bool:
        return (u > INTERSECT_TOL and v < -INTERSECT_TOL) or (u < -INTERSECT_TOL and v > INTERSECT_TOL)

    return opposite(cross(p3, p4, p1), cross(p3, p4, p2)) and opposite(cross(p1, p2, p3), cross(p1, p2, p4))


def _has_crossing_sides(pts: list) -> bool:
    n = len(pts)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # neighbours across the closing of the outline
            if _segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return True
    return False


def _total_turn(pts: list) -> float:
    """Sum of the turning angles along the outline (2 pi for a simple counter clockwise polygon)."""
    n = len(pts)
    turn = 0.0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        d1 = (b[0] - a[0], b[1] - a[1])
        d2 = (c[0] - b[0], c[1] - b[1])
        turn += math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
    return turn


def side_lengths(pts: list) -> list[float]:
    n = len(pts)
    return [math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]) for i in range(n)]


def polygon_report(pts: list[list[float]]) -> dict:
    """Check a counter clockwise polygon for short sides, self intersection and convexity.

    Returns {min_side, simple, convex, area, problems}."""
    out = {"min_side": min(side_lengths(pts)), "simple": True, "convex": True, "area": signed_area(pts), "problems": []}
    if out["min_side"] < EPS_LEN:
        out["problems"].append(tr("polygon.zero_side"))
        out["simple"] = out["convex"] = False
        return out
    if out["area"] <= EPS_AREA:
        out["problems"].append(tr("polygon.no_area"))
        out["simple"] = out["convex"] = False
        return out
    # A total turn other than 360 degrees means the outline winds several times (intersects itself)
    winds_once = abs(_total_turn(pts) - 2 * math.pi) <= WINDING_TOL
    out["simple"] = winds_once and not _has_crossing_sides(pts)
    out["convex"] = winds_once and is_convex_ccw(pts)
    if not out["simple"]:
        out["problems"].append(tr("polygon.self_intersection"))
    if not out["convex"]:
        out["problems"].append(tr("polygon.not_convex"))
    return out


def penetration(a: list, b: list) -> float:
    """Penetration depth of two convex polygons (SAT). Greater than 0 means a real overlap, touching is 0."""
    return max(0.0, sat_penetration(a, b))


def gear_box(cd: float, gear_diameter: float, gear_width: float) -> list[list[float]]:
    """Gear as a box in the rod frame (centre at (-cd, 0), shaft parallel to y)."""
    r, h = gear_diameter / 2.0, gear_width / 2.0
    return [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]]


def gear_overlap_message(pts: list, cd_nominal: float, cd: float, gear_diameter: float, gear_width: float) -> str:
    """Message if the gear reaches into the housing (housing shifted for centre distance cd compared to the nominal one)."""
    shift = cd_nominal - cd
    shifted = [[x + shift, y] for x, y in pts]
    depth = penetration(shifted, gear_box(cd, gear_diameter, gear_width))
    if depth > GEAR_OVERLAP_TOL:
        return tr("polygon.gear_overlap", depth=depth, cd=cd)
    return ""


def measures(pts: list[list[float]]) -> dict:
    """Lengths of all sides and interior angles at all points (degrees, 0 to 360)."""
    n = len(pts)
    angles = []
    for i in range(n):
        p, q, r = pts[i - 1], pts[i], pts[(i + 1) % n]
        to_prev = (p[0] - q[0], p[1] - q[1])
        to_next = (r[0] - q[0], r[1] - q[1])
        angle = math.degrees(math.atan2(
            to_next[0] * to_prev[1] - to_next[1] * to_prev[0], to_prev[0] * to_next[0] + to_prev[1] * to_next[1]
        ))
        angles.append(angle if angle >= 0 else angle + 360.0)
    return {"sides": side_lengths(pts), "angles": angles}


def bounding_box(pts: list) -> dict:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}
