"""What the motor is made of. Housing hull and gear derived from a (solved) sketch.

Housing  convex hull of all normal entities except the gear. Construction geometry and sketch points do
         not count. Circles and arcs enter as circumscribed polygons, so the hull is conservative.
Gear     the four normal lines with role "gear". They must form an axis parallel rectangle whose centre
         lies on the x axis left of the rod (the shaft runs parallel to y). Derived are the gear diameter
         (extent in x), the gear width (extent in y) and the centre distance (distance of the centre to
         the rod axis).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..geometry import convex_hull, polygon_area, sat_penetration
from ..i18n import tr
from .entities import ROLE_GEAR, Point

CURVE_SEGMENTS = 48  # polygon of a full circle
AXIS_TOL = 1e-4  # mm, gear edges axis parallel and centre on the x axis
GEAR_OVERLAP_TOL = 1e-6  # mm, from this penetration on the gear reaches into the housing
MIN_AREA = 1e-9


@dataclass
class Profile:
    housing: list[Point] = field(default_factory=list)  # convex, counter clockwise
    gear: Optional[dict] = None  # {xmin, ymin, xmax, ymax, diameter, width, center_distance}
    bbox: Optional[dict] = None  # of the housing
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"housing": [list(p) for p in self.housing], "gear": self.gear, "bbox": self.bbox}


def _arc_points(centre: Point, start: Point, end: Point) -> list[Point]:
    """Points of a circumscribed polygon of the arc from start to end (counter clockwise), plus both ends."""
    r = math.hypot(start[0] - centre[0], start[1] - centre[1])
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    n = max(2, math.ceil(CURVE_SEGMENTS * sweep / (2 * math.pi)))
    outer = r / math.cos(sweep / n / 2.0)
    pts = [start, end]
    for i in range(n):
        a = a0 + sweep * (i + 0.5) / n  # vertices of the circumscribed polygon lie between the samples
        pts.append((centre[0] + outer * math.cos(a), centre[1] + outer * math.sin(a)))
    return pts


def _circle_points(centre: Point, r: float) -> list[Point]:
    outer = r / math.cos(math.pi / CURVE_SEGMENTS)
    return [(centre[0] + outer * math.cos(2 * math.pi * (i + 0.5) / CURVE_SEGMENTS),
             centre[1] + outer * math.sin(2 * math.pi * (i + 0.5) / CURVE_SEGMENTS)) for i in range(CURVE_SEGMENTS)]


def entity_outline_points(sk: dict, e: dict) -> list[Point]:
    pts = sk["points"]
    if e["type"] == "line":
        return [tuple(pts[p]) for p in e["points"]]
    if e["type"] == "circle":
        return _circle_points(tuple(pts[e["points"][0]]), e["radius"])
    if e["type"] == "arc":
        c, s, t = (tuple(pts[p]) for p in e["points"])
        return _arc_points(c, s, t)
    return []


def profile(sk: dict) -> Profile:
    """Housing hull, gear and their problems for a solved sketch."""
    out = Profile()
    housing_pts: list[Point] = []
    gear_lines = []
    for e in sk["entities"]:
        if e["construction"] or e["type"] == "point":
            continue
        if e["role"] == ROLE_GEAR:
            if e["type"] == "line":
                gear_lines.append(e)
            continue
        housing_pts.extend(entity_outline_points(sk, e))
    hull = convex_hull(housing_pts) if housing_pts else []
    if len(hull) < 3 or polygon_area(hull) < MIN_AREA:
        out.errors.append(tr("profile.no_housing"))
    else:
        out.housing = [(float(x), float(y)) for x, y in hull]
        xs, ys = [p[0] for p in hull], [p[1] for p in hull]
        out.bbox = {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}
    out.gear = _gear(sk, gear_lines, out.errors)
    if out.gear and out.housing:
        box = [(out.gear["xmin"], out.gear["ymin"]), (out.gear["xmax"], out.gear["ymin"]),
               (out.gear["xmax"], out.gear["ymax"]), (out.gear["xmin"], out.gear["ymax"])]
        depth = max(0.0, sat_penetration(out.housing, box))
        if depth > GEAR_OVERLAP_TOL:
            out.errors.append(tr("polygon.gear_overlap", depth=depth, cd=out.gear["center_distance"]))
    return out


def _gear(sk: dict, lines: list[dict], errors: list) -> Optional[dict]:
    if not lines:
        errors.append(tr("profile.no_gear"))
        return None
    pts = [tuple(sk["points"][p]) for e in lines for p in e["points"]]
    straight = all(abs(sk["points"][e["points"][0]][0] - sk["points"][e["points"][1]][0]) < AXIS_TOL or
                   abs(sk["points"][e["points"][0]][1] - sk["points"][e["points"][1]][1]) < AXIS_TOL for e in lines)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    gear = {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}
    gear["diameter"], gear["width"] = gear["xmax"] - gear["xmin"], gear["ymax"] - gear["ymin"]
    cx, cy = (gear["xmin"] + gear["xmax"]) / 2.0, (gear["ymin"] + gear["ymax"]) / 2.0
    gear["center_distance"] = -cx
    if len(lines) != 4 or not straight or gear["diameter"] <= AXIS_TOL or gear["width"] <= AXIS_TOL:
        errors.append(tr("profile.gear_rectangle"))
        return None
    if abs(cy) > AXIS_TOL or cx >= 0:
        errors.append(tr("profile.gear_axis", x=cx, y=cy))
        return None
    return gear
