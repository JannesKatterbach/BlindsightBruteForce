"""Layout (Menge platzierter Einheiten) und Kollisionspruefung.

Ein Layout haelt Platzierungen (Stangenposition, Motorebene, Motorwinkel, Achsabstand)
und prueft neue Platzierungen inkrementell gegen die bereits vorhandenen. Ein
Raumraster beschleunigt die Nachbarsuche.

Regel. Zwei Bauteile sind nur dann kollisionsfrei, wenn ihr echter Mindestabstand
im Raum >= Sicherheitsabstand + Toleranz ist. Der eigene Eingriff Zahnrad zu
eigener Stange gehoert zum Entwurf und wird nicht geprueft.

Erweitern. Eine neue Bedingung fuer eine einzelne Einheit ist eine Funktion
``(model, placement, parts) -> Meldung`` in ``UNIT_RULES``. Sie wird dann sowohl beim
schnellen ``Layout.check`` als auch bei der vollstaendigen Pruefung ``all_collisions``
angewendet.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from .geometry import prism_distance
from .model import KIND_GEAR, KIND_HOUSING, KIND_OBSTACLE, KIND_ROD, Model, Part
from .units import ANGLE_TOL_DEG, EPS, is_finite_number, normalize_angle_deg

SIGNATURE_DIGITS = 2  # Rundung (mm, Grad) beim Vergleich zweier Layouts auf Gleichheit
REACH_SLACK = 1e-6  # Zuschlag auf die Reichweite, damit Rundung keine Nachbarn verliert

KIND_LABELS = {KIND_HOUSING: "Motor", KIND_GEAR: "Zahnrad", KIND_ROD: "Gewindestange", KIND_OBSTACLE: "Hindernis"}
_KIND_DE = KIND_LABELS  # Name aus frueheren Versionen

PLACEMENT_FIELDS = ("x", "y", "plane", "angle", "cd")


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    plane: int  # Index der Motorebene (1..n)
    angle: float  # Grad
    cd: Optional[float] = None  # Achsabstand Zahnrad zu Stange, None = nominal

    @staticmethod
    def from_dict(data: object, n_planes: int) -> "Placement":
        """Strenge Pruefung einer von aussen kommenden Platzierung (UI, JSON Dateien)."""
        if not isinstance(data, dict):
            raise ValueError("Platzierung muss ein Objekt sein")
        extra = set(data) - set(PLACEMENT_FIELDS)
        if extra:
            raise ValueError(f"Unbekannte Felder in Platzierung. {sorted(extra)}")

        def number(key: str) -> float:
            value = data.get(key)
            if not is_finite_number(value):
                raise ValueError(f"Platzierung.{key} muss eine endliche Zahl sein")
            return float(value)

        plane = data.get("plane")
        if isinstance(plane, bool) or not isinstance(plane, int) or not 1 <= plane <= n_planes:
            raise ValueError(f"Platzierung.plane muss eine ganze Zahl von 1 bis {n_planes} sein")
        cd = None
        if data.get("cd") is not None:
            cd = number("cd")
            if cd < 0:
                raise ValueError("Platzierung.cd darf nicht negativ sein")
        return Placement(number("x"), number("y"), plane, number("angle"), cd)

    def as_dict(self) -> dict:
        out = {"x": self.x, "y": self.y, "plane": self.plane, "angle": self.angle}
        if self.cd is not None:
            out["cd"] = self.cd
        return out


def layout_signature(placements: Iterable[Placement]) -> tuple:
    """Reihenfolgeunabhaengiger Schluessel eines Layouts. Gleiche Layouts (bis auf Rundung) haben
    denselben Schluessel. Der Achsabstand gehoert dazu, None wird wie 0 behandelt."""
    digits = SIGNATURE_DIGITS
    return tuple(sorted(
        (round(p.x, digits), round(p.y, digits), p.plane, round(p.angle, digits), round(p.cd or 0.0, digits))
        for p in placements
    ))


@dataclass
class Collision:
    a: int  # Unit Id, -1 bei festem Hindernis oder Bauraum
    b: int
    kind_a: str
    kind_b: str
    gap: float  # tatsaechlicher Abstand
    required: float
    x: float
    y: float
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    ok: bool
    # Bei ok die kleinste gemessene Distanz zu Nachbarn und Hindernissen. Distanzen ab dem
    # Sicherheitsabstand werden nur so genau wie noetig berechnet (prism_distance mit cutoff),
    # der Wert ist daher eine untere Schranke des echten Abstands, aber nie kleiner als gap.
    min_gap: float = math.inf
    reason: str = ""
    collisions: list[Collision] = field(default_factory=list)


class Counter:
    """Gemeinsamer Zaehler fuer untersuchte Kandidaten (ueber mehrere Layouts hinweg)."""

    def __init__(self) -> None:
        self.checks = 0


# ---------------------------------------------------------------------------
# Regeln fuer eine einzelne Einheit. Jede liefert "" (erfuellt) oder eine Meldung.
# Die Kapazitaet je Ebene haengt vom ganzen Layout ab und wird im Layout geprueft.
# ---------------------------------------------------------------------------
UnitRule = Callable[[Model, Placement, list[Part]], str]


def _rule_plane(model: Model, pl: Placement, parts: list[Part]) -> str:
    problems = model.plane_problems(pl.plane)
    return problems[0] if problems else ""


def _rule_center_distance(model: Model, pl: Placement, parts: list[Part]) -> str:
    return model.cd_problem(pl.cd)


def _rule_angle(model: Model, pl: Placement, parts: list[Part]) -> str:
    if angle_allowed(model, pl):
        return ""
    return f"Motorwinkel {pl.angle:g} Grad ist auf Ebene G{pl.plane} nicht erlaubt"


def _rule_bounds(model: Model, pl: Placement, parts: list[Part]) -> str:
    return model.within_bounds(parts, pl.plane) or ""


# (Art fuer Collision.kind_b, Regel, braucht Bauteile). Regeln ohne Bauteile laufen zuerst,
# so muessen fuer klar unzulaessige Platzierungen keine Prismen erzeugt werden.
UNIT_RULES: list[tuple[str, UnitRule, bool]] = [
    ("plane", _rule_plane, False),
    ("rod", _rule_center_distance, False),
    ("angle", _rule_angle, False),
    ("bounds", _rule_bounds, True),
]


def angle_allowed(model: Model, pl: Placement) -> bool:
    """True, wenn der Winkel (modulo 360) in der Winkelliste der Ebene liegt."""
    angle = normalize_angle_deg(pl.angle)
    for allowed in model.angles_for(pl.plane):
        diff = abs(angle - allowed)
        if diff < ANGLE_TOL_DEG or abs(diff - 360.0) < ANGLE_TOL_DEG:
            return True
    return False


_angle_allowed = angle_allowed  # Name aus frueheren Versionen


def _midpoint(p: Part, q: Part) -> tuple[float, float]:
    return 0.5 * (p.prism.fp.cx + q.prism.fp.cx), 0.5 * (p.prism.fp.cy + q.prism.fp.cy)


class Layout:
    def __init__(self, model: Model, counter: Optional[Counter] = None):
        self.model = model
        self.counter = counter or Counter()
        self.units: dict[int, Placement] = {}
        self._parts: dict[int, list[Part]] = {}
        self._grid: dict[tuple[int, int], set[int]] = {}
        self._next_id = 0
        self._plane_count: dict[int, int] = {}
        # Zwei Einheiten koennen nur kollidieren, wenn ihre Stangenachsen hoechstens
        # 2 * Einheitenradius + Abstand auseinander liegen. Das ist auch die Rasterweite.
        self._reach = 2.0 * model.unit_radius + model.gap + REACH_SLACK
        self._cell = self._reach

    @property
    def reach(self) -> float:
        """Largest rod to rod distance at which two units can still collide (mm)."""
        return self._reach

    # -- Verwaltung ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self.units)

    def placements(self) -> list[Placement]:
        return [self.units[i] for i in sorted(self.units)]

    def _cell_of(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / self._cell), math.floor(y / self._cell))

    def add(self, pl: Placement) -> int:
        """Fuegt ohne Pruefung hinzu und liefert die neue Unit Id."""
        uid = self._next_id
        self._next_id += 1
        self.units[uid] = pl
        self._plane_count[pl.plane] = self._plane_count.get(pl.plane, 0) + 1
        self._parts[uid] = self.model.unit_parts(uid, pl.x, pl.y, pl.plane, pl.angle, pl.cd)
        self._grid.setdefault(self._cell_of(pl.x, pl.y), set()).add(uid)
        return uid

    def remove(self, uid: int) -> Placement:
        pl = self.units.pop(uid)
        self._plane_count[pl.plane] -= 1
        self._parts.pop(uid)
        cell = self._cell_of(pl.x, pl.y)
        self._grid[cell].discard(uid)
        if not self._grid[cell]:
            del self._grid[cell]
        return pl

    def parts_of(self, uid: int) -> list[Part]:
        return self._parts[uid]

    def copy(self) -> "Layout":
        other = Layout(self.model, self.counter)
        for uid in sorted(self.units):
            other.add(self.units[uid])
        return other

    @property
    def checks(self) -> int:
        return self.counter.checks

    def _neighbors(self, x: float, y: float) -> list[int]:
        """Unit Ids in der eigenen und den acht umliegenden Rasterzellen."""
        cx, cy = self._cell_of(x, y)
        out = []
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                ids = self._grid.get((i, j))
                if ids:
                    out.extend(ids)
        return out

    def _in_reach(self, a: Placement, b: Placement) -> bool:
        return math.hypot(a.x - b.x, a.y - b.y) <= self._reach

    # -- Pruefung -------------------------------------------------------------
    def _capacity_problem(self, pl: Placement, ignore: Optional[int]) -> str:
        cap = self.model.capacity.get(pl.plane)
        if cap is None:
            return ""
        count = self._plane_count.get(pl.plane, 0)
        if ignore is not None and ignore in self.units and self.units[ignore].plane == pl.plane:
            count -= 1
        if count >= cap:
            return f"Ebene G{pl.plane} trägt bereits die maximale Anzahl Motoren ({cap})"
        return ""

    def check(self, pl: Placement, ignore: Optional[int] = None, collect: bool = False) -> CheckResult:
        """Prueft eine Platzierung gegen Einheitenregeln, Kapazitaet, Hindernisse und vorhandene Einheiten.

        ignore ist eine Unit Id, die nicht beruecksichtigt wird (zum Verschieben einer Einheit).
        Mit collect werden alle Kollisionen gesammelt, sonst endet die Pruefung bei der ersten.
        """
        self.counter.checks += 1
        model = self.model
        for _, rule, needs_parts in UNIT_RULES:
            if not needs_parts:
                message = rule(model, pl, [])
                if message:
                    return CheckResult(False, reason=message)
        message = self._capacity_problem(pl, ignore)
        if message:
            return CheckResult(False, reason=message)
        parts = model.unit_parts(-1, pl.x, pl.y, pl.plane, pl.angle, pl.cd)
        for _, rule, needs_parts in UNIT_RULES:
            if needs_parts:
                message = rule(model, pl, parts)
                if message:
                    return CheckResult(False, reason=message)

        gap = model.gap
        need = gap - EPS
        collisions: list[Collision] = []
        min_gap = math.inf
        for obstacle in model.obstacles:
            for p in parts:
                dist = prism_distance(p.prism, obstacle.prism, gap)
                if dist >= need:
                    min_gap = min(min_gap, dist)
                    continue
                message = (
                    f"{KIND_LABELS[p.kind]} kollidiert mit {obstacle.label} "
                    f"(Abstand {dist:.2f} mm, benötigt {gap:.2f} mm)"
                )
                if not collect:
                    return CheckResult(False, reason=message)
                collisions.append(Collision(-1, -1, p.kind, KIND_OBSTACLE, dist, gap, p.prism.fp.cx, p.prism.fp.cy, message))
        for uid in self._neighbors(pl.x, pl.y):
            if uid == ignore or not self._in_reach(self.units[uid], pl):
                continue
            for p in parts:
                for q in self._parts[uid]:
                    dist = prism_distance(p.prism, q.prism, gap)
                    if dist >= need:
                        min_gap = min(min_gap, dist)
                        continue
                    message = (
                        f"{KIND_LABELS[p.kind]} kollidiert mit {KIND_LABELS[q.kind]} von Einheit {uid} "
                        f"(Abstand {dist:.2f} mm, benötigt {gap:.2f} mm)"
                    )
                    if not collect:
                        return CheckResult(False, reason=message)
                    collisions.append(Collision(-1, uid, p.kind, q.kind, dist, gap, *_midpoint(p, q), message))
        if collisions:
            return CheckResult(False, reason=collisions[0].message, collisions=collisions)
        return CheckResult(True, min_gap=min_gap)

    def try_add(self, pl: Placement) -> Optional[int]:
        """Fuegt hinzu, wenn die Platzierung zulaessig ist. Liefert die Unit Id oder None."""
        if self.check(pl).ok:
            return self.add(pl)
        return None

    def all_collisions(self) -> list[Collision]:
        """Vollstaendige Pruefung des gesamten Layouts (fuer Visualisierung und Validierung)."""
        out: list[Collision] = []
        ids = sorted(self.units)
        for uid in ids:
            out.extend(self._unit_collisions(uid))
        out.extend(self._capacity_collisions(ids))
        out.extend(self._pair_collisions(ids))
        return out

    def _unit_collisions(self, uid: int) -> list[Collision]:
        """Verletzte Einheitenregeln und Kollisionen mit Hindernissen einer Einheit."""
        model = self.model
        gap = model.gap
        pl = self.units[uid]
        parts = self._parts[uid]
        out = []
        for kind, rule, _ in UNIT_RULES:
            message = rule(model, pl, parts)
            if message:
                out.append(Collision(uid, -1, KIND_HOUSING, kind, 0.0, gap, pl.x, pl.y, f"Einheit {uid}. {message}"))
        for obstacle in model.obstacles:
            for p in parts:
                dist = prism_distance(p.prism, obstacle.prism, gap)
                if dist < gap - EPS:
                    out.append(Collision(
                        uid, -1, p.kind, KIND_OBSTACLE, dist, gap, p.prism.fp.cx, p.prism.fp.cy,
                        f"Einheit {uid}. {KIND_LABELS[p.kind]} kollidiert mit {obstacle.label}",
                    ))
        return out

    def _capacity_collisions(self, ids: list[int]) -> list[Collision]:
        out = []
        gap = self.model.gap
        for plane, count in sorted(self._plane_count.items()):
            cap = self.model.capacity.get(plane)
            if cap is None or count <= cap:
                continue
            first = next(u for u in ids if self.units[u].plane == plane)
            pl = self.units[first]
            out.append(Collision(first, -1, KIND_HOUSING, "capacity", 0.0, gap, pl.x, pl.y,
                                 f"Ebene G{plane} trägt {count} Motoren, erlaubt sind {cap}"))
        return out

    def _pair_collisions(self, ids: list[int]) -> list[Collision]:
        """Kollisionen zwischen allen Paaren von Einheiten (ohne Raster, auch fuer unsortierte Eingaben)."""
        gap = self.model.gap
        out = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if not self._in_reach(self.units[a], self.units[b]):
                    continue
                for p in self._parts[a]:
                    for q in self._parts[b]:
                        dist = prism_distance(p.prism, q.prism, gap)
                        if dist < gap - EPS:
                            out.append(Collision(
                                a, b, p.kind, q.kind, dist, gap, *_midpoint(p, q),
                                f"Einheit {a} ({KIND_LABELS[p.kind]}) und Einheit {b} ({KIND_LABELS[q.kind]}) "
                                f"Abstand {dist:.2f} mm, benötigt {gap:.2f} mm",
                            ))
        return out

    def closest_pairs(self, limit: int = 12) -> list[dict]:
        """Die engsten Bauteilpaare verschiedener Einheiten (Abstand im Raum), aufsteigend nach Abstand."""
        found: list[dict] = []
        for a in sorted(self.units):
            pa = self.units[a]
            for b in self._neighbors(pa.x, pa.y):
                if b <= a or not self._in_reach(pa, self.units[b]):
                    continue
                closest = None
                for p in self._parts[a]:
                    for q in self._parts[b]:
                        dist = prism_distance(p.prism, q.prism)
                        if closest is None or dist < closest["gap"]:
                            x, y = _midpoint(p, q)
                            closest = {"a": a, "b": b, "kind_a": p.kind, "kind_b": q.kind, "gap": dist, "x": x, "y": y}
                if closest:
                    found.append(closest)
        return sorted(found, key=lambda row: row["gap"])[:limit]

    def is_valid(self) -> bool:
        return not self.all_collisions()


def layout_from_placements(model: Model, placements: Iterable[Placement], counter: Optional[Counter] = None) -> Layout:
    """Layout ohne Pruefung aus Platzierungen aufbauen (Kollisionen ueber all_collisions abfragen)."""
    layout = Layout(model, counter)
    for pl in placements:
        layout.add(pl)
    return layout
