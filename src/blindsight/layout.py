"""Layout (Menge platzierter Einheiten) und Kollisionspruefung.

Ein Layout haelt Platzierungen (Stangenposition, Motorebene, Motorwinkel) und
prueft neue Platzierungen inkrementell gegen die bereits vorhandenen. Ein
Raumraster beschleunigt die Nachbarsuche.

Regel. Zwei Bauteile sind nur dann kollisionsfrei, wenn ihr echter Mindestabstand
im Raum >= Sicherheitsabstand + Toleranz ist. Der eigene Eingriff Zahnrad zu
eigener Stange gehoert zum Entwurf und wird nicht geprueft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .model import Model, Part
from .geometry import prism_distance

_FLOAT_NOISE = 1e-9


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    plane: int  # Index der Motorebene (1..n)
    angle: float  # Grad
    cd: Optional[float] = None  # Achsabstand Zahnrad zu Stange, None = nominal

    @staticmethod
    def from_dict(d: object, n_planes: int) -> "Placement":
        """Strenge Pruefung einer von aussen kommenden Platzierung (UI, JSON Dateien)."""
        if not isinstance(d, dict):
            raise ValueError("Platzierung muss ein Objekt sein")
        extra = set(d) - {"x", "y", "plane", "angle", "cd"}
        if extra:
            raise ValueError(f"Unbekannte Felder in Platzierung. {sorted(extra)}")

        def num(key: str, optional: bool = False):
            v = d.get(key)
            if v is None and optional:
                return None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"Platzierung.{key} muss eine endliche Zahl sein")
            return float(v)

        plane = d.get("plane")
        if isinstance(plane, bool) or not isinstance(plane, int) or not 1 <= plane <= n_planes:
            raise ValueError(f"Platzierung.plane muss eine ganze Zahl von 1 bis {n_planes} sein")
        return Placement(num("x"), num("y"), plane, num("angle"), num("cd", True))

    def as_dict(self) -> dict:
        d = {"x": self.x, "y": self.y, "plane": self.plane, "angle": self.angle}
        if self.cd is not None:
            d["cd"] = self.cd
        return d


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
        return {
            "a": self.a,
            "b": self.b,
            "kind_a": self.kind_a,
            "kind_b": self.kind_b,
            "gap": self.gap,
            "required": self.required,
            "x": self.x,
            "y": self.y,
            "message": self.message,
        }


@dataclass
class CheckResult:
    ok: bool
    min_gap: float = math.inf  # kleinster Abstand zu Nachbarn (nur relevant bei ok)
    reason: str = ""
    collisions: list[Collision] = field(default_factory=list)


_KIND_DE = {"housing": "Motor", "gear": "Zahnrad", "rod": "Gewindestange", "obstacle": "Hindernis"}


class Counter:
    """Gemeinsamer Zaehler fuer untersuchte Kandidaten (ueber mehrere Layouts hinweg)."""

    def __init__(self) -> None:
        self.checks = 0


class Layout:
    def __init__(self, model: Model, counter: Optional[Counter] = None):
        self.model = model
        self.counter = counter or Counter()
        self.units: dict[int, Placement] = {}
        self._parts: dict[int, list[Part]] = {}
        self._grid: dict[tuple[int, int], set[int]] = {}
        self._next_id = 0
        self._plane_count: dict[int, int] = {}
        # Rasterweite. Zwei Einheiten koennen nur kollidieren, wenn ihre Stangenachsen
        # hoechstens 2*R + Abstand auseinander liegen.
        self._reach = 2.0 * model.unit_radius + model.gap + 1e-6
        self._cell = self._reach

    # -- Verwaltung ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self.units)

    def placements(self) -> list[Placement]:
        return [self.units[i] for i in sorted(self.units)]

    def _cellof(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / self._cell), math.floor(y / self._cell))

    def add(self, pl: Placement) -> int:
        uid = self._next_id
        self._next_id += 1
        self.units[uid] = pl
        self._plane_count[pl.plane] = self._plane_count.get(pl.plane, 0) + 1
        self._parts[uid] = self.model.unit_parts(uid, pl.x, pl.y, pl.plane, pl.angle, pl.cd)
        self._grid.setdefault(self._cellof(pl.x, pl.y), set()).add(uid)
        return uid

    def remove(self, uid: int) -> Placement:
        pl = self.units.pop(uid)
        self._plane_count[pl.plane] -= 1
        self._parts.pop(uid)
        c = self._cellof(pl.x, pl.y)
        self._grid[c].discard(uid)
        if not self._grid[c]:
            del self._grid[c]
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
        cx, cy = self._cellof(x, y)
        out = []
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                s = self._grid.get((i, j))
                if s:
                    out.extend(s)
        return out

    # -- Pruefung -------------------------------------------------------------
    def check(self, pl: Placement, ignore: Optional[int] = None, collect: bool = False) -> CheckResult:
        """Prueft eine Platzierung gegen Bauraum, Hindernisse, Ebenen und vorhandene Einheiten."""
        self.counter.checks += 1
        model = self.model
        gap = model.gap
        problems = model.plane_problems(pl.plane)
        if problems:
            return CheckResult(False, reason=problems[0])
        msg = model.cd_problem(pl.cd)
        if msg:
            return CheckResult(False, reason=msg)
        if not _angle_allowed(model, pl):
            return CheckResult(False, reason=f"Motorwinkel {pl.angle:g} Grad ist auf Ebene G{pl.plane} nicht erlaubt")
        cap = model.capacity.get(pl.plane)
        if cap is not None:
            n = self._plane_count.get(pl.plane, 0)
            if ignore is not None and ignore in self.units and self.units[ignore].plane == pl.plane:
                n -= 1
            if n >= cap:
                return CheckResult(False, reason=f"Ebene G{pl.plane} traegt bereits die maximale Anzahl Motoren ({cap})")
        parts = model.unit_parts(-1, pl.x, pl.y, pl.plane, pl.angle, pl.cd)
        msg = model.within_bounds(parts, pl.plane)
        if msg:
            return CheckResult(False, reason=msg)
        collisions: list[Collision] = []
        min_gap = math.inf
        need = gap - _FLOAT_NOISE
        for obs in model.obstacles:
            for p in parts:
                d = prism_distance(p.prism, obs.prism, gap)
                if d < need:
                    c = Collision(-1, -1, p.kind, "obstacle", d, gap, p.prism.fp.cx, p.prism.fp.cy)
                    c.message = f"{_KIND_DE[p.kind]} kollidiert mit {obs.label} (Abstand {d:.2f} mm, benoetigt {gap:.2f} mm)"
                    if not collect:
                        return CheckResult(False, reason=c.message)
                    collisions.append(c)
                else:
                    min_gap = min(min_gap, d)
        for uid in self._neighbors(pl.x, pl.y):
            if uid == ignore:
                continue
            other = self.units[uid]
            if math.hypot(other.x - pl.x, other.y - pl.y) > self._reach:
                continue
            for p in parts:
                for q in self._parts[uid]:
                    d = prism_distance(p.prism, q.prism, gap)
                    if d < need:
                        c = Collision(
                            -1, uid, p.kind, q.kind, d, gap, 0.5 * (p.prism.fp.cx + q.prism.fp.cx),
                            0.5 * (p.prism.fp.cy + q.prism.fp.cy),
                        )
                        c.message = (
                            f"{_KIND_DE[p.kind]} kollidiert mit {_KIND_DE[q.kind]} von Einheit {uid} "
                            f"(Abstand {d:.2f} mm, benoetigt {gap:.2f} mm)"
                        )
                        if not collect:
                            return CheckResult(False, reason=c.message)
                        collisions.append(c)
                    else:
                        min_gap = min(min_gap, d)
        if collisions:
            return CheckResult(False, reason=collisions[0].message, collisions=collisions)
        return CheckResult(True, min_gap=min_gap)

    def try_add(self, pl: Placement) -> Optional[int]:
        if self.check(pl).ok:
            return self.add(pl)
        return None

    def all_collisions(self) -> list[Collision]:
        """Vollstaendige Pruefung des gesamten Layouts (fuer Visualisierung und Validierung)."""
        model = self.model
        gap = model.gap
        need = gap - _FLOAT_NOISE
        out: list[Collision] = []
        ids = sorted(self.units)
        for uid in ids:
            pl = self.units[uid]
            problems = model.plane_problems(pl.plane)
            if problems:
                out.append(Collision(uid, -1, "housing", "plane", 0.0, gap, pl.x, pl.y, f"Einheit {uid}. {problems[0]}"))
            if not _angle_allowed(model, pl):
                out.append(Collision(uid, -1, "housing", "angle", 0.0, gap, pl.x, pl.y,
                                     f"Einheit {uid}. Motorwinkel {pl.angle:g} Grad ist auf Ebene G{pl.plane} nicht erlaubt"))
            msg = model.cd_problem(pl.cd)
            if msg:
                out.append(Collision(uid, -1, "housing", "rod", 0.0, gap, pl.x, pl.y, f"Einheit {uid}. {msg}"))
            msg = model.within_bounds(self._parts[uid], pl.plane)
            if msg:
                out.append(Collision(uid, -1, "housing", "bounds", 0.0, gap, pl.x, pl.y, f"Einheit {uid}. {msg}"))
            for obs in model.obstacles:
                for p in self._parts[uid]:
                    d = prism_distance(p.prism, obs.prism, gap)
                    if d < need:
                        out.append(Collision(
                            uid, -1, p.kind, "obstacle", d, gap, p.prism.fp.cx, p.prism.fp.cy,
                            f"Einheit {uid}. {_KIND_DE[p.kind]} kollidiert mit {obs.label}",
                        ))
        for plane, n in sorted(self._plane_count.items()):
            cap = model.capacity.get(plane)
            if cap is not None and n > cap:
                ex = next(u for u in ids if self.units[u].plane == plane)
                out.append(Collision(ex, -1, "housing", "capacity", 0.0, gap, self.units[ex].x, self.units[ex].y,
                                     f"Ebene G{plane} traegt {n} Motoren, erlaubt sind {cap}"))
        for i, a in enumerate(ids):
            pa = self.units[a]
            for b in ids[i + 1:]:
                pb = self.units[b]
                if math.hypot(pa.x - pb.x, pa.y - pb.y) > self._reach:
                    continue
                for p in self._parts[a]:
                    for q in self._parts[b]:
                        d = prism_distance(p.prism, q.prism, gap)
                        if d < need:
                            out.append(Collision(
                                a, b, p.kind, q.kind, d, gap, 0.5 * (p.prism.fp.cx + q.prism.fp.cx),
                                0.5 * (p.prism.fp.cy + q.prism.fp.cy),
                                f"Einheit {a} ({_KIND_DE[p.kind]}) und Einheit {b} ({_KIND_DE[q.kind]}) "
                                f"Abstand {d:.2f} mm, benoetigt {gap:.2f} mm",
                            ))
        return out

    def closest_pairs(self, limit: int = 12) -> list[dict]:
        """Die engsten Bauteilpaare verschiedener Einheiten (Abstand im Raum), aufsteigend nach Abstand."""
        found: dict[tuple, dict] = {}
        ids = sorted(self.units)
        for a in ids:
            pa = self.units[a]
            for b in self._neighbors(pa.x, pa.y):
                if b <= a:
                    continue
                pb = self.units[b]
                if math.hypot(pa.x - pb.x, pa.y - pb.y) > self._reach:
                    continue
                best = None
                for p in self._parts[a]:
                    for q in self._parts[b]:
                        d = prism_distance(p.prism, q.prism)
                        if best is None or d < best["gap"]:
                            best = {
                                "a": a, "b": b, "kind_a": p.kind, "kind_b": q.kind, "gap": d,
                                "x": 0.5 * (p.prism.fp.cx + q.prism.fp.cx), "y": 0.5 * (p.prism.fp.cy + q.prism.fp.cy),
                            }
                if best:
                    found[(a, b)] = best
        return sorted(found.values(), key=lambda r: r["gap"])[:limit]

    def is_valid(self) -> bool:
        return not self.all_collisions()


def _angle_allowed(model: Model, pl: Placement) -> bool:
    a = round(pl.angle % 360.0, 6)
    return any(abs(a - b) < 1e-4 or abs(abs(a - b) - 360.0) < 1e-4 for b in model.angles_for(pl.plane))


def layout_from_placements(model: Model, placements: list[Placement], counter: Optional[Counter] = None) -> Layout:
    lay = Layout(model, counter)
    for pl in placements:
        lay.add(pl)
    return lay
