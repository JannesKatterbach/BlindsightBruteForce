"""Sketch data in the rod frame (origin = rod axis, mm, y up), modelled after the sketches of Onshape.

  {"points": [[x, y], ...],
   "entities": [{"type": "line", "points": [a, b], "radius": null, "construction": false, "role": ""}, ...],
   "constraints": [{"type": "length", "refs": ["e0"], "value": 20, "at": null, "enabled": true,
                    "name": "", "label": [x, y]}, ...]}

Entities own their points (a point belongs to one entity), connections are coincident constraints.
  point   points [p]
  line    points [a, b]
  circle  points [centre], radius
  arc     points [centre, start, end], counter clockwise from start to end, radius |start - centre|
construction marks helper geometry (not part of the housing). role "gear" marks the gear (its four lines,
the construction diagonal and the centre point).

References of constraints are texts. "p3" is point 3, "e2" entity 2 (a point entity counts as its point),
"o" the origin (rod axis, fixed).

The unknowns of the solver are all point coordinates followed by the radii of the circles.
All functions return new dictionaries and do not change their input.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..i18n import tr
from ..units import is_finite_number

ENTITY_POINTS = {"point": 1, "line": 2, "circle": 1, "arc": 3}
ROLES = ("", "gear")
ROLE_GEAR = "gear"
ORIGIN = "o"
MAX_POINTS = 400
MAX_ENTITIES = 200
MAX_CONSTRAINTS = 400
MIN_RADIUS = 1e-6

# Kinds of references
K_POINT, K_LINE, K_CURVE = "point", "line", "curve"

Vector = list[float]
Point = tuple[float, float]


def entity_dict(e: Any) -> dict:
    """Normalised entity (EntitySpec or dictionary). Values are not converted so that checks can report them."""
    get = (lambda k, d=None: e.get(k, d)) if isinstance(e, dict) else (lambda k, d=None: getattr(e, k, d))
    points = get("points", [])
    return {"type": get("type"), "points": list(points) if isinstance(points, (list, tuple)) else points,
            "radius": get("radius"), "construction": get("construction", False), "role": get("role", "") or ""}


def constraint_dict(c: Any) -> dict:
    get = (lambda k, d=None: c.get(k, d)) if isinstance(c, dict) else (lambda k, d=None: getattr(c, k, d))
    refs = get("refs", [])
    enabled = get("enabled", True)
    return {"type": get("type"), "refs": list(refs) if isinstance(refs, (list, tuple)) else refs,
            "value": get("value"), "at": get("at"), "enabled": True if enabled is None else enabled,
            "name": get("name", "") or "", "label": get("label")}


def sketch_dict(sk: Any) -> dict:
    """{points, entities, constraints} with copies, from a SketchSpec or a dictionary."""
    get = (lambda k: sk.get(k, [])) if isinstance(sk, dict) else (lambda k: getattr(sk, k, None))
    pts, ents, cons = get("points"), get("entities"), get("constraints")
    if isinstance(pts, (list, tuple)):
        pts = [[p[0], p[1]] if isinstance(p, (list, tuple)) and len(p) == 2 else p for p in pts]
    if isinstance(ents, (list, tuple)):
        ents = [entity_dict(e) for e in ents]
    if isinstance(cons, (list, tuple)):
        cons = [constraint_dict(c) for c in cons]
    return {"points": pts, "entities": ents, "constraints": cons}


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------
def ref_kind(sk: dict, ref: Any) -> Optional[str]:
    """Kind of a reference (point, line, curve) or None if it does not exist."""
    if ref == ORIGIN:
        return K_POINT
    if not isinstance(ref, str) or len(ref) < 2 or ref[0] not in "pe" or not ref[1:].isdigit():
        return None
    i = int(ref[1:])
    if ref[0] == "p":
        return K_POINT if i < len(sk["points"]) else None
    if i >= len(sk["entities"]):
        return None
    kind = sk["entities"][i]["type"]
    return {"point": K_POINT, "line": K_LINE, "circle": K_CURVE, "arc": K_CURVE}.get(kind)


def owner_of_points(sk: dict) -> dict[int, int]:
    """Point index -> entity index."""
    return {p: k for k, e in enumerate(sk["entities"]) for p in e["points"]}


class Vars:
    """Access to the geometry of a sketch in the vector of unknowns x = [x0, y0, x1, y1, ..., r_circle, ...]."""

    def __init__(self, sk: dict):
        self.sk = sk
        self.n_points = len(sk["points"])
        self.radius_slot = {}
        for k, e in enumerate(sk["entities"]):
            if e["type"] == "circle":
                self.radius_slot[k] = 2 * self.n_points + len(self.radius_slot)
        self.size = 2 * self.n_points + len(self.radius_slot)

    def vector(self) -> Vector:
        x = [float(v) for p in self.sk["points"] for v in p]
        for k in self.radius_slot:
            x.append(float(self.sk["entities"][k]["radius"]))
        return x

    def apply(self, x: Vector) -> dict:
        """Copy of the sketch with the positions and radii of x."""
        points = [[x[2 * i], x[2 * i + 1]] for i in range(self.n_points)]
        entities = [dict(e) for e in self.sk["entities"]]
        for k, slot in self.radius_slot.items():
            entities[k]["radius"] = x[slot]
        return {"points": points, "entities": entities, "constraints": [dict(c) for c in self.sk["constraints"]]}

    # -- Geometry ---------------------------------------------------------------------
    def point(self, x: Vector, ref: str) -> Point:
        if ref == ORIGIN:
            return 0.0, 0.0
        i = int(ref[1:])
        if ref[0] == "e":
            i = self.sk["entities"][i]["points"][0]
        return x[2 * i], x[2 * i + 1]

    def point_index(self, ref: str) -> Optional[int]:
        """Index in the point pool (None for the origin)."""
        if ref == ORIGIN:
            return None
        i = int(ref[1:])
        return self.sk["entities"][i]["points"][0] if ref[0] == "e" else i

    def line(self, x: Vector, ref: str) -> tuple[Point, Point]:
        a, b = self.sk["entities"][int(ref[1:])]["points"]
        return (x[2 * a], x[2 * a + 1]), (x[2 * b], x[2 * b + 1])

    def curve(self, x: Vector, ref: str) -> tuple[Point, float]:
        """Centre and radius of a circle or arc."""
        k = int(ref[1:])
        e = self.sk["entities"][k]
        c = e["points"][0]
        centre = (x[2 * c], x[2 * c + 1])
        if e["type"] == "circle":
            return centre, x[self.radius_slot[k]]
        s = e["points"][1]
        return centre, math.hypot(x[2 * s] - centre[0], x[2 * s + 1] - centre[1])


# ---------------------------------------------------------------------------
# Structure check
# ---------------------------------------------------------------------------
def validate_structure(sk: dict, prefix: str = "motor.sketch") -> list[str]:
    """Check types, indices and numbers of points and entities. Constraints are checked in constraints.py."""
    pts, ents, cons = sk.get("points"), sk.get("entities"), sk.get("constraints")
    if not isinstance(pts, list) or not isinstance(ents, list) or not isinstance(cons, list):
        return [tr("sketch.not_lists", prefix=prefix)]
    errs: list[str] = []
    if len(pts) > MAX_POINTS:
        errs.append(tr("sketch.max_points", prefix=prefix, max=MAX_POINTS, n=len(pts)))
    if len(ents) > MAX_ENTITIES:
        errs.append(tr("sketch.max_entities", prefix=prefix, max=MAX_ENTITIES, n=len(ents)))
    if len(cons) > MAX_CONSTRAINTS:
        errs.append(tr("sketch.too_many_constraints", prefix=prefix, max=MAX_CONSTRAINTS))
    if errs:
        return errs
    for i, p in enumerate(pts):
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(is_finite_number(v) for v in p)):
            errs.append(tr("sketch.point_format", path=f"{prefix}.points[{i}]"))
    used: dict[int, int] = {}
    for k, e in enumerate(ents):
        errs.extend(_entity_errors(e, k, len(pts), used, f"{prefix}.entities[{k}]"))
    return errs


def _entity_errors(e: dict, k: int, n_points: int, used: dict[int, int], tag: str) -> list[str]:
    errs: list[str] = []
    count = ENTITY_POINTS.get(e["type"]) if isinstance(e["type"], str) else None
    if count is None:
        return [tr("sketch.unknown_entity", tag=tag, type=e["type"], allowed=sorted(ENTITY_POINTS))]
    points = e["points"]
    if not isinstance(points, list) or len(points) != count:
        return [tr("sketch.entity_points", tag=tag, n=count)]
    for p in points:
        if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < n_points:
            errs.append(tr("sketch.point_missing", path=f"{tag}.points", index=p, last=n_points - 1))
        elif p in used:
            errs.append(tr("sketch.point_shared", path=f"{tag}.points", index=p, other=used[p]))
        else:
            used[p] = k
    if e["type"] == "circle" and not (is_finite_number(e["radius"]) and e["radius"] > MIN_RADIUS):
        errs.append(tr("sketch.radius_positive", path=f"{tag}.radius"))
    if not isinstance(e["construction"], bool):
        errs.append(tr("value.bool", path=f"{tag}.construction"))
    if e["role"] not in ROLES:
        errs.append(tr("value.enum", path=f"{tag}.role", value=e["role"], allowed=list(ROLES)))
    return errs


# ---------------------------------------------------------------------------
# Editing (used by the server side helpers and the tests, the UI does the same in JavaScript)
# ---------------------------------------------------------------------------
def delete_entities(sk: dict, indices: set[int]) -> dict:
    """Remove entities with their points and all constraints that refer to them. Indices are renumbered."""
    keep_e = [k for k in range(len(sk["entities"])) if k not in indices]
    removed_points = {p for k in indices for p in sk["entities"][k]["points"]}
    keep_p = [i for i in range(len(sk["points"])) if i not in removed_points]
    new_e = {old: new for new, old in enumerate(keep_e)}
    new_p = {old: new for new, old in enumerate(keep_p)}

    def remap(ref: str) -> Optional[str]:
        if ref == ORIGIN:
            return ref
        i = int(ref[1:])
        table = new_p if ref[0] == "p" else new_e
        return None if i not in table else f"{ref[0]}{table[i]}"

    constraints = []
    for c in sk["constraints"]:
        refs = [remap(r) for r in c["refs"]]
        if all(r is not None for r in refs):
            constraints.append({**c, "refs": refs})
    entities = [{**sk["entities"][k], "points": [new_p[p] for p in sk["entities"][k]["points"]]} for k in keep_e]
    return {"points": [list(sk["points"][i]) for i in keep_p], "entities": entities, "constraints": constraints}
