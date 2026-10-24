"""Layout (set of placed units) and collision check.

A layout holds placements (rod position, motor layer, motor angle, centre distance) and checks new
placements incrementally against the existing ones. A spatial grid speeds up the neighbour search.

Rule. Two parts are only free of collisions if their true minimum distance in space is >= safety
clearance + tolerance. The mesh of a gear with its own rod belongs to the design and is not checked.

Extending. A new condition for a single unit is a function ``(model, placement, parts) -> message``
in ``UNIT_RULES``. It is then applied both in the fast ``Layout.check`` and in the full check
``all_collisions``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from .geometry import prism_distance
from .i18n import tr
from .model import KIND_HOUSING, KIND_OBSTACLE, KIND_ROD, Model, Part, part_label
from .units import ANGLE_TOL_DEG, EPS, is_finite_number, normalize_angle_deg

SIGNATURE_DIGITS = 2  # rounding (mm, degrees) when comparing two layouts for equality
REACH_SLACK = 1e-6  # allowance on the reach so that rounding loses no neighbours


def kind_label(kind: str):
    """Label of a part kind in collision messages (the rod is called threaded rod there)."""
    return part_label("threaded_rod" if kind == KIND_ROD else kind)

PLACEMENT_FIELDS = ("x", "y", "plane", "angle", "cd")


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    plane: int  # index of the motor layer (1..n)
    angle: float  # degrees
    cd: Optional[float] = None  # centre distance gear to rod, None = nominal

    @staticmethod
    def from_dict(data: object, n_planes: int) -> "Placement":
        """Strict check of a placement from outside (UI, JSON files)."""
        if not isinstance(data, dict):
            raise ValueError(tr("placement.not_object"))
        extra = set(data) - set(PLACEMENT_FIELDS)
        if extra:
            raise ValueError(tr("placement.unknown_fields", fields=sorted(extra)))

        def number(key: str) -> float:
            value = data.get(key)
            if not is_finite_number(value):
                raise ValueError(tr("placement.number", key=key))
            return float(value)

        plane = data.get("plane")
        if isinstance(plane, bool) or not isinstance(plane, int) or not 1 <= plane <= n_planes:
            raise ValueError(tr("placement.plane", n=n_planes))
        cd = None
        if data.get("cd") is not None:
            cd = number("cd")
            if cd < 0:
                raise ValueError(tr("placement.cd_negative"))
        return Placement(number("x"), number("y"), plane, number("angle"), cd)

    def as_dict(self) -> dict:
        out = {"x": self.x, "y": self.y, "plane": self.plane, "angle": self.angle}
        if self.cd is not None:
            out["cd"] = self.cd
        return out


def layout_signature(placements: Iterable[Placement]) -> tuple:
    """Order independent key of a layout. Equal layouts (up to rounding) have the same key. The centre
    distance is part of it, None counts as 0."""
    digits = SIGNATURE_DIGITS
    return tuple(sorted(
        (round(p.x, digits), round(p.y, digits), p.plane, round(p.angle, digits), round(p.cd or 0.0, digits))
        for p in placements
    ))


@dataclass
class Collision:
    a: int  # unit id, -1 for a fixed obstacle or the build area
    b: int
    kind_a: str
    kind_b: str
    gap: float  # actual distance
    required: float
    x: float
    y: float
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    ok: bool
    # If ok, the smallest measured distance to neighbours and obstacles. Distances beyond the safety
    # clearance are only computed as precisely as needed (prism_distance with cutoff), so the value is
    # a lower bound of the true distance, but never smaller than gap.
    min_gap: float = math.inf
    reason: str = ""
    collisions: list[Collision] = field(default_factory=list)


class Counter:
    """Shared counter of examined candidates (across several layouts)."""

    def __init__(self) -> None:
        self.checks = 0


# ---------------------------------------------------------------------------
# Rules for a single unit. Each returns "" (satisfied) or a message.
# The capacity per layer depends on the whole layout and is checked in the layout.
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
    return tr("layout.angle_not_allowed", angle=pl.angle, plane=pl.plane)


def _rule_bounds(model: Model, pl: Placement, parts: list[Part]) -> str:
    return model.within_bounds(parts, pl.plane) or ""


# (kind for Collision.kind_b, rule, needs parts). Rules without parts run first, so no prisms have to
# be built for clearly invalid placements.
UNIT_RULES: list[tuple[str, UnitRule, bool]] = [
    ("plane", _rule_plane, False),
    ("rod", _rule_center_distance, False),
    ("angle", _rule_angle, False),
    ("bounds", _rule_bounds, True),
]


def angle_allowed(model: Model, pl: Placement) -> bool:
    """True if the angle (modulo 360) is in the angle list of the layer."""
    angle = normalize_angle_deg(pl.angle)
    for allowed in model.angles_for(pl.plane):
        diff = abs(angle - allowed)
        if diff < ANGLE_TOL_DEG or abs(diff - 360.0) < ANGLE_TOL_DEG:
            return True
    return False


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
        # Two units can only collide if their rod axes are at most 2 * unit radius + clearance apart.
        # This is also the grid cell size.
        self._reach = 2.0 * model.unit_radius + model.gap + REACH_SLACK
        self._cell = self._reach

    @property
    def reach(self) -> float:
        """Largest rod to rod distance at which two units can still collide (mm)."""
        return self._reach

    # -- Bookkeeping ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self.units)

    def placements(self) -> list[Placement]:
        return [self.units[i] for i in sorted(self.units)]

    def _cell_of(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / self._cell), math.floor(y / self._cell))

    def add(self, pl: Placement) -> int:
        """Add without a check and return the new unit id."""
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
        """Unit ids in the own and the eight surrounding grid cells."""
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

    # -- Check -------------------------------------------------------------
    def _capacity_problem(self, pl: Placement, ignore: Optional[int]) -> str:
        cap = self.model.capacity.get(pl.plane)
        if cap is None:
            return ""
        count = self._plane_count.get(pl.plane, 0)
        if ignore is not None and ignore in self.units and self.units[ignore].plane == pl.plane:
            count -= 1
        if count >= cap:
            return tr("layout.capacity_full", plane=pl.plane, cap=cap)
        return ""

    def check(self, pl: Placement, ignore: Optional[int] = None, collect: bool = False) -> CheckResult:
        """Check a placement against unit rules, capacity, obstacles and existing units.

        ignore is a unit id that is not considered (for moving a unit). With collect all collisions are
        gathered, otherwise the check stops at the first one.
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
                message = tr("layout.hits_obstacle", part=kind_label(p.kind), obstacle=obstacle.label, distance=dist, gap=gap)
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
                    message = tr("layout.hits_unit", part=kind_label(p.kind), other=kind_label(q.kind), unit=uid,
                                 distance=dist, gap=gap)
                    if not collect:
                        return CheckResult(False, reason=message)
                    collisions.append(Collision(-1, uid, p.kind, q.kind, dist, gap, *_midpoint(p, q), message))
        if collisions:
            return CheckResult(False, reason=collisions[0].message, collisions=collisions)
        return CheckResult(True, min_gap=min_gap)

    def try_add(self, pl: Placement) -> Optional[int]:
        """Add if the placement is valid. Returns the unit id or None."""
        if self.check(pl).ok:
            return self.add(pl)
        return None

    def all_collisions(self) -> list[Collision]:
        """Full check of the whole layout (for display and validation)."""
        out: list[Collision] = []
        ids = sorted(self.units)
        for uid in ids:
            out.extend(self._unit_collisions(uid))
        out.extend(self._capacity_collisions(ids))
        out.extend(self._pair_collisions(ids))
        return out

    def _unit_collisions(self, uid: int) -> list[Collision]:
        """Violated unit rules and collisions with obstacles of one unit."""
        model = self.model
        gap = model.gap
        pl = self.units[uid]
        parts = self._parts[uid]
        out = []
        for kind, rule, _ in UNIT_RULES:
            message = rule(model, pl, parts)
            if message:
                out.append(Collision(uid, -1, KIND_HOUSING, kind, 0.0, gap, pl.x, pl.y, tr("layout.unit_message", unit=uid, message=message)))
        for obstacle in model.obstacles:
            for p in parts:
                dist = prism_distance(p.prism, obstacle.prism, gap)
                if dist < gap - EPS:
                    out.append(Collision(
                        uid, -1, p.kind, KIND_OBSTACLE, dist, gap, p.prism.fp.cx, p.prism.fp.cy,
                        tr("layout.unit_hits_obstacle", unit=uid, part=kind_label(p.kind), obstacle=obstacle.label),
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
                                 tr("layout.capacity_exceeded", plane=plane, count=count, cap=cap)))
        return out

    def _pair_collisions(self, ids: list[int]) -> list[Collision]:
        """Collisions between all pairs of units (without the grid, also for unsorted input)."""
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
                                tr("layout.pair", a=a, part_a=kind_label(p.kind), b=b, part_b=kind_label(q.kind),
                                   distance=dist, gap=gap),
                            ))
        return out

    def closest_pairs(self, limit: int = 12) -> list[dict]:
        """The closest part pairs of different units (distance in space), ascending by distance."""
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
    """Build a layout from placements without a check (query collisions with all_collisions)."""
    layout = Layout(model, counter)
    for pl in placements:
        layout.add(pl)
    return layout
