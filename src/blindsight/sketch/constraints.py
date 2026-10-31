"""Registry of the sketch constraints (relations and dimensions, modelled after Onshape).

Every constraint type is exactly one entry in ``CONSTRAINT_TYPES``. Derived from it are
  * the check of the references (which combinations of points, lines and curves are allowed)
  * the equations for the solver (``residuals``)
  * labels and the schema for the web UI (``constraint_schema``)

Relations   coincident, horizontal, vertical, parallel, perpendicular, equal, midpoint, concentric, fix
Dimensions  distance, hdistance, vdistance, length, angle, diameter, radius (with a value)

A reference "point" is a point, a point entity or the origin "o". "curve" is a circle or an arc.
The references of a constraint may come in any order, ``match`` sorts them to the order of a signature.

Extending. A new type is a residual factory ``(refs, c, vars, x0) -> (x -> list of residuals)``, an entry
in ``CONSTRAINT_TYPES`` and its label in the catalogs (``constraint.<name>``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..i18n import LocalText, tr
from ..units import is_finite_number
from .entities import K_CURVE, K_LINE, K_POINT, Vars, Vector, ref_kind

MIN_NORM = 1e-12  # lower limit of vector lengths (no division by 0)
EPS_LEN = 1e-9

Residuals = Callable[[Vector], list[float]]
Factory = Callable[[list[str], dict, Vars, Vector], Residuals]


def _norm(v) -> float:
    return max(math.hypot(v[0], v[1]), MIN_NORM)


def _cross(u, v) -> float:
    return u[0] * v[1] - u[1] * v[0]


def _dot(u, v) -> float:
    return u[0] * v[0] + u[1] * v[1]


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def wrap_angle(angle_rad: float) -> float:
    """Map an angle to [-pi, pi)."""
    return (angle_rad + math.pi) % (2 * math.pi) - math.pi


def _sign(value: float) -> float:
    return -1.0 if value < 0 else 1.0


def _point_line_distance(p, a, b) -> float:
    """Signed distance of p to the line through a and b (positive left of a -> b)."""
    d = _sub(b, a)
    return _cross(d, _sub(p, a)) / _norm(d)


# ---------------------------------------------------------------------------
# Residual factories. Each returns a function x -> list of residuals (0 = satisfied).
# ---------------------------------------------------------------------------
def _coincident(refs, c, v: Vars, x0) -> Residuals:
    p, other = refs
    kind = ref_kind(v.sk, other)
    if kind == K_POINT:
        return lambda x: list(_sub(v.point(x, p), v.point(x, other)))
    if kind == K_LINE:
        return lambda x: [_point_line_distance(v.point(x, p), *v.line(x, other))]

    def on_curve(x):
        centre, r = v.curve(x, other)
        return [math.hypot(*_sub(v.point(x, p), centre)) - r]
    return on_curve


def _axis_aligned(axis: int) -> Factory:
    """horizontal (axis 1, equal y) or vertical (axis 0, equal x) for a line or two points."""
    def factory(refs, c, v: Vars, x0) -> Residuals:
        if len(refs) == 1:
            return lambda x: [v.line(x, refs[0])[1][axis] - v.line(x, refs[0])[0][axis]]
        return lambda x: [v.point(x, refs[1])[axis] - v.point(x, refs[0])[axis]]
    return factory


def _direction(v: Vars, x, ref):
    a, b = v.line(x, ref)
    return _sub(b, a)


def _parallel(refs, c, v: Vars, x0) -> Residuals:
    def residuals(x):
        d1, d2 = _direction(v, x, refs[0]), _direction(v, x, refs[1])
        return [_cross(d1, d2) / (_norm(d1) * _norm(d2))]
    return residuals


def _perpendicular(refs, c, v: Vars, x0) -> Residuals:
    def residuals(x):
        d1, d2 = _direction(v, x, refs[0]), _direction(v, x, refs[1])
        return [_dot(d1, d2) / (_norm(d1) * _norm(d2))]
    return residuals


def _equal(refs, c, v: Vars, x0) -> Residuals:
    if ref_kind(v.sk, refs[0]) == K_LINE:
        return lambda x: [_norm(_direction(v, x, refs[0])) - _norm(_direction(v, x, refs[1]))]
    return lambda x: [v.curve(x, refs[0])[1] - v.curve(x, refs[1])[1]]


def _midpoint(refs, c, v: Vars, x0) -> Residuals:
    def residuals(x):
        p = v.point(x, refs[0])
        a, b = v.line(x, refs[1])
        return [p[0] - (a[0] + b[0]) / 2.0, p[1] - (a[1] + b[1]) / 2.0]
    return residuals


def _concentric(refs, c, v: Vars, x0) -> Residuals:
    def centre(x, ref):
        return v.curve(x, ref)[0] if ref_kind(v.sk, ref) == K_CURVE else v.point(x, ref)
    return lambda x: list(_sub(centre(x, refs[0]), centre(x, refs[1])))


def _fix(refs, c, v: Vars, x0) -> Residuals:
    at = c["at"] if c.get("at") is not None else v.point(x0, refs[0])
    return lambda x: list(_sub(v.point(x, refs[0]), at))


def _distance(refs, c, v: Vars, x0) -> Residuals:
    value = c["value"]
    first, second = refs
    kinds = (ref_kind(v.sk, first), ref_kind(v.sk, second))
    if kinds == (K_POINT, K_POINT):
        return lambda x: [math.hypot(*_sub(v.point(x, first), v.point(x, second))) - value]
    if kinds == (K_POINT, K_LINE):
        sign = _sign(_point_line_distance(v.point(x0, first), *v.line(x0, second)))
        return lambda x: [sign * _point_line_distance(v.point(x, first), *v.line(x, second)) - value]

    def mid(x):  # two lines. Distance of the midpoint of the second line to the first line
        a, b = v.line(x, second)
        return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    sign = _sign(_point_line_distance(mid(x0), *v.line(x0, first)))
    return lambda x: [sign * _point_line_distance(mid(x), *v.line(x, first)) - value]


def _axis_distance(axis: int) -> Factory:
    """hdistance (axis 0) or vdistance (axis 1) between two points. The sign comes from the start position."""
    def factory(refs, c, v: Vars, x0) -> Residuals:
        value = c["value"]
        sign = _sign(v.point(x0, refs[1])[axis] - v.point(x0, refs[0])[axis])
        return lambda x: [sign * (v.point(x, refs[1])[axis] - v.point(x, refs[0])[axis]) - value]
    return factory


def _length(refs, c, v: Vars, x0) -> Residuals:
    return lambda x: [_norm(_direction(v, x, refs[0])) - c["value"]]


def _outward_ends(v: Vars, a: str, b: str) -> tuple[int, int]:
    """For lines a and b the index (0 or 1) of the end where they meet.

    The angle is measured between the directions pointing away from these ends, so two lines meeting at a
    corner give the angle at that corner (like Onshape). The ends must be joined by a coincident constraint,
    so the choice does not depend on positions and stays stable while dragging. Lines that do not meet use
    their own directions (start to end)."""
    ends_a = [f"p{p}" for p in v.sk["entities"][int(a[1:])]["points"]]
    ends_b = [f"p{p}" for p in v.sk["entities"][int(b[1:])]["points"]]
    for c in v.sk["constraints"]:
        if c.get("type") == "coincident" and c.get("enabled", True) and len(c.get("refs") or []) == 2:
            for i, ra in enumerate(ends_a):
                for j, rb in enumerate(ends_b):
                    if set(c["refs"]) == {ra, rb}:
                        return i, j
    return 0, 0


def _away(v: Vars, x, ref, near: int):
    ends = v.line(x, ref)
    return _sub(ends[1 - near], ends[near])


def _angle(refs, c, v: Vars, x0) -> Residuals:
    # The sense of rotation from the first to the second line is fixed by the start position so that the
    # equation stays smooth near it
    a, b = refs
    i, j = _outward_ends(v, a, b)
    sign = -1.0 if _cross(_away(v, x0, a, i), _away(v, x0, b, j)) < 0 else 1.0
    target = sign * math.radians(c["value"])

    def residuals(x):
        d1, d2 = _away(v, x, a, i), _away(v, x, b, j)
        return [wrap_angle(math.atan2(_cross(d1, d2), _dot(d1, d2)) - target)]
    return residuals


def measured_angle(v: Vars, x, a: str, b: str) -> float:
    """Angle in degrees (0 to 180) between two lines as the angle dimension measures it."""
    i, j = _outward_ends(v, a, b)
    d1, d2 = _away(v, x, a, i), _away(v, x, b, j)
    return math.degrees(abs(math.atan2(_cross(d1, d2), _dot(d1, d2))))


def _diameter(refs, c, v: Vars, x0) -> Residuals:
    return lambda x: [2.0 * v.curve(x, refs[0])[1] - c["value"]]


def _radius(refs, c, v: Vars, x0) -> Residuals:
    return lambda x: [v.curve(x, refs[0])[1] - c["value"]]


# ---------------------------------------------------------------------------
# Check of the values. Returns "" or a message (without field path).
# ---------------------------------------------------------------------------
def _positive(value: float) -> str:
    return "" if value > EPS_LEN else tr("sketch.length_positive")


def _non_negative(value: float) -> str:
    return "" if value >= 0 else tr("sketch.distance_negative")


def _angle_range(value: float) -> str:
    return "" if 0 <= value <= 180 else tr("sketch.side_angle_range")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
P, L, C = K_POINT, K_LINE, K_CURVE


@dataclass(frozen=True)
class ConstraintType:
    name: str
    residuals: Factory
    signatures: tuple[tuple[str, ...], ...]  # allowed kinds of the references, in the order of the factory
    value: Optional[str] = None  # unit of value. "len" (mm), "deg" or None (no value, a relation)
    check_value: Optional[Callable[[float], str]] = None

    @property
    def label(self) -> LocalText:
        return tr(f"constraint.{self.name}")

    @property
    def is_dimension(self) -> bool:
        return self.value is not None

    def as_schema(self) -> dict:
        return {"name": self.name, "label": self.label, "signatures": [list(s) for s in self.signatures],
                "value": self.value}


CONSTRAINT_TYPES: dict[str, ConstraintType] = {
    t.name: t
    for t in (
        ConstraintType("coincident", _coincident, ((P, P), (P, L), (P, C))),
        ConstraintType("horizontal", _axis_aligned(1), ((L,), (P, P))),
        ConstraintType("vertical", _axis_aligned(0), ((L,), (P, P))),
        ConstraintType("parallel", _parallel, ((L, L),)),
        ConstraintType("perpendicular", _perpendicular, ((L, L),)),
        ConstraintType("equal", _equal, ((L, L), (C, C))),
        ConstraintType("midpoint", _midpoint, ((P, L),)),
        ConstraintType("concentric", _concentric, ((C, C), (C, P))),
        ConstraintType("fix", _fix, ((P,),)),
        ConstraintType("distance", _distance, ((P, P), (P, L), (L, L)), "len", _non_negative),
        ConstraintType("hdistance", _axis_distance(0), ((P, P),), "len", _non_negative),
        ConstraintType("vdistance", _axis_distance(1), ((P, P),), "len", _non_negative),
        ConstraintType("length", _length, ((L,),), "len", _positive),
        ConstraintType("angle", _angle, ((L, L),), "deg", _angle_range),
        ConstraintType("diameter", _diameter, ((C,),), "len", _positive),
        ConstraintType("radius", _radius, ((C,),), "len", _positive),
    )
}


def match(sk: dict, c: dict) -> Optional[list[str]]:
    """References of c sorted to the order of a signature of its type, or None if no signature fits."""
    ctype = CONSTRAINT_TYPES.get(c["type"])
    refs = c["refs"]
    if ctype is None or not isinstance(refs, list):
        return None
    kinds = [ref_kind(sk, r) for r in refs]
    if None in kinds:
        return None
    for signature in ctype.signatures:
        if len(signature) != len(refs):
            continue
        if list(signature) == kinds:
            return list(refs)
        if len(refs) == 2 and list(signature) == kinds[::-1]:
            return list(refs[::-1])
    return None


def constraint_errors(sk: dict, c: dict, tag: str) -> list[str]:
    """Problems of one constraint (type, references, value, flags), with field path."""
    ctype = CONSTRAINT_TYPES.get(c["type"]) if isinstance(c["type"], str) else None
    if ctype is None:
        return [tr("sketch.unknown_type", tag=tag, type=c["type"], allowed=sorted(CONSTRAINT_TYPES))]
    errs: list[str] = []
    if match(sk, c) is None:
        errs.append(tr("sketch.bad_refs", path=f"{tag}.refs", type=ctype.label))
    elif len(set(c["refs"])) != len(c["refs"]):
        errs.append(tr("sketch.same_refs", path=f"{tag}.refs"))
    if ctype.value is not None:
        if not is_finite_number(c["value"]):
            errs.append(tr("sketch.number_required", path=f"{tag}.value"))
        elif ctype.check_value is not None:
            message = ctype.check_value(c["value"])
            if message:
                errs.append(tr("sketch.value_message", path=f"{tag}.value", message=message))
    at = c.get("at")
    if at is not None and not (isinstance(at, (list, tuple)) and len(at) == 2 and all(is_finite_number(v) for v in at)):
        errs.append(tr("sketch.point_format", path=f"{tag}.at"))
    label = c.get("label")
    if label is not None and not (isinstance(label, (list, tuple)) and len(label) == 2 and all(is_finite_number(v) for v in label)):
        errs.append(tr("sketch.point_format", path=f"{tag}.label"))
    if not isinstance(c["enabled"], bool):
        errs.append(tr("value.bool", path=f"{tag}.enabled"))
    if not isinstance(c["name"], str):
        errs.append(tr("value.text", path=f"{tag}.name"))
    return errs


def compile_constraint(sk: dict, c: dict, v: Vars, x0: Vector) -> Residuals:
    """Residual function of a (checked) constraint."""
    return CONSTRAINT_TYPES[c["type"]].residuals(match(sk, c), c, v, x0)


def implicit_residuals(sk: dict, v: Vars) -> list[Residuals]:
    """Equations that belong to the entities themselves. An arc has one radius, |start - centre| = |end - centre|."""
    out = []
    for e in sk["entities"]:
        if e["type"] == "arc":
            c, s, t = e["points"]

            def same_radius(x, c=c, s=s, t=t):
                centre = (x[2 * c], x[2 * c + 1])
                return [math.hypot(x[2 * s] - centre[0], x[2 * s + 1] - centre[1]) -
                        math.hypot(x[2 * t] - centre[0], x[2 * t + 1] - centre[1])]
            out.append(same_radius)
    return out


def constraint_label(c: dict, k: int) -> LocalText:
    """Readable label for messages, e.g. 'Length (e2) [no. 3]' (counting from 1)."""
    ctype = CONSTRAINT_TYPES.get(c["type"])
    base = ctype.label if ctype else str(c["type"])
    return tr("sketch.constraint_label", name=c["name"] or base, where=list(c["refs"]), number=k + 1)


def constraint_schema() -> list[dict[str, Any]]:
    """Description of all types for the web UI (order as in the registry)."""
    return [t.as_schema() for t in CONSTRAINT_TYPES.values()]
