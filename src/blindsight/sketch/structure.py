"""Datenhaltung der Skizze. Normierung, Strukturpruefung und Umindizieren.

Die Skizze wird intern als JSON nahes Dictionary gefuehrt.
  {"points": [[x, y], ...], "constraints": [{"type", "a", "b", "value", "value2", "ref", "enabled", "name"}, ...]}

Alle Funktionen hier liefern neue Dictionaries und veraendern ihre Eingabe nicht.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..errors import SketchError
from ..geometry import convex_hull_indices, signed_area
from ..units import is_finite_number
from .constraints import CONSTRAINT_TYPES, REFS, SPLIT_DROP

MIN_POINTS = 3
MAX_POINTS = 40
MAX_CONSTRAINTS = 150

CONSTRAINT_FIELDS = ("type", "a", "b", "value", "value2", "ref", "enabled", "name")

IndexMap = Callable[[int], Optional[int]]  # alter Index -> neuer Index oder None (Bezug entfaellt)


# ---------------------------------------------------------------------------
# Normierung
# ---------------------------------------------------------------------------
def constraint_dict(c: Any) -> dict:
    """Wandelt ein ConstraintSpec oder Dictionary in ein normiertes Dictionary.

    Werte werden nicht umgewandelt (auch enabled nicht), damit validate_structure falsche
    Typen melden kann statt sie still zu deuten."""
    if isinstance(c, dict):
        def get(key, default=None):
            return c.get(key, default)
    else:
        def get(key, default=None):
            return getattr(c, key, default)
    enabled = get("enabled", True)
    return {
        "type": get("type"), "a": get("a"), "b": get("b"), "value": get("value"), "value2": get("value2"),
        "ref": get("ref", "rod") or "rod", "enabled": True if enabled is None else enabled,
        "name": get("name", "") or "",
    }


def sketch_dict(sk: Any) -> dict:
    """Wandelt SketchSpec oder Dictionary in {points, constraints} mit Kopien.

    Unpassende Eingaben (keine Listen) bleiben erhalten, validate_structure meldet sie."""
    if isinstance(sk, dict):
        pts, cons = sk.get("points", []), sk.get("constraints", [])
    else:
        pts, cons = getattr(sk, "points", None), getattr(sk, "constraints", None)
    if isinstance(pts, (list, tuple)):
        pts = [[p[0], p[1]] if isinstance(p, (list, tuple)) and len(p) == 2 else p for p in pts]
    if isinstance(cons, (list, tuple)):
        cons = [constraint_dict(c) for c in cons]
    return {"points": pts, "constraints": cons}


# ---------------------------------------------------------------------------
# Strukturpruefung
# ---------------------------------------------------------------------------
def validate_structure(sk: dict, prefix: str = "motor.sketch") -> list[str]:
    """Prueft Typen, Indizes und Wertebereiche. Gibt alle Fehler mit Feldpfad zurueck."""
    pts, cons = sk.get("points"), sk.get("constraints")
    if not isinstance(pts, list) or not isinstance(cons, list):
        return [f"{prefix}. points und constraints muessen Listen sein"]
    errs: list[str] = []
    n = len(pts)
    if n < MIN_POINTS:
        errs.append(f"{prefix}.points. Mindestens {MIN_POINTS} Punkte noetig (sind {n})")
    if n > MAX_POINTS:
        errs.append(f"{prefix}.points. Hoechstens {MAX_POINTS} Punkte erlaubt (sind {n})")
    for i, p in enumerate(pts):
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(is_finite_number(v) for v in p)):
            errs.append(f"{prefix}.points[{i}]. Muss [x, y] mit endlichen Zahlen sein")
    if len(cons) > MAX_CONSTRAINTS:
        errs.append(f"{prefix}.constraints. Zu viele Constraints (max {MAX_CONSTRAINTS})")
        return errs
    for k, c in enumerate(cons):
        errs.extend(_constraint_errors(c, n, f"{prefix}.constraints[{k}]"))
    return errs


def _constraint_errors(c: dict, n: int, tag: str) -> list[str]:
    ctype = CONSTRAINT_TYPES.get(c["type"]) if isinstance(c["type"], str) else None
    if ctype is None:
        return [f"{tag}.type. Unbekannter Typ '{c['type']}'. Erlaubt. {sorted(CONSTRAINT_TYPES)}"]
    errs: list[str] = []
    for f in ctype.index_fields:
        idx = c[f]
        if isinstance(idx, bool) or not isinstance(idx, int):
            errs.append(f"{tag}.{f}. Index muss eine ganze Zahl sein")
        elif not 0 <= idx < max(n, 1):
            what = "Seite" if f in ctype.sides else "Punkt"
            errs.append(f"{tag}.{f}. {what} {idx} existiert nicht (0..{n - 1})")
    if len(ctype.sides) == 2 and isinstance(c["a"], int) and c["a"] == c["b"]:
        errs.append(f"{tag}. Die beiden Seiten muessen verschieden sein")
    if ctype.value is not None and not is_finite_number(c["value"]):
        errs.append(f"{tag}.value. Zahl erforderlich")
    elif ctype.value2 is not None and not is_finite_number(c["value2"]):
        errs.append(f"{tag}.value2. Zahl erforderlich")
    elif ctype.check_value is not None:
        message = ctype.check_value(c["value"])
        if message:
            errs.append(f"{tag}.value. {message}")
    if ctype.uses_ref and c["ref"] not in REFS:
        errs.append(f"{tag}.ref. Muss 'rod' oder 'gear' sein")
    if not isinstance(c["enabled"], bool):
        errs.append(f"{tag}.enabled. Muss true oder false sein")
    if not isinstance(c["name"], str):
        errs.append(f"{tag}.name. Muss Text sein")
    return errs


# ---------------------------------------------------------------------------
# Umindizieren (Orientierung, Punkt einfuegen, loeschen, Huelle)
# ---------------------------------------------------------------------------
def _map_constraint(c: dict, point_map: IndexMap, side_map: IndexMap) -> Optional[dict]:
    """Uebertraegt einen Constraint auf neue Indizes. None, wenn ein Bezug entfaellt."""
    ctype = CONSTRAINT_TYPES[c["type"]]
    out = dict(c)
    for fields, index_map in ((ctype.sides, side_map), (ctype.points, point_map)):
        for f in fields:
            new = index_map(c[f])
            if new is None:
                return None
            out[f] = new
    return out


def _map_all(constraints: list[dict], point_map: IndexMap, side_map: IndexMap) -> list[dict]:
    out = []
    for c in constraints:
        mapped = _map_constraint(c, point_map, side_map)
        if mapped is not None:
            out.append(mapped)
    return out


def reversed_point_index(n: int, i: int) -> int:
    """Index von Punkt i, nachdem die Punktreihenfolge umgedreht wurde."""
    return n - 1 - i


def normalize_orientation(sk: dict) -> tuple[dict, bool]:
    """Dreht die Punktreihenfolge, falls die Kontur im Uhrzeigersinn liegt (Constraints werden umindiziert).

    Rueckgabe (Skizze, wurde gedreht). Seite s (Punkt s nach s+1) wird zur Seite n-2-s."""
    pts = sk["points"]
    n = len(pts)
    if signed_area(pts) >= 0:
        return sk, False
    new_pts = [list(p) for p in reversed(pts)]
    cons = _map_all(sk["constraints"], lambda v: reversed_point_index(n, v), lambda s: (n - 2 - s) % n)
    return {"points": new_pts, "constraints": cons}, True


def insert_point(sk: dict, side: int, t: float = 0.5) -> dict:
    """Fuegt einen Punkt auf Seite side ein (Parameter t zwischen 0 und 1, exklusiv).

    Laengenbezuege der geteilten Seite entfallen, Richtungsbezuege gelten fuer beide Haelften."""
    pts = sk["points"]
    n = len(pts)
    if isinstance(side, bool) or not isinstance(side, int) or not 0 <= side < n:
        raise SketchError(f"Seite {side} existiert nicht")
    if not is_finite_number(t) or not 0 < t < 1:
        raise SketchError("t. Muss eine Zahl zwischen 0 und 1 sein (exklusiv)")
    if n >= MAX_POINTS:
        raise SketchError(f"Hoechstens {MAX_POINTS} Punkte erlaubt")
    a, b = pts[side], pts[(side + 1) % n]
    new = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    new_pts = [list(p) for p in pts[: side + 1]] + [new] + [list(p) for p in pts[side + 1:]]

    def shift(i: int) -> int:
        """Punkt und Seitenindizes hinter der Einfuegestelle wandern um eins."""
        return i if i <= side else i + 1

    out: list[dict] = []
    for c in sk["constraints"]:
        ctype = CONSTRAINT_TYPES[c["type"]]
        base = dict(c)
        for f in ctype.points:
            base[f] = shift(c[f])
        split_fields = [f for f in ctype.sides if c[f] == side]
        for f in ctype.sides:
            if f not in split_fields:
                base[f] = shift(c[f])
        if not split_fields:
            out.append(base)
        elif ctype.on_split != SPLIT_DROP:
            for half in (side, side + 1):
                out.append({**base, **{f: half for f in split_fields}})
    return {"points": new_pts, "constraints": out}


def remap_vertices(sk: dict, keep: list[int]) -> dict:
    """Behaelt nur die Punkte keep (in dieser Reihenfolge). Constraints mit entfallenen Bezuegen werden entfernt."""
    pts = sk["points"]
    n = len(pts)
    m = len(keep)
    new_of = {old: new for new, old in enumerate(keep)}

    def side_map(s: int) -> Optional[int]:
        """Eine Seite bleibt nur, wenn ihre beiden Endpunkte weiterhin Nachbarn sind."""
        a, b = new_of.get(s), new_of.get((s + 1) % n)
        if a is None or b is None or b != (a + 1) % m:
            return None
        return a

    cons = _map_all(sk["constraints"], new_of.get, side_map)
    return {"points": [list(pts[i]) for i in keep], "constraints": cons}


def delete_point(sk: dict, v: int) -> dict:
    """Entfernt Punkt v. Constraints mit Bezug auf den Punkt oder seine zwei Seiten entfallen."""
    n = len(sk["points"])
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < n:
        raise SketchError(f"Punkt {v} existiert nicht")
    if n <= MIN_POINTS:
        raise SketchError(f"Mindestens {MIN_POINTS} Punkte noetig")
    return remap_vertices(sk, [i for i in range(n) if i != v])


def hull_sketch(sk: dict) -> dict:
    """Ersetzt die Kontur durch ihre konvexe Huelle (gegen den Uhrzeigersinn, Start beim kleinsten alten Index)."""
    keep = convex_hull_indices(sk["points"])
    if len(keep) < MIN_POINTS:
        raise SketchError("Die Huelle hat weniger als 3 Punkte")
    first = keep.index(min(keep))
    return remap_vertices(sk, keep[first:] + keep[:first])
