"""Sketch data. Normalisation, structure check and reindexing.

Internally the sketch is a JSON like dictionary.
  {"points": [[x, y], ...], "constraints": [{"type", "a", "b", "value", "value2", "ref", "enabled", "name"}, ...]}

All functions here return new dictionaries and do not change their input.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..errors import SketchError
from ..geometry import convex_hull_indices, signed_area
from ..i18n import tr
from ..units import is_finite_number
from .constraints import CONSTRAINT_TYPES, REFS, SPLIT_DROP

MIN_POINTS = 3
MAX_POINTS = 40
MAX_CONSTRAINTS = 150

CONSTRAINT_FIELDS = ("type", "a", "b", "value", "value2", "ref", "enabled", "name")

IndexMap = Callable[[int], Optional[int]]  # old index -> new index or None (reference dropped)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def constraint_dict(c: Any) -> dict:
    """Turn a ConstraintSpec or dictionary into a normalised dictionary.

    Values are not converted (enabled neither) so that validate_structure can report wrong types
    instead of silently interpreting them."""
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
    """Turn a SketchSpec or dictionary into {points, constraints} with copies.

    Unsuitable input (no lists) is kept, validate_structure reports it."""
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
# Structure check
# ---------------------------------------------------------------------------
def validate_structure(sk: dict, prefix: str = "motor.sketch") -> list[str]:
    """Check types, indices and value ranges. Returns all errors with field path."""
    pts, cons = sk.get("points"), sk.get("constraints")
    if not isinstance(pts, list) or not isinstance(cons, list):
        return [tr("sketch.not_lists", prefix=prefix)]
    errs: list[str] = []
    n = len(pts)
    if n < MIN_POINTS:
        errs.append(tr("sketch.min_points", prefix=prefix, min=MIN_POINTS, n=n))
    if n > MAX_POINTS:
        errs.append(tr("sketch.max_points", prefix=prefix, max=MAX_POINTS, n=n))
    for i, p in enumerate(pts):
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(is_finite_number(v) for v in p)):
            errs.append(tr("sketch.point_format", path=f"{prefix}.points[{i}]"))
    if len(cons) > MAX_CONSTRAINTS:
        errs.append(tr("sketch.too_many_constraints", prefix=prefix, max=MAX_CONSTRAINTS))
        return errs
    for k, c in enumerate(cons):
        errs.extend(_constraint_errors(c, n, f"{prefix}.constraints[{k}]"))
    return errs


def _constraint_errors(c: dict, n: int, tag: str) -> list[str]:
    ctype = CONSTRAINT_TYPES.get(c["type"]) if isinstance(c["type"], str) else None
    if ctype is None:
        return [tr("sketch.unknown_type", tag=tag, type=c["type"], allowed=sorted(CONSTRAINT_TYPES))]
    errs: list[str] = []
    for f in ctype.index_fields:
        idx = c[f]
        if isinstance(idx, bool) or not isinstance(idx, int):
            errs.append(tr("sketch.index_integer", path=f"{tag}.{f}"))
        elif not 0 <= idx < max(n, 1):
            key = "sketch.side_missing" if f in ctype.sides else "sketch.point_missing"
            errs.append(tr(key, path=f"{tag}.{f}", index=idx, last=n - 1))
    if len(ctype.sides) == 2 and isinstance(c["a"], int) and c["a"] == c["b"]:
        errs.append(tr("sketch.sides_differ", tag=tag))
    if ctype.value is not None and not is_finite_number(c["value"]):
        errs.append(tr("sketch.number_required", path=f"{tag}.value"))
    elif ctype.value2 is not None and not is_finite_number(c["value2"]):
        errs.append(tr("sketch.number_required", path=f"{tag}.value2"))
    elif ctype.check_value is not None:
        message = ctype.check_value(c["value"])
        if message:
            errs.append(tr("sketch.value_message", path=f"{tag}.value", message=message))
    if ctype.uses_ref and c["ref"] not in REFS:
        errs.append(tr("sketch.ref_invalid", path=f"{tag}.ref"))
    if not isinstance(c["enabled"], bool):
        errs.append(tr("value.bool", path=f"{tag}.enabled"))
    if not isinstance(c["name"], str):
        errs.append(tr("value.text", path=f"{tag}.name"))
    return errs


# ---------------------------------------------------------------------------
# Reindexing (orientation, insert point, delete, hull)
# ---------------------------------------------------------------------------
def _map_constraint(c: dict, point_map: IndexMap, side_map: IndexMap) -> Optional[dict]:
    """Carry a constraint over to new indices. None if a reference is dropped."""
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
    """Index of point i after the point order was reversed."""
    return n - 1 - i


def normalize_orientation(sk: dict) -> tuple[dict, bool]:
    """Reverse the point order if the outline is clockwise (constraints are reindexed).

    Returns (sketch, was reversed). Side s (point s to s+1) becomes side n-2-s."""
    pts = sk["points"]
    n = len(pts)
    if signed_area(pts) >= 0:
        return sk, False
    new_pts = [list(p) for p in reversed(pts)]
    cons = _map_all(sk["constraints"], lambda v: reversed_point_index(n, v), lambda s: (n - 2 - s) % n)
    return {"points": new_pts, "constraints": cons}, True


def insert_point(sk: dict, side: int, t: float = 0.5) -> dict:
    """Insert a point on side side (parameter t between 0 and 1, exclusive).

    Length references of the split side are dropped, direction references hold for both halves."""
    pts = sk["points"]
    n = len(pts)
    if isinstance(side, bool) or not isinstance(side, int) or not 0 <= side < n:
        raise SketchError(tr("sketch.side_not_exists", side=side))
    if not is_finite_number(t) or not 0 < t < 1:
        raise SketchError(tr("sketch.t_range"))
    if n >= MAX_POINTS:
        raise SketchError(tr("sketch.max_points_plain", max=MAX_POINTS))
    a, b = pts[side], pts[(side + 1) % n]
    new = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    new_pts = [list(p) for p in pts[: side + 1]] + [new] + [list(p) for p in pts[side + 1:]]

    def shift(i: int) -> int:
        """Point and side indices behind the insertion point move by one."""
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
    """Keep only the points keep (in this order). Constraints with dropped references are removed."""
    pts = sk["points"]
    n = len(pts)
    m = len(keep)
    new_of = {old: new for new, old in enumerate(keep)}

    def side_map(s: int) -> Optional[int]:
        """A side only stays if its two end points are still neighbours."""
        a, b = new_of.get(s), new_of.get((s + 1) % n)
        if a is None or b is None or b != (a + 1) % m:
            return None
        return a

    cons = _map_all(sk["constraints"], new_of.get, side_map)
    return {"points": [list(pts[i]) for i in keep], "constraints": cons}


def delete_point(sk: dict, v: int) -> dict:
    """Remove point v. Constraints referring to the point or its two sides are dropped."""
    n = len(sk["points"])
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < n:
        raise SketchError(tr("sketch.point_not_exists", point=v))
    if n <= MIN_POINTS:
        raise SketchError(tr("sketch.min_points_plain", min=MIN_POINTS))
    return remap_vertices(sk, [i for i in range(n) if i != v])


def hull_sketch(sk: dict) -> dict:
    """Replace the outline by its convex hull (counter clockwise, starting at the smallest old index)."""
    keep = convex_hull_indices(sk["points"])
    if len(keep) < MIN_POINTS:
        raise SketchError(tr("sketch.hull_too_small"))
    first = keep.index(min(keep))
    return remap_vertices(sk, keep[first:] + keep[:first])
