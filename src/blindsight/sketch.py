"""Parametrische Skizze fuer die Motorkontur (Constraint Solver im CAD Stil).

Koordinatensystem. Ursprung ist die Achse der Gewindestange (Getriebestange), Einheit mm, y nach oben.
Der ganze Motor dreht bei der Platzierung um diesen Ursprung. Das Zahnrad liegt fest bei (-Achsabstand, 0),
seine Welle verlaeuft parallel zu y.

Die Skizze ist ein konvexes Polygon (Punkte gegen den Uhrzeigersinn).
  Seite i geht von Punkt i nach Punkt i+1 (zyklisch).
  Winkel an Punkt i ist der Innenwinkel zwischen Seite i-1 und Seite i.

Constraints (Feld type, Indizes a und b, Zahlenwerte value und value2, Referenz ref)
  length         Seite a hat die Laenge value
  angle          Innenwinkel an Punkt a ist value Grad (0 bis 180, exklusiv)
  angle_sides    Winkel zwischen den Richtungen der Seiten a und b ist value Grad (0 bis 180)
  parallel       Seiten a und b sind parallel (auch gegenlaeufig)
  perpendicular  Seiten a und b stehen senkrecht
  equal          Seiten a und b sind gleich lang
  horizontal     Seite a ist parallel zur x Achse
  vertical       Seite a ist parallel zur y Achse
  fix            Punkt a liegt bei (value, value2)
  coord_x        Punkt a hat die x Koordinate value
  coord_y        Punkt a hat die y Koordinate value
  dist_point     Abstand Punkt a zur Referenz ref (rod oder gear) ist value
  dist_side      Lotabstand der Geraden durch Seite a zur Referenz ref ist value

Der Solver loest die Gleichungen mit Levenberg Marquardt (reines Python, keine Abhaengigkeit) und bewegt die
Punkte dabei so wenig wie moeglich. Er meldet Freiheitsgrade, redundante und widerspruechliche Constraints.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

MIN_POINTS = 3
MAX_POINTS = 40
MAX_CONSTRAINTS = 150
TIME_LIMIT_S = 3.0  # Obergrenze der Rechenzeit eines Solver Aufrufs
TOL_SOLVE = 1e-9  # Abbruchkriterium des Newton Verfahrens
TOL_OK = 1e-6  # ab hier gilt ein Constraint als erfuellt
EPS_LEN = 1e-9  # kuerzeste erlaubte Seite

REFS = ("rod", "gear")
# Aufbau. name -> (Seitenfelder, Punktfelder, braucht value, braucht value2)
SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool, bool]] = {
    "length": (("a",), (), True, False),
    "angle": ((), ("a",), True, False),
    "angle_sides": (("a", "b"), (), True, False),
    "parallel": (("a", "b"), (), False, False),
    "perpendicular": (("a", "b"), (), False, False),
    "equal": (("a", "b"), (), False, False),
    "horizontal": (("a",), (), False, False),
    "vertical": (("a",), (), False, False),
    "fix": ((), ("a",), True, True),
    "coord_x": ((), ("a",), True, False),
    "coord_y": ((), ("a",), True, False),
    "dist_point": ((), ("a",), True, False),
    "dist_side": (("a",), (), True, False),
}
LABELS = {
    "length": "Laenge", "angle": "Winkel", "angle_sides": "Winkel zwischen Seiten", "parallel": "Parallel",
    "perpendicular": "Rechtwinklig", "equal": "Gleich lang", "horizontal": "Horizontal", "vertical": "Vertikal",
    "fix": "Fixiert", "coord_x": "x Koordinate", "coord_y": "y Koordinate", "dist_point": "Abstand Punkt",
    "dist_side": "Abstand Seite",
}


class SketchError(ValueError):
    """Ungueltige Skizze. errors enthaelt alle Probleme mit Feldpfad."""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# ---------------------------------------------------------------------------
# Datenhaltung. Die Skizze wird intern als Dictionary gefuehrt (JSON nah).
# ---------------------------------------------------------------------------
def constraint_dict(c: Any) -> dict:
    """Wandelt ein ConstraintSpec oder Dictionary in ein normiertes Dictionary."""
    get = (lambda k, d=None: c.get(k, d)) if isinstance(c, dict) else (lambda k, d=None: getattr(c, k, d))
    return {
        "type": get("type"), "a": get("a"), "b": get("b"), "value": get("value"), "value2": get("value2"),
        "ref": get("ref", "rod") or "rod", "enabled": bool(get("enabled", True)), "name": get("name", "") or "",
    }


def sketch_dict(sk: Any) -> dict:
    """Wandelt SketchSpec oder Dictionary in {points, constraints} mit Kopien."""
    if isinstance(sk, dict):
        pts, cons = sk.get("points", []), sk.get("constraints", [])
    else:
        pts, cons = sk.points, sk.constraints
    return {
        "points": [[p[0], p[1]] if isinstance(p, (list, tuple)) and len(p) == 2 else p for p in pts],
        "constraints": [constraint_dict(c) for c in cons],
    }


def _isnum(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_structure(sk: dict, prefix: str = "motor.sketch") -> list[str]:
    """Prueft Typen, Indizes und Wertebereiche. Gibt alle Fehler mit Feldpfad zurueck."""
    errs: list[str] = []
    pts, cons = sk["points"], sk["constraints"]
    if not isinstance(pts, list) or not isinstance(cons, list):
        return [f"{prefix}. points und constraints muessen Listen sein"]
    n = len(pts)
    if n < MIN_POINTS:
        errs.append(f"{prefix}.points. Mindestens {MIN_POINTS} Punkte noetig (sind {n})")
    if n > MAX_POINTS:
        errs.append(f"{prefix}.points. Hoechstens {MAX_POINTS} Punkte erlaubt (sind {n})")
    for i, p in enumerate(pts):
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(_isnum(v) for v in p)):
            errs.append(f"{prefix}.points[{i}]. Muss [x, y] mit endlichen Zahlen sein")
    if len(cons) > MAX_CONSTRAINTS:
        errs.append(f"{prefix}.constraints. Zu viele Constraints (max {MAX_CONSTRAINTS})")
        return errs
    for k, c in enumerate(cons):
        tag = f"{prefix}.constraints[{k}]"
        t = c["type"]
        if t not in SPEC:
            errs.append(f"{tag}.type. Unbekannter Typ '{t}'. Erlaubt. {sorted(SPEC)}")
            continue
        sides, verts, need_v, need_v2 = SPEC[t]
        for f in sides + verts:
            idx = c[f]
            if isinstance(idx, bool) or not isinstance(idx, int):
                errs.append(f"{tag}.{f}. Index muss eine ganze Zahl sein")
            elif not 0 <= idx < max(n, 1):
                errs.append(f"{tag}.{f}. {'Seite' if f in sides else 'Punkt'} {idx} existiert nicht (0..{n - 1})")
        if len(sides) == 2 and c["a"] == c["b"] and isinstance(c["a"], int):
            errs.append(f"{tag}. Die beiden Seiten muessen verschieden sein")
        if need_v and not _isnum(c["value"]):
            errs.append(f"{tag}.value. Zahl erforderlich")
        elif need_v2 and not _isnum(c["value2"]):
            errs.append(f"{tag}.value2. Zahl erforderlich")
        elif need_v:
            v = c["value"]
            if t == "length" and v <= EPS_LEN:
                errs.append(f"{tag}.value. Laenge muss groesser als 0 sein")
            if t == "angle" and not 0 < v < 180:
                errs.append(f"{tag}.value. Innenwinkel muss zwischen 0 und 180 Grad liegen (exklusiv)")
            if t == "angle_sides" and not 0 <= v <= 180:
                errs.append(f"{tag}.value. Winkel muss zwischen 0 und 180 Grad liegen")
            if t in ("dist_point", "dist_side") and v < 0:
                errs.append(f"{tag}.value. Abstand darf nicht negativ sein")
        if t in ("dist_point", "dist_side") and c["ref"] not in REFS:
            errs.append(f"{tag}.ref. Muss 'rod' oder 'gear' sein")
        if c["name"] is not None and not isinstance(c["name"], str):
            errs.append(f"{tag}.name. Muss Text sein")
    return errs


# ---------------------------------------------------------------------------
# Geometrie Hilfen
# ---------------------------------------------------------------------------
def signed_area(pts: list[list[float]]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _seg_intersect(p1, p2, p3, p4) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 1e-12 and d2 < -1e-12) or (d1 < -1e-12 and d2 > 1e-12)) and (
        (d3 > 1e-12 and d4 < -1e-12) or (d3 < -1e-12 and d4 > 1e-12)
    )


def polygon_report(pts: list[list[float]]) -> dict:
    """Prueft ein gegen den Uhrzeigersinn orientiertes Polygon auf kurze Seiten, Selbstschnitt und Konvexitaet."""
    n = len(pts)
    out = {"min_side": math.inf, "simple": True, "convex": True, "area": signed_area(pts), "problems": []}
    for i in range(n):
        j = (i + 1) % n
        out["min_side"] = min(out["min_side"], math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]))
    if out["min_side"] < EPS_LEN:
        out["problems"].append("Zwei Punkte liegen aufeinander (Seite der Laenge 0)")
        out["simple"] = out["convex"] = False
        return out
    if out["area"] <= 1e-9:
        out["problems"].append("Die Kontur hat keine Flaeche oder ist im Uhrzeigersinn orientiert")
        out["simple"] = out["convex"] = False
        return out
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _seg_intersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                out["simple"] = False
    if not out["simple"]:
        out["problems"].append("Die Kontur schneidet sich selbst")
    turn = 0.0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        d1 = (b[0] - a[0], b[1] - a[1])
        d2 = (c[0] - b[0], c[1] - b[1])
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        dot = d1[0] * d2[0] + d1[1] * d2[1]
        scale = math.hypot(*d1) * math.hypot(*d2)
        if cross < -1e-9 * scale:
            out["convex"] = False
        turn += math.atan2(cross, dot)
    if abs(turn - 2 * math.pi) > 1e-6:
        out["simple"] = False
        out["convex"] = False
    if not out["convex"]:
        out["problems"].append("Die Kontur ist nicht konvex (das Modell braucht ein konvexes Gehaeuse, siehe Konvexe Huelle)")
    return out


def penetration(a: list, b: list) -> float:
    """Eindringtiefe zweier konvexer Polygone (SAT). Groesser 0 heisst echte Ueberlappung, Beruehren ist 0."""
    best = math.inf
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            nx, ny = y2 - y1, x1 - x2
            ln = math.hypot(nx, ny)
            if ln == 0:
                continue
            nx, ny = nx / ln, ny / ln
            pa = [nx * p[0] + ny * p[1] for p in a]
            pb = [nx * p[0] + ny * p[1] for p in b]
            ov = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if ov <= 0:
                return 0.0
            best = min(best, ov)
    return best if best != math.inf else 0.0


def gear_box(cd: float, gear_diameter: float, gear_width: float) -> list[list[float]]:
    """Zahnrad als Quader im Stangenrahmen (Mitte bei (-cd, 0), Welle parallel zu y)."""
    r, h = gear_diameter / 2.0, gear_width / 2.0
    return [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]]


def gear_overlap_message(pts: list, cd_nominal: float, cd: float, gear_diameter: float, gear_width: float) -> str:
    """Meldung, wenn das Zahnrad in das Gehaeuse ragt (Gehaeuse bei Achsabstand cd gegenueber dem nominalen verschoben)."""
    shifted = [[x + (cd_nominal - cd), y] for x, y in pts]
    pen = penetration(shifted, gear_box(cd, gear_diameter, gear_width))
    if pen > 1e-6:
        return f"Das Zahnrad ragt {pen:.2f} mm in das Gehaeuse (Achsabstand {cd:g} mm)"
    return ""


def measures(pts: list[list[float]]) -> dict:
    """Laengen aller Seiten und Innenwinkel an allen Punkten (Grad)."""
    n = len(pts)
    sides, angles = [], []
    for i in range(n):
        j = (i + 1) % n
        sides.append(math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]))
    for i in range(n):
        p, q, r = pts[i - 1], pts[i], pts[(i + 1) % n]
        a = (p[0] - q[0], p[1] - q[1])
        b = (r[0] - q[0], r[1] - q[1])
        ang = math.degrees(math.atan2(b[0] * a[1] - b[1] * a[0], a[0] * b[0] + a[1] * b[1]))
        angles.append(ang if ang >= 0 else ang + 360.0)
    return {"sides": sides, "angles": angles}


# ---------------------------------------------------------------------------
# Umindizieren (Orientierung, Punkt einfuegen, loeschen, Huelle)
# ---------------------------------------------------------------------------
def _map_constraint(c: dict, vmap, smap) -> Optional[dict]:
    """Uebertraegt einen Constraint auf neue Indizes. None, wenn ein Bezug entfaellt."""
    sides, verts, _, _ = SPEC[c["type"]]
    out = dict(c)
    for f in sides:
        m = smap(c[f])
        if m is None:
            return None
        out[f] = m
    for f in verts:
        m = vmap(c[f])
        if m is None:
            return None
        out[f] = m
    return out


def normalize_orientation(sk: dict) -> tuple[dict, bool]:
    """Dreht die Punktreihenfolge, falls die Kontur im Uhrzeigersinn liegt (Constraints werden umindiziert)."""
    pts = sk["points"]
    n = len(pts)
    if signed_area(pts) >= 0:
        return sk, False
    new_pts = [list(p) for p in reversed(pts)]
    vmap = lambda v: n - 1 - v
    smap = lambda s: (n - 2 - s) % n
    cons = []
    for c in sk["constraints"]:
        m = _map_constraint(c, vmap, smap)
        if m is not None:
            cons.append(m)
    return {"points": new_pts, "constraints": cons}, True


def insert_point(sk: dict, side: int, t: float = 0.5) -> dict:
    """Fuegt einen Punkt auf Seite side ein (Parameter t von 0 bis 1). Laengen Bezuege der Seite entfallen."""
    pts = sk["points"]
    n = len(pts)
    if not 0 <= side < n:
        raise SketchError(f"Seite {side} existiert nicht")
    if n >= MAX_POINTS:
        raise SketchError(f"Hoechstens {MAX_POINTS} Punkte erlaubt")
    a, b = pts[side], pts[(side + 1) % n]
    new = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    new_pts = [list(p) for p in pts[: side + 1]] + [new] + [list(p) for p in pts[side + 1:]]
    out: list[dict] = []
    for c in sk["constraints"]:
        sides, verts, _, _ = SPEC[c["type"]]
        vmap = lambda v: v if v <= side else v + 1
        base = dict(c)
        for f in verts:
            base[f] = vmap(c[f])
        refs_side = [f for f in sides if c[f] == side]
        if not refs_side:
            for f in sides:
                base[f] = c[f] if c[f] < side else c[f] + 1
            out.append(base)
            continue
        if c["type"] in ("length", "equal"):  # Laenge wuerde sich auf die Haelfte beziehen. Entfaellt
            continue
        # Richtungsbezuege gelten fuer beide Haelften der Geraden
        for half in (side, side + 1):
            d = dict(base)
            for f in sides:
                d[f] = half if c[f] == side else (c[f] if c[f] < side else c[f] + 1)
            out.append(d)
    return {"points": new_pts, "constraints": out}


def remap_vertices(sk: dict, keep: list[int]) -> dict:
    """Behaelt nur die Punkte keep (in dieser Reihenfolge). Constraints mit entfallenen Bezuegen werden entfernt."""
    pts = sk["points"]
    n = len(pts)
    new_of = {old: new for new, old in enumerate(keep)}
    m = len(keep)

    def vmap(v):
        return new_of.get(v)

    def smap(s):
        a, b = new_of.get(s), new_of.get((s + 1) % n)
        if a is None or b is None or b != (a + 1) % m:
            return None
        return a

    cons = []
    for c in sk["constraints"]:
        mc = _map_constraint(c, vmap, smap)
        if mc is not None:
            cons.append(mc)
    return {"points": [list(pts[i]) for i in keep], "constraints": cons}


def delete_point(sk: dict, v: int) -> dict:
    n = len(sk["points"])
    if not 0 <= v < n:
        raise SketchError(f"Punkt {v} existiert nicht")
    if n <= MIN_POINTS:
        raise SketchError(f"Mindestens {MIN_POINTS} Punkte noetig")
    return remap_vertices(sk, [i for i in range(n) if i != v])


def hull_sketch(sk: dict) -> dict:
    """Ersetzt die Kontur durch ihre konvexe Huelle (gegen den Uhrzeigersinn, Start beim gleichen Punkt wie moeglich)."""
    pts = sk["points"]
    order = sorted(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))

    def cross(o, a, b):
        return (pts[a][0] - pts[o][0]) * (pts[b][1] - pts[o][1]) - (pts[a][1] - pts[o][1]) * (pts[b][0] - pts[o][0])

    lower: list[int] = []
    for i in order:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 0:
            lower.pop()
        lower.append(i)
    upper: list[int] = []
    for i in reversed(order):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 0:
            upper.pop()
        upper.append(i)
    keep = lower[:-1] + upper[:-1]
    if len(keep) < MIN_POINTS:
        raise SketchError("Die Huelle hat weniger als 3 Punkte")
    # Reihenfolge der Huelle behalten, aber beim kleinsten urspruenglichen Index beginnen
    k0 = keep.index(min(keep))
    keep = keep[k0:] + keep[:k0]
    return remap_vertices(sk, keep)


# ---------------------------------------------------------------------------
# Residuen
# ---------------------------------------------------------------------------
def _refpos(ref: str, cd: float) -> tuple[float, float]:
    return (0.0, 0.0) if ref == "rod" else (-cd, 0.0)


def _compile(c: dict, n: int, cd: float, x0: list[float]):
    """Liefert eine Funktion x -> Liste von Residuen fuer den Constraint c.

    Vorzeichen (angle_sides, dist_side) werden einmal aus der Startlage x0 bestimmt, damit die
    Gleichungen im Betrachtungsbereich glatt bleiben."""
    t = c["type"]
    a, b = c["a"], c["b"]
    v, v2 = c["value"], c["value2"]

    def P(x, i):
        return x[2 * i], x[2 * i + 1]

    def D(x, s):  # Richtung der Seite s
        i, j = P(x, s), P(x, (s + 1) % n)
        return j[0] - i[0], j[1] - i[1]

    def norm(d):
        return max(math.hypot(*d), 1e-12)

    if t == "length":
        return lambda x: [norm(D(x, a)) - v]
    if t == "angle":
        def f(x):
            q = P(x, a)
            p, r = P(x, (a - 1) % n), P(x, (a + 1) % n)
            va, vb = (p[0] - q[0], p[1] - q[1]), (r[0] - q[0], r[1] - q[1])
            return [_wrap(math.atan2(vb[0] * va[1] - vb[1] * va[0], va[0] * vb[0] + va[1] * vb[1]) - math.radians(v))]
        return f
    if t == "angle_sides":
        da, db = D(x0, a), D(x0, b)
        s0 = da[0] * db[1] - da[1] * db[0]
        sign = -1.0 if s0 < 0 else 1.0
        target = sign * math.radians(v)

        def f(x):
            d1, d2 = D(x, a), D(x, b)
            return [_wrap(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]) - target)]
        return f
    if t == "parallel":
        def f(x):
            d1, d2 = D(x, a), D(x, b)
            return [(d1[0] * d2[1] - d1[1] * d2[0]) / (norm(d1) * norm(d2))]
        return f
    if t == "perpendicular":
        def f(x):
            d1, d2 = D(x, a), D(x, b)
            return [(d1[0] * d2[0] + d1[1] * d2[1]) / (norm(d1) * norm(d2))]
        return f
    if t == "equal":
        return lambda x: [norm(D(x, a)) - norm(D(x, b))]
    if t == "horizontal":
        return lambda x: [D(x, a)[1]]
    if t == "vertical":
        return lambda x: [D(x, a)[0]]
    if t == "fix":
        return lambda x: [P(x, a)[0] - v, P(x, a)[1] - v2]
    if t == "coord_x":
        return lambda x: [P(x, a)[0] - v]
    if t == "coord_y":
        return lambda x: [P(x, a)[1] - v]
    if t == "dist_point":
        r = _refpos(c["ref"], cd)
        return lambda x: [math.hypot(P(x, a)[0] - r[0], P(x, a)[1] - r[1]) - v]
    if t == "dist_side":
        r = _refpos(c["ref"], cd)

        def signed(x):
            d = D(x, a)
            p = P(x, a)
            return (d[0] * (r[1] - p[1]) - d[1] * (r[0] - p[0])) / norm(d)

        sign = 1.0 if signed(x0) > 0 else -1.0  # Referenz innerhalb (+) oder ausserhalb (-) der Seite
        return lambda x: [signed(x) - sign * v]
    raise SketchError(f"Unbekannter Constraint {t}")


# ---------------------------------------------------------------------------
# Numerik (reines Python)
# ---------------------------------------------------------------------------
def _gauss(A: list[list[float]], b: list[float]) -> Optional[list[float]]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-300:
            return None
        M[col], M[piv] = M[piv], M[col]
        inv = 1.0 / M[col][col]
        for r in range(col + 1, n):
            f = M[r][col] * inv
            if f:
                Mr, Mc = M[r], M[col]
                for k in range(col, n + 1):
                    Mr[k] -= f * Mc[k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][k] * x[k] for k in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def _jacobian(fn, x: list[float], m: int) -> list[list[float]]:
    N = len(x)
    J = [[0.0] * N for _ in range(m)]
    for j in range(N):
        h = 1e-6 * max(1.0, abs(x[j]))
        xp, xm = x[:], x[:]
        xp[j] += h
        xm[j] -= h
        rp, rm = fn(xp), fn(xm)
        for i in range(m):
            J[i][j] = (rp[i] - rm[i]) / (2 * h)
    return J


def _lm(hard, soft, x0: list[float], max_iter: int = 120, deadline: Optional[float] = None):
    """Minimiert |hard|^2 + |soft|^2 mit Levenberg Marquardt. hard und soft sind Funktionen x -> Liste.

    Jeder Schritt ist die Minimum Norm Loesung (dx = -J^T (J J^T + mu I)^-1 r). Sie liegt im Zeilenraum von J,
    nicht eindeutig bestimmte Richtungen bleiben daher unveraendert (minimale Bewegung der Punkte) und
    Rundungsrauschen wird nicht in freie Richtungen verstaerkt.

    Gibt (x, max Betrag der harten Residuen) zurueck."""
    N = len(x0)

    def full(x):
        return hard(x) + soft(x)

    x = x0[:]
    r = full(x)
    cost = sum(v * v for v in r)
    lam = 1e-3
    m = len(r)
    step = math.inf
    for _ in range(max_iter):
        if m == 0 or (deadline is not None and time.monotonic() > deadline):
            break
        hr = r[: m - len(soft(x))] if soft(x) else r
        if hr and max(abs(v) for v in hr) < TOL_SOLVE and not soft(x):
            break
        J = _jacobian(full, x, m)
        JJT = [[sum(J[i][k] * J[j][k] for k in range(N)) for j in range(m)] for i in range(m)]
        scale = max(max(JJT[i][i] for i in range(m)), 1e-12)
        improved = False
        for _try in range(30):
            A = [row[:] for row in JJT]
            for i in range(m):
                A[i][i] += lam * scale + 1e-14
            y = _gauss(A, r)
            if y is None:
                lam *= 10
                continue
            dx = [-sum(J[i][k] * y[i] for i in range(m)) for k in range(N)]
            xn = [x[k] + dx[k] for k in range(N)]
            rn = full(xn)
            cn = sum(v * v for v in rn)
            if cn < cost or cn < 1e-26:
                step = math.sqrt(sum(d * d for d in dx))
                x, r, cost = xn, rn, cn
                lam = max(lam / 3.0, 1e-12)
                improved = True
                break
            lam *= 4.0
        if not improved or step < 1e-13:
            break
    hr = hard(x)
    return x, (max(abs(v) for v in hr) if hr else 0.0)


# ---------------------------------------------------------------------------
# Analyse. Freiheitsgrade, Redundanz
# ---------------------------------------------------------------------------
def _analyse(fns, x: list[float]) -> tuple[int, list[bool]]:
    """Rang der Constraint Jacobi Matrix. Rueckgabe (Rang, redundant je Constraint)."""
    basis: list[list[float]] = []
    redundant: list[bool] = []
    for fn in fns:
        m = len(fn(x))
        J = _jacobian(fn, x, m)
        dependent = True
        for row in J:
            norm0 = math.sqrt(sum(v * v for v in row))
            if norm0 < 1e-9:
                continue  # Zeile ist null. Der Constraint wirkt hier nicht, zaehlt als abhaengig
            v = row[:]
            for _ in range(2):  # zweimal orthogonalisieren, numerisch stabiler
                for bvec in basis:
                    d = sum(v[i] * bvec[i] for i in range(len(v)))
                    v = [v[i] - d * bvec[i] for i in range(len(v))]
            nv = math.sqrt(sum(q * q for q in v))
            if nv / norm0 > 1e-6:
                basis.append([q / nv for q in v])
                dependent = False
        redundant.append(dependent)
    return len(basis), redundant


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------
@dataclass
class SolveResult:
    ok: bool
    sketch: dict
    state: str  # under | full | over | conflict | invalid
    dof: int
    constraints: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    convex: bool = False
    measures: dict = field(default_factory=dict)
    bbox: Optional[dict] = None
    reoriented: bool = False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "sketch": self.sketch, "state": self.state, "dof": self.dof, "constraints": self.constraints,
            "errors": self.errors, "warnings": self.warnings, "convex": self.convex, "measures": self.measures,
            "bbox": self.bbox, "reoriented": self.reoriented,
        }


def _label(c: dict, k: int) -> str:
    base = LABELS.get(c["type"], c["type"])
    where = []
    sides, verts, _, _ = SPEC.get(c["type"], ((), (), False, False))
    for f in sides:
        where.append(f"Seite {c[f] + 1}")
    for f in verts:
        where.append(f"Punkt {c[f] + 1}")
    return f"{c['name'] or base} ({', '.join(where)}) [Nr. {k + 1}]"


def solve(sketch: Any, cd: float = 5.0, drag: Optional[dict] = None, diagnose: bool = True,
          gear: Optional[tuple[float, float]] = None, time_limit: float = TIME_LIMIT_S) -> SolveResult:
    """Loest die Skizze. Die Punkte aus sketch sind die Startlage (minimale Bewegung).

    drag = {"point": i, "target": [x, y]} zieht einen Punkt so nah wie moeglich an das Ziel, ohne Constraints zu verletzen.
    Bei Widerspruechen enthaelt das Ergebnis die letzte widerspruchsfreie Loesung und ok ist False.
    gear = (Durchmesser, Breite) prueft zusaetzlich, ob das Zahnrad ins Gehaeuse ragt (Warnung)."""
    sk = sketch_dict(sketch)
    errs = validate_structure(sk)
    if errs:
        return SolveResult(False, sk, "invalid", 0, errors=errs)
    if not _isnum(cd) or cd < 0:
        return SolveResult(False, sk, "invalid", 0, errors=["cd. Achsabstand muss eine Zahl >= 0 sein"])
    sk, reoriented = normalize_orientation(sk)
    if signed_area(sk["points"]) <= 1e-12:
        return SolveResult(False, sk, "invalid", 0, errors=["motor.sketch.points. Die Kontur hat keine Flaeche"], reoriented=reoriented)
    n = len(sk["points"])
    cons = sk["constraints"]
    active = [(k, c) for k, c in enumerate(cons) if c["enabled"]]
    x0 = [v for p in sk["points"] for v in p]
    for _, c in active:  # Abstand zur Referenz ist am Referenzpunkt nicht differenzierbar. Startlage leicht verschieben
        if c["type"] == "dist_point":
            rx, ry = _refpos(c["ref"], cd)
            i = c["a"]
            if math.hypot(x0[2 * i] - rx, x0[2 * i + 1] - ry) < 1e-6:
                x0[2 * i] += 1e-3

    def make_hard(items, base):
        fns = [_compile(c, n, cd, base) for _, c in items]
        return fns, (lambda x: [r for fn in fns for r in fn(x)])

    drag_soft = lambda x: []
    if drag is not None:
        try:
            di, (tx, ty) = int(drag["point"]), drag["target"]
            assert 0 <= di < n and _isnum(tx) and _isnum(ty)
        except (KeyError, TypeError, ValueError, AssertionError):
            return SolveResult(False, sk, "invalid", 0, errors=["drag. Erwartet {point, target:[x, y]} mit gueltigem Punkt"])
        w = 0.1
        drag_soft = lambda x: [w * (x[2 * di] - tx), w * (x[2 * di + 1] - ty)]

    deadline = time.monotonic() + time_limit
    fns, hard = make_hard(active, x0)
    x, resid = _lm(hard, drag_soft, x0, deadline=deadline)
    if drag is not None:
        x, resid = _lm(hard, lambda x: [], x, deadline=deadline)  # Politur ohne Ziehen. Constraints haben Vorrang
    status = {k: "ok" for k, _ in active}
    messages: dict[int, str] = {}
    conflicts: list[int] = []
    if resid >= TOL_OK and time.monotonic() > deadline:
        return SolveResult(False, sk, "invalid", 0, errors=["Zeitlimit beim Loesen ueberschritten (zu viele oder zu komplizierte Constraints)"])
    if resid >= TOL_OK:
        if drag is not None or not diagnose:
            # Ziehen ist unzulaessig. Startlage zurueckgeben
            x_fallback = x0
            conflicts = []
            x = x_fallback
        else:
            ok_items: list[tuple[int, dict]] = []
            sol = x0
            for item in active:
                trial = ok_items + [item]
                _, h = make_hard(trial, sol)
                xs, r = _lm(h, lambda x: [], sol, deadline=deadline)
                if time.monotonic() > deadline:
                    return SolveResult(False, sk, "invalid", 0, errors=["Zeitlimit beim Loesen ueberschritten (zu viele oder zu komplizierte Constraints)"])
                if r < TOL_OK:
                    ok_items, sol = trial, xs
                else:
                    conflicts.append(item[0])
            x = sol
            for k in conflicts:
                status[k] = "conflict"
                messages[k] = f"{_label(cons[k], k)} widerspricht den vorherigen Constraints"
        fns, _ = make_hard([it for it in active if it[0] not in conflicts], x)
        used = [it for it in active if it[0] not in conflicts]
    else:
        used = active
    pts = [[x[2 * i], x[2 * i + 1]] for i in range(n)]
    # Analyse nur ueber die erfuellten Constraints
    fns_used = [_compile(c, n, cd, x) for _, c in used]
    rank, redundant = _analyse(fns_used, x)
    for (k, _), red in zip(used, redundant):
        if red:
            status[k] = "redundant"
            messages[k] = f"{_label(cons[k], k)} ist redundant (bereits durch andere Constraints bestimmt)"
    dof = 2 * n - rank
    rep = polygon_report(pts)
    errors = list(messages[k] for k in conflicts)
    if resid >= TOL_OK and drag is not None:
        errors.append("Die gezogene Lage verletzt Constraints. Die Skizze bleibt unveraendert")
    warnings: list[str] = [] if rep["convex"] else list(rep["problems"])
    if gear is not None and rep["convex"]:
        msg = gear_overlap_message(pts, cd, cd, gear[0], gear[1])
        if msg:
            warnings.append(msg)
    if conflicts:
        state = "conflict"
    elif any(r for r in redundant):
        state = "over"
    elif dof == 0:
        state = "full"
    else:
        state = "under"
    res_list = []
    for k, c in enumerate(cons):
        st = "disabled" if not c["enabled"] else status.get(k, "ok")
        entry = {"index": k, "status": st, "message": messages.get(k, "")}
        if c["enabled"] and st != "conflict":
            fn = _compile(c, n, cd, x)
            entry["residual"] = max(abs(v) for v in fn(x))
        res_list.append(entry)
    xs_, ys_ = [p[0] for p in pts], [p[1] for p in pts]
    bbox = {"xmin": min(xs_), "ymin": min(ys_), "xmax": max(xs_), "ymax": max(ys_)}
    out_sketch = {"points": pts, "constraints": cons}
    return SolveResult(not conflicts and resid < TOL_OK, out_sketch, state, dof, res_list, errors, warnings,
                       rep["convex"], measures(pts), bbox, reoriented)


# ---------------------------------------------------------------------------
# Verbindung zum Motor
# ---------------------------------------------------------------------------
def legacy_to_sketch(motor: Any, with_constraints: bool = True) -> dict:
    """Wandelt Rechteck oder outline eines Motors in eine Skizze im Stangenrahmen um."""
    from .geometry import Footprint

    outline = getattr(motor, "outline", None)
    if outline:
        poly = [list(p) for p in Footprint.polygon(outline).pts]
        rect = False
    else:
        poly = [list(p) for p in Footprint.rect(0, 0, motor.width, motor.depth).pts]
        rect = True
    rx, ry = motor.rod_local()
    pts = [[x - rx, y - ry] for x, y in poly]
    cons: list[dict] = []
    if with_constraints and rect:
        def mk(t, a=None, b=None, value=None):
            return {"type": t, "a": a, "b": b, "value": value, "value2": None, "ref": "rod", "enabled": True, "name": ""}

        cons = [mk("horizontal", 0), mk("length", 0, value=motor.width), mk("length", 1, value=motor.depth),
                mk("angle", 1, value=90.0), mk("parallel", 0, 2), mk("parallel", 1, 3)]
    return {"points": pts, "constraints": cons}


def sketch_from_outline(outline: list[list[float]], motor: Any) -> dict:
    """Kontur im Gehaeuse Koordinatensystem (z.B. aus SVG) als Skizze im Stangenrahmen ohne Constraints.

    Die Kontur wird so zum Zahnrad gesetzt, wie es auch ein Umriss ohne Skizze waere. Das Zahnrad sitzt
    gear_gap hinter der obersten Kante, die Stange auf Hoehe der Zahnradmitte."""
    from .geometry import Footprint

    poly = [list(p) for p in Footprint.polygon(outline).pts]
    top = max(p[1] for p in poly)
    rx, ry = motor.shaft_x + motor.center_distance, top + motor.gear_gap + motor.gear_width / 2.0
    return {"points": [[x - rx, y - ry] for x, y in poly], "constraints": []}


def check_sketch_motor(motor: Any, prefix: str = "motor.sketch") -> tuple[list[tuple[float, float]], list[str]]:
    """Loest die Skizze eines Motors und prueft sie gegen Zahnrad. Rueckgabe (Gehaeuse, Fehler)."""
    res = solve(motor.sketch, cd=motor.center_distance)
    errs: list[str] = []
    if not res.ok:
        errs.extend(res.errors or [f"{prefix}. Skizze nicht loesbar"])
        return [], errs
    if not res.convex:
        errs.extend(f"{prefix}. {w}" for w in res.warnings)
        return [], errs
    pts = res.sketch["points"]
    for cd in motor.center_distances():
        msg = gear_overlap_message(pts, motor.center_distance, cd, motor.gear_diameter, motor.gear_width)
        if msg:
            errs.append(f"{prefix}. {msg}")
            break
    return [(p[0], p[1]) for p in pts], errs


def housing_polygon(motor: Any) -> list[tuple[float, float]]:
    """Gehaeusekontur im Stangenrahmen bei nominalem Achsabstand (gegen den Uhrzeigersinn).

    Mit Skizze wird sie geloest, sonst aus Rechteck oder outline berechnet. Wirft SketchError bei Fehlern."""
    from .geometry import Footprint

    if getattr(motor, "sketch", None) is not None:
        pts, errs = check_sketch_motor(motor)
        if errs:
            raise SketchError(errs)
        return pts
    rx, ry = motor.rod_local()
    poly = Footprint.polygon(motor.outline).pts if motor.outline else Footprint.rect(0, 0, motor.width, motor.depth).pts
    return [(x - rx, y - ry) for x, y in poly]
