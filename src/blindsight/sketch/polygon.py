"""Auswertung der Skizzenkontur. Masse, Gueltigkeit (Selbstschnitt, Konvexitaet) und Zahnrad Ueberlappung."""

from __future__ import annotations

import math

from ..geometry import cross, is_convex_ccw, sat_penetration, signed_area
from ..units import EPS_AREA
from .constraints import EPS_LEN

INTERSECT_TOL = 1e-12  # Orientierungstest beim Seitenschnitt (mm^2)
WINDING_TOL = 1e-6  # Abweichung der Gesamtdrehung von 360 Grad (rad)
GEAR_OVERLAP_TOL = 1e-6  # ab dieser Eindringtiefe (mm) ragt das Zahnrad ins Gehaeuse

MSG_ZERO_SIDE = "Zwei Punkte liegen aufeinander (Seite der Länge 0)"
MSG_NO_AREA = "Die Kontur hat keine Fläche oder ist im Uhrzeigersinn orientiert"
MSG_SELF_INTERSECTION = "Die Kontur schneidet sich selbst"
MSG_NOT_CONVEX = "Die Kontur ist nicht konvex (das Modell braucht ein konvexes Gehäuse, siehe Konvexe Hülle)"


def _segments_cross(p1, p2, p3, p4) -> bool:
    """True, wenn sich die Strecken p1p2 und p3p4 echt schneiden (Beruehren zaehlt nicht)."""
    def opposite(u: float, v: float) -> bool:
        return (u > INTERSECT_TOL and v < -INTERSECT_TOL) or (u < -INTERSECT_TOL and v > INTERSECT_TOL)

    return opposite(cross(p3, p4, p1), cross(p3, p4, p2)) and opposite(cross(p1, p2, p3), cross(p1, p2, p4))


def _has_crossing_sides(pts: list) -> bool:
    n = len(pts)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # benachbart ueber den Schluss der Kontur
            if _segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return True
    return False


def _total_turn(pts: list) -> float:
    """Summe der Abbiegewinkel entlang der Kontur (2 pi fuer ein einfaches Polygon gegen den Uhrzeigersinn)."""
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
    """Prueft ein gegen den Uhrzeigersinn orientiertes Polygon auf kurze Seiten, Selbstschnitt und Konvexitaet.

    Rueckgabe {min_side, simple, convex, area, problems}."""
    out = {"min_side": min(side_lengths(pts)), "simple": True, "convex": True, "area": signed_area(pts), "problems": []}
    if out["min_side"] < EPS_LEN:
        out["problems"].append(MSG_ZERO_SIDE)
        out["simple"] = out["convex"] = False
        return out
    if out["area"] <= EPS_AREA:
        out["problems"].append(MSG_NO_AREA)
        out["simple"] = out["convex"] = False
        return out
    # Eine Gesamtdrehung ungleich 360 Grad heisst, die Kontur windet sich mehrfach (schneidet sich)
    winds_once = abs(_total_turn(pts) - 2 * math.pi) <= WINDING_TOL
    out["simple"] = winds_once and not _has_crossing_sides(pts)
    out["convex"] = winds_once and is_convex_ccw(pts)
    if not out["simple"]:
        out["problems"].append(MSG_SELF_INTERSECTION)
    if not out["convex"]:
        out["problems"].append(MSG_NOT_CONVEX)
    return out


def penetration(a: list, b: list) -> float:
    """Eindringtiefe zweier konvexer Polygone (SAT). Groesser 0 heisst echte Ueberlappung, Beruehren ist 0."""
    return max(0.0, sat_penetration(a, b))


def gear_box(cd: float, gear_diameter: float, gear_width: float) -> list[list[float]]:
    """Zahnrad als Quader im Stangenrahmen (Mitte bei (-cd, 0), Welle parallel zu y)."""
    r, h = gear_diameter / 2.0, gear_width / 2.0
    return [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]]


def gear_overlap_message(pts: list, cd_nominal: float, cd: float, gear_diameter: float, gear_width: float) -> str:
    """Meldung, wenn das Zahnrad in das Gehaeuse ragt (Gehaeuse bei Achsabstand cd gegenueber dem nominalen verschoben)."""
    shift = cd_nominal - cd
    shifted = [[x + shift, y] for x, y in pts]
    depth = penetration(shifted, gear_box(cd, gear_diameter, gear_width))
    if depth > GEAR_OVERLAP_TOL:
        return f"Das Zahnrad ragt {depth:.2f} mm in das Gehäuse (Achsabstand {cd:g} mm)"
    return ""


def measures(pts: list[list[float]]) -> dict:
    """Laengen aller Seiten und Innenwinkel an allen Punkten (Grad, 0 bis 360)."""
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
