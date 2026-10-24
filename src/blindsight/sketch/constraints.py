"""Registry of the sketch constraints.

Every constraint type is exactly one entry in ``CONSTRAINT_TYPES``. Derived from it are
  * the structure check (which fields are sides, which points, which values are needed)
  * the equations for the solver (``residuals``)
  * the reindexing when a point is inserted (``on_split``)
  * labels and the schema for the web UI (``constraint_schema``)

Extending. Adding a new type means
  1. write a residual factory ``(c, geo) -> (x -> list of residuals)``
  2. add a ``ConstraintType`` entry to ``CONSTRAINT_TYPES`` and its label to the catalogs
     (key ``constraint.<name>``)
  3. optionally add a tool button in the UI (label and value kind come along via /api/schema)

Naming. Side i runs from point i to point i+1 (cyclic). The interior angle at point i lies between side
i-1 and side i. References are the rod axis (rod, origin) and the gear axis (gear, at (-centre
distance, 0)).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..i18n import LocalText, tr

EPS_LEN = 1e-9  # shortest permitted side (mm)
MIN_NORM = 1e-12  # lower limit of vector lengths (no division by 0)

REFS = ("rod", "gear")  # labels in the catalogs (key ref.<name>)

Vector = list[float]  # unknowns of the solver. [x0, y0, x1, y1, ...]
Residuals = Callable[[Vector], list[float]]


# ---------------------------------------------------------------------------
# Access to points and sides in the vector of unknowns
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SketchGeometry:
    """Context for the residual factories. n points, centre distance cd, start position x0."""

    n: int
    cd: float
    x0: Vector

    def point(self, x: Vector, i: int) -> tuple[float, float]:
        return x[2 * i], x[2 * i + 1]

    def side(self, x: Vector, s: int) -> tuple[float, float]:
        """Direction vector of side s (from point s to point s+1)."""
        ax, ay = self.point(x, s)
        bx, by = self.point(x, (s + 1) % self.n)
        return bx - ax, by - ay

    def ref(self, name: str) -> tuple[float, float]:
        """Position of a reference (rod or gear) in the rod frame."""
        return (0.0, 0.0) if name == "rod" else (-self.cd, 0.0)


def _norm(v: tuple[float, float]) -> float:
    return max(math.hypot(*v), MIN_NORM)


def _cross(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[1] - u[1] * v[0]


def _dot(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[0] + u[1] * v[1]


def wrap_angle(angle_rad: float) -> float:
    """Map an angle to [-pi, pi)."""
    return (angle_rad + math.pi) % (2 * math.pi) - math.pi


# ---------------------------------------------------------------------------
# Residual factories. Each returns a function x -> list of residuals (0 = satisfied).
# ---------------------------------------------------------------------------
def _length(c: dict, geo: SketchGeometry) -> Residuals:
    side, value = c["a"], c["value"]
    return lambda x: [_norm(geo.side(x, side)) - value]


def _interior_angle(c: dict, geo: SketchGeometry) -> Residuals:
    vertex, target = c["a"], math.radians(c["value"])

    def residuals(x: Vector) -> list[float]:
        qx, qy = geo.point(x, vertex)
        px, py = geo.point(x, (vertex - 1) % geo.n)
        rx, ry = geo.point(x, (vertex + 1) % geo.n)
        to_prev, to_next = (px - qx, py - qy), (rx - qx, ry - qy)
        angle = math.atan2(_cross(to_next, to_prev), _dot(to_prev, to_next))
        return [wrap_angle(angle - target)]

    return residuals


def _angle_between_sides(c: dict, geo: SketchGeometry) -> Residuals:
    # The sign (sense of rotation from side a to b) is determined once from the start position so that
    # the equation stays smooth near the start position
    a, b = c["a"], c["b"]
    sign = -1.0 if _cross(geo.side(geo.x0, a), geo.side(geo.x0, b)) < 0 else 1.0
    target = sign * math.radians(c["value"])

    def residuals(x: Vector) -> list[float]:
        d1, d2 = geo.side(x, a), geo.side(x, b)
        return [wrap_angle(math.atan2(_cross(d1, d2), _dot(d1, d2)) - target)]

    return residuals


def _parallel(c: dict, geo: SketchGeometry) -> Residuals:
    a, b = c["a"], c["b"]

    def residuals(x: Vector) -> list[float]:
        d1, d2 = geo.side(x, a), geo.side(x, b)
        return [_cross(d1, d2) / (_norm(d1) * _norm(d2))]

    return residuals


def _perpendicular(c: dict, geo: SketchGeometry) -> Residuals:
    a, b = c["a"], c["b"]

    def residuals(x: Vector) -> list[float]:
        d1, d2 = geo.side(x, a), geo.side(x, b)
        return [_dot(d1, d2) / (_norm(d1) * _norm(d2))]

    return residuals


def _equal_length(c: dict, geo: SketchGeometry) -> Residuals:
    a, b = c["a"], c["b"]
    return lambda x: [_norm(geo.side(x, a)) - _norm(geo.side(x, b))]


def _horizontal(c: dict, geo: SketchGeometry) -> Residuals:
    side = c["a"]
    return lambda x: [geo.side(x, side)[1]]


def _vertical(c: dict, geo: SketchGeometry) -> Residuals:
    side = c["a"]
    return lambda x: [geo.side(x, side)[0]]


def _fix(c: dict, geo: SketchGeometry) -> Residuals:
    vertex, vx, vy = c["a"], c["value"], c["value2"]

    def residuals(x: Vector) -> list[float]:
        px, py = geo.point(x, vertex)
        return [px - vx, py - vy]

    return residuals


def _coord_x(c: dict, geo: SketchGeometry) -> Residuals:
    vertex, value = c["a"], c["value"]
    return lambda x: [geo.point(x, vertex)[0] - value]


def _coord_y(c: dict, geo: SketchGeometry) -> Residuals:
    vertex, value = c["a"], c["value"]
    return lambda x: [geo.point(x, vertex)[1] - value]


def _distance_point_ref(c: dict, geo: SketchGeometry) -> Residuals:
    vertex, value = c["a"], c["value"]
    rx, ry = geo.ref(c["ref"])

    def residuals(x: Vector) -> list[float]:
        px, py = geo.point(x, vertex)
        return [math.hypot(px - rx, py - ry) - value]

    return residuals


def _distance_side_ref(c: dict, geo: SketchGeometry) -> Residuals:
    side, value = c["a"], c["value"]
    rx, ry = geo.ref(c["ref"])

    def signed_distance(x: Vector) -> float:
        """Perpendicular distance of the reference to the line through the side, positive left of the side (inside)."""
        d = geo.side(x, side)
        px, py = geo.point(x, side)
        return _cross(d, (rx - px, ry - py)) / _norm(d)

    # Reference inside (+) or outside (-) the side, fixed by the start position
    sign = 1.0 if signed_distance(geo.x0) > 0 else -1.0
    return lambda x: [signed_distance(x) - sign * value]


# ---------------------------------------------------------------------------
# Check of the numbers. Returns "" or a message (without field path).
# ---------------------------------------------------------------------------
def _positive_length(v: float) -> str:
    return "" if v > EPS_LEN else tr("sketch.length_positive")


def _interior_angle_range(v: float) -> str:
    return "" if 0 < v < 180 else tr("sketch.interior_angle_range")


def _side_angle_range(v: float) -> str:
    return "" if 0 <= v <= 180 else tr("sketch.side_angle_range")


def _non_negative(v: float) -> str:
    return "" if v >= 0 else tr("sketch.distance_negative")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
SPLIT_DROP = "drop"  # a reference to a split side is dropped (lengths)
SPLIT_BOTH = "both"  # the reference holds for both halves (directions lie on the same line)


@dataclass(frozen=True)
class ConstraintType:
    name: str
    residuals: Callable[[dict, SketchGeometry], Residuals]
    sides: tuple[str, ...] = ()  # fields that are side indices
    points: tuple[str, ...] = ()  # fields that are point indices
    value: Optional[str] = None  # unit of value. "len" (mm), "deg" or None (no value)
    value2: Optional[str] = None  # unit of value2 or None
    check_value: Optional[Callable[[float], str]] = None
    uses_ref: bool = False  # uses the field ref (rod or gear)
    on_split: str = SPLIT_BOTH  # behaviour when a point is inserted on a referenced side

    @property
    def label(self) -> LocalText:
        return tr(f"constraint.{self.name}")

    @property
    def index_fields(self) -> tuple[str, ...]:
        return self.sides + self.points

    def as_schema(self) -> dict:
        return {
            "name": self.name, "label": self.label, "sides": list(self.sides), "points": list(self.points),
            "value": self.value, "value2": self.value2, "ref": self.uses_ref,
        }


CONSTRAINT_TYPES: dict[str, ConstraintType] = {
    t.name: t
    for t in (
        ConstraintType("length", _length, sides=("a",), value="len", check_value=_positive_length,
                       on_split=SPLIT_DROP),
        ConstraintType("angle", _interior_angle, points=("a",), value="deg", check_value=_interior_angle_range),
        ConstraintType("angle_sides", _angle_between_sides, sides=("a", "b"), value="deg",
                       check_value=_side_angle_range),
        ConstraintType("parallel", _parallel, sides=("a", "b")),
        ConstraintType("perpendicular", _perpendicular, sides=("a", "b")),
        ConstraintType("equal", _equal_length, sides=("a", "b"), on_split=SPLIT_DROP),
        ConstraintType("horizontal", _horizontal, sides=("a",)),
        ConstraintType("vertical", _vertical, sides=("a",)),
        ConstraintType("fix", _fix, points=("a",), value="len", value2="len"),
        ConstraintType("coord_x", _coord_x, points=("a",), value="len"),
        ConstraintType("coord_y", _coord_y, points=("a",), value="len"),
        ConstraintType("dist_point", _distance_point_ref, points=("a",), value="len",
                       check_value=_non_negative, uses_ref=True),
        ConstraintType("dist_side", _distance_side_ref, sides=("a",), value="len",
                       check_value=_non_negative, uses_ref=True),
    )
}

# Derived table. name -> (side fields, point fields, needs value, needs value2)
SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool, bool]] = {
    t.name: (t.sides, t.points, t.value is not None, t.value2 is not None) for t in CONSTRAINT_TYPES.values()
}


def compile_constraint(c: dict, geo: SketchGeometry) -> Residuals:
    """Residual function of a (structurally checked) constraint."""
    return CONSTRAINT_TYPES[c["type"]].residuals(c, geo)


def constraint_label(c: dict, k: int) -> str:
    """Readable label for messages, e.g. 'Length (Side 2) [no. 3]' (counting from 1)."""
    ctype = CONSTRAINT_TYPES.get(c["type"])
    base = ctype.label if ctype else str(c["type"])
    where = []
    if ctype:
        where += [tr("sketch.side", n=c[f] + 1) for f in ctype.sides]
        where += [tr("sketch.point", n=c[f] + 1) for f in ctype.points]
    return tr("sketch.constraint_label", name=c["name"] or base, where=where, number=k + 1)


def constraint_schema() -> list[dict[str, Any]]:
    """Description of all types for the web UI (order as in the registry)."""
    return [t.as_schema() for t in CONSTRAINT_TYPES.values()]
