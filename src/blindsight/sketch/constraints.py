"""Register der Skizzen Constraints.

Jeder Constraint Typ ist genau ein Eintrag in ``CONSTRAINT_TYPES``. Daraus leiten sich ab
  * die Strukturpruefung (welche Felder sind Seiten, welche Punkte, welche Werte noetig)
  * die Gleichungen fuer den Solver (``residuals``)
  * das Umindizieren beim Einfuegen eines Punktes (``on_split``)
  * Beschriftungen und das Schema fuer die Web UI (``constraint_schema``)

Erweitern. Einen neuen Typ anlegen heisst
  1. eine Residuen Fabrik ``(c, geo) -> (x -> Liste von Residuen)`` schreiben
  2. einen ``ConstraintType`` Eintrag in ``CONSTRAINT_TYPES`` ergaenzen
  3. optional in der UI einen Werkzeugknopf hinzufuegen (Beschriftung und Werteart kommen
     ueber /api/schema mit)

Bezeichnungen. Seite i geht von Punkt i nach Punkt i+1 (zyklisch). Der Innenwinkel an Punkt i
liegt zwischen Seite i-1 und Seite i. Referenzen sind die Stangenachse (rod, Ursprung) und die
Zahnradachse (gear, bei (-Achsabstand, 0)).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

EPS_LEN = 1e-9  # kuerzeste erlaubte Seite (mm)
MIN_NORM = 1e-12  # Untergrenze fuer Vektorlaengen (keine Division durch 0)

REFS = ("rod", "gear")
REF_LABELS = {"rod": "Stange", "gear": "Zahnrad"}

Vector = list[float]  # Unbekannte des Solvers. [x0, y0, x1, y1, ...]
Residuals = Callable[[Vector], list[float]]


# ---------------------------------------------------------------------------
# Zugriff auf Punkte und Seiten im Unbekanntenvektor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SketchGeometry:
    """Kontext fuer die Residuen Fabriken. n Punkte, Achsabstand cd, Startlage x0."""

    n: int
    cd: float
    x0: Vector

    def point(self, x: Vector, i: int) -> tuple[float, float]:
        return x[2 * i], x[2 * i + 1]

    def side(self, x: Vector, s: int) -> tuple[float, float]:
        """Richtungsvektor der Seite s (von Punkt s zu Punkt s+1)."""
        ax, ay = self.point(x, s)
        bx, by = self.point(x, (s + 1) % self.n)
        return bx - ax, by - ay

    def ref(self, name: str) -> tuple[float, float]:
        """Position einer Referenz (rod oder gear) im Stangenrahmen."""
        return (0.0, 0.0) if name == "rod" else (-self.cd, 0.0)


def _norm(v: tuple[float, float]) -> float:
    return max(math.hypot(*v), MIN_NORM)


def _cross(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[1] - u[1] * v[0]


def _dot(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[0] + u[1] * v[1]


def wrap_angle(angle_rad: float) -> float:
    """Winkel auf [-pi, pi) abbilden."""
    return (angle_rad + math.pi) % (2 * math.pi) - math.pi


# ---------------------------------------------------------------------------
# Residuen Fabriken. Jede liefert eine Funktion x -> Liste von Residuen (0 = erfuellt).
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
    # Das Vorzeichen (Drehsinn von Seite a nach b) wird einmal aus der Startlage bestimmt,
    # damit die Gleichung in der Naehe der Startlage glatt bleibt
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
        """Lotabstand der Referenz zur Geraden durch die Seite, positiv links der Seite (innen)."""
        d = geo.side(x, side)
        px, py = geo.point(x, side)
        return _cross(d, (rx - px, ry - py)) / _norm(d)

    # Referenz innerhalb (+) oder ausserhalb (-) der Seite, festgelegt durch die Startlage
    sign = 1.0 if signed_distance(geo.x0) > 0 else -1.0
    return lambda x: [signed_distance(x) - sign * value]


# ---------------------------------------------------------------------------
# Pruefung der Zahlenwerte. Liefert "" oder eine Meldung (ohne Feldpfad).
# ---------------------------------------------------------------------------
def _positive_length(v: float) -> str:
    return "" if v > EPS_LEN else "Laenge muss groesser als 0 sein"


def _interior_angle_range(v: float) -> str:
    return "" if 0 < v < 180 else "Innenwinkel muss zwischen 0 und 180 Grad liegen (exklusiv)"


def _side_angle_range(v: float) -> str:
    return "" if 0 <= v <= 180 else "Winkel muss zwischen 0 und 180 Grad liegen"


def _non_negative(v: float) -> str:
    return "" if v >= 0 else "Abstand darf nicht negativ sein"


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
SPLIT_DROP = "drop"  # Bezug auf eine geteilte Seite entfaellt (Laengen)
SPLIT_BOTH = "both"  # Bezug gilt fuer beide Haelften (Richtungen liegen auf derselben Geraden)


@dataclass(frozen=True)
class ConstraintType:
    name: str
    label: str
    residuals: Callable[[dict, SketchGeometry], Residuals]
    sides: tuple[str, ...] = ()  # Felder, die Seitenindizes sind
    points: tuple[str, ...] = ()  # Felder, die Punktindizes sind
    value: Optional[str] = None  # Einheit von value. "len" (mm), "deg" oder None (kein Wert)
    value2: Optional[str] = None  # Einheit von value2 oder None
    check_value: Optional[Callable[[float], str]] = None
    uses_ref: bool = False  # nutzt das Feld ref (rod oder gear)
    on_split: str = SPLIT_BOTH  # Verhalten, wenn ein Punkt auf einer Bezugsseite eingefuegt wird

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
        ConstraintType("length", "Laenge", _length, sides=("a",), value="len", check_value=_positive_length,
                       on_split=SPLIT_DROP),
        ConstraintType("angle", "Winkel", _interior_angle, points=("a",), value="deg", check_value=_interior_angle_range),
        ConstraintType("angle_sides", "Winkel zwischen Seiten", _angle_between_sides, sides=("a", "b"), value="deg",
                       check_value=_side_angle_range),
        ConstraintType("parallel", "Parallel", _parallel, sides=("a", "b")),
        ConstraintType("perpendicular", "Rechtwinklig", _perpendicular, sides=("a", "b")),
        ConstraintType("equal", "Gleich lang", _equal_length, sides=("a", "b"), on_split=SPLIT_DROP),
        ConstraintType("horizontal", "Horizontal", _horizontal, sides=("a",)),
        ConstraintType("vertical", "Vertikal", _vertical, sides=("a",)),
        ConstraintType("fix", "Fixiert", _fix, points=("a",), value="len", value2="len"),
        ConstraintType("coord_x", "x Koordinate", _coord_x, points=("a",), value="len"),
        ConstraintType("coord_y", "y Koordinate", _coord_y, points=("a",), value="len"),
        ConstraintType("dist_point", "Abstand Punkt", _distance_point_ref, points=("a",), value="len",
                       check_value=_non_negative, uses_ref=True),
        ConstraintType("dist_side", "Abstand Seite", _distance_side_ref, sides=("a",), value="len",
                       check_value=_non_negative, uses_ref=True),
    )
}

# Abgeleitete Tabellen (Namen aus frueheren Versionen)
# SPEC. name -> (Seitenfelder, Punktfelder, braucht value, braucht value2)
SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool, bool]] = {
    t.name: (t.sides, t.points, t.value is not None, t.value2 is not None) for t in CONSTRAINT_TYPES.values()
}
LABELS: dict[str, str] = {t.name: t.label for t in CONSTRAINT_TYPES.values()}


def compile_constraint(c: dict, geo: SketchGeometry) -> Residuals:
    """Residuen Funktion fuer einen (strukturell geprueften) Constraint."""
    return CONSTRAINT_TYPES[c["type"]].residuals(c, geo)


def constraint_label(c: dict, k: int) -> str:
    """Lesbare Bezeichnung fuer Meldungen, z.B. 'Laenge (Seite 2) [Nr. 3]' (Zaehlung ab 1)."""
    ctype = CONSTRAINT_TYPES.get(c["type"])
    base = ctype.label if ctype else str(c["type"])
    where = []
    if ctype:
        where += [f"Seite {c[f] + 1}" for f in ctype.sides]
        where += [f"Punkt {c[f] + 1}" for f in ctype.points]
    return f"{c['name'] or base} ({', '.join(where)}) [Nr. {k + 1}]"


def constraint_schema() -> list[dict[str, Any]]:
    """Beschreibung aller Typen fuer die Web UI (Reihenfolge wie im Register)."""
    return [t.as_schema() for t in CONSTRAINT_TYPES.values()]
