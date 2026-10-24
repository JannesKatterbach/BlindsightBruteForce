"""Input data (configuration) as dataclasses with schema driven validation.

All lengths in mm, angles in degrees, time in seconds. The configuration is a pure data model and knows
neither optimizers nor UI. It can be loaded from and saved to JSON.

Layout of this file
  1. Dataclasses (RodSpec, MotorSpec, StackSpec, ...). The defaults are placeholders
  2. Project with loading, saving and validation
  3. FIELD_META. Description of every simple field (kind, limits, choices, group). Field checks, the UI
     forms (/api/schema) and the parameter table of the README (docs.py) are built from it. Labels and
     tips live in the translation catalogs (keys ``field.<path>.label`` and ``field.<path>.tip``)
  4. Type driven reading from JSON (_build, _coerce)

Extending. A new simple field needs a dataclass attribute, an entry in FIELD_META and its label and tip
in the catalogs. Checks that involve several fields belong into the matching ``_check_*`` function.

Important. The defaults are placeholders for a first try and not manufacturer data. All mechanically
relevant dimensions must be overwritten with the real parts.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import ConfigError
from .geometry import is_convex_ccw, signed_area
from .i18n import LocalText, tr
from .patterns import PATTERNS
from .sketch import check_sketch_motor
from .units import EPS, EPS_AREA, FAR_AWAY, is_finite_number, normalize_angle_deg

MAX_ANGLE_COUNT = 100_000  # protection against tiny angle steps

STACK_MODES = ("uniform", "gaps", "distances")
MOUNT_MODES = ("top", "bottom")
OBSTACLE_SHAPES = ("rect", "circle")
# Hole patterns of the optimizer periodic_tile (see optimizers/periodic_tile.py)
PATTERN_KINDS = ("square", "centered_square", "hex", "hex_rotated", "staggered", "rectangle", "free", "custom")


# ---------------------------------------------------------------------------
# 1. Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class RodSpec:
    """Threaded rod (vertical)."""

    diameter: float = 4.0
    stroke: float = 50.0
    engage_below: float = 10.0
    engage_above: float = 10.0
    length_tolerance: float = 2.0
    retract_depth: float = 0.0
    hole_clearance: float = 0.5


@dataclass
class ConstraintSpec:
    """One constraint of the motor sketch (types and meaning see sketch/constraints.py)."""

    type: str = "length"
    a: Optional[int] = None
    b: Optional[int] = None
    value: Optional[float] = None
    value2: Optional[float] = None
    ref: str = "rod"
    enabled: bool = True
    name: str = ""


@dataclass
class SketchSpec:
    """Parametric housing outline in the rod frame (origin = rod axis, mm)."""

    points: list[list[float]] = field(default_factory=list)
    constraints: list[ConstraintSpec] = field(default_factory=list)


@dataclass
class MotorSpec:
    """Motor with a side mounted drive gear, simplified as a prism plus a gear box.

    There are two ways to describe the housing.

    Without sketch (housing frame, motor angle 0 degrees, top view)
      * Housing centred at (0, 0). A rectangle width x depth or, with ``outline``, a convex
        polygon (width and depth are then only shown).
      * The output shaft runs parallel to y at x = shaft_x and leaves at the +y side. The gear
        sits gear_gap behind the topmost housing edge.
      * The threaded rod stands vertically at center_distance from the output shaft (in +x),
        at the height of the gear centre.

    With sketch (``sketch``, rod frame)
      * The origin is the rod axis, the gear lies at (-center_distance, 0).
      * width, depth, shaft_x, gear_gap and outline are ignored.
    """

    width: float = 12.0
    depth: float = 24.0
    height: float = 10.0
    shaft_x: float = 0.0
    axis_height: float = 5.0
    gear_diameter: float = 6.0
    gear_width: float = 4.0
    gear_gap: float = 1.0
    center_distance: float = 5.0
    center_distance_min: Optional[float] = None
    center_distance_max: Optional[float] = None
    center_distance_steps: int = 1
    own_clearance: float = 0.2
    mount: str = "top"
    outline: Optional[list[list[float]]] = None
    sketch: Optional[SketchSpec] = None

    @property
    def gear_radius(self) -> float:
        return self.gear_diameter / 2.0

    @property
    def gear_center_y(self) -> float:
        """y of the gear centre in the housing frame (behind the topmost edge of the outline)."""
        top = max(p[1] for p in self.outline) if self.outline else self.depth / 2.0
        return top + self.gear_gap + self.gear_width / 2.0

    def center_distances(self) -> list[float]:
        """Permitted centre distances, ascending. Without a range only the nominal value.

        The nominal value is always included (validation ensures it lies within the range)."""
        lo, hi = self.center_distance_min, self.center_distance_max
        steps = max(1, self.center_distance_steps)
        if lo is None or hi is None or steps == 1 or hi <= lo:
            return [self.center_distance]
        values = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
        if not any(abs(v - self.center_distance) < EPS for v in values):
            values.append(self.center_distance)
        return sorted(values)

    def rod_local(self, cd: Optional[float] = None) -> tuple[float, float]:
        """Position of the threaded rod in the housing frame (only meaningful without sketch)."""
        return (self.shaft_x + (self.center_distance if cd is None else cd), self.gear_center_y)


@dataclass
class StackSpec:
    """Layer stack. z = 0 is the top face of G0, negative below.

    mode "uniform"   equal distance uniform_spacing between all layers (including G0)
    mode "gaps"      gaps[i] is the distance between the top faces of G(i) and G(i+1)
    mode "distances" distances[i] is the distance of the top face of G(i+1) to G0
    """

    n_motor_planes: int = 3
    mode: str = "uniform"
    uniform_spacing: float = 20.0
    gaps: list[float] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)
    thickness: float = 1.6
    g0_thickness: float = 6.0
    thicknesses: Optional[list[float]] = None  # thickness per motor layer (overrides thickness)
    allowed_planes: Optional[list[int]] = None
    mount_zones: dict[str, list[list[float]]] = field(default_factory=dict)
    max_per_plane: dict[str, int] = field(default_factory=dict)
    plane_angles: dict[str, list[float]] = field(default_factory=dict)

    def plane_tops(self) -> list[float]:
        """z of the top faces of G0 to Gn (G0 at 0, negative below)."""
        n = self.n_motor_planes
        tops = [0.0]
        if self.mode == "uniform":
            tops += [-(i * self.uniform_spacing) for i in range(1, n + 1)]
        elif self.mode == "gaps":
            z = 0.0
            for gap in self.gaps[:n]:
                z -= gap
                tops.append(z)
        elif self.mode == "distances":
            tops += [-d for d in self.distances[:n]]
        else:
            raise ConfigError(tr("config.unknown_stack_mode", mode=self.mode))
        return tops

    def plane_thickness(self, index: int) -> float:
        """Thickness of layer G<index> (0 = G0)."""
        if index == 0:
            return self.g0_thickness
        if self.thicknesses is not None:
            return self.thicknesses[index - 1]
        return self.thickness


@dataclass
class BoundsSpec:
    """Build area in top view. A rectangle from the origin (0, 0) at the bottom left to (width, height), in mm."""

    width: float = 120.0
    height: float = 120.0
    edge_margin: float = 0.0
    parts_in_bounds: str = "all"

    # Corner coordinates for the geometry code. The origin is fixed at the bottom left corner.
    xmin = 0.0
    ymin = 0.0

    @property
    def xmax(self) -> float:
        return self.width

    @property
    def ymax(self) -> float:
        return self.height


@dataclass
class ObstacleSpec:
    """Fixed obstacle (prism). Without z0 and z1 it reaches through all layers.

    If plane is set, it only applies to this motor layer (keep out zone, for example a hole or a part on
    the board), its z range then follows from the layer and the motor height. ``angle`` is in degrees.
    """

    shape: str = "rect"
    x: float = 0.0
    y: float = 0.0
    w: float = 10.0
    h: float = 10.0
    r: float = 5.0
    angle: float = 0.0
    z0: float = -FAR_AWAY
    z1: float = FAR_AWAY
    plane: Optional[int] = None
    name: str = ""


@dataclass
class WeightsSpec:
    """Priorities of the optimization goals (relative weights, normalized).

    Every field corresponds to an entry in ``scoring.OBJECTIVES``."""

    count: float = 10.0
    area: float = 8.0
    uniformity: float = 2.0
    regularity: float = 1.0

    def as_dict(self) -> dict[str, float]:
        return dataclasses.asdict(self)


@dataclass
class CustomTileSpec:
    """Own repeating tile from the hole pattern generator. Holes in mm relative to the bottom left corner of the
    tile (0 <= x < width, 0 <= y < height). scalable allows the program to scale the whole tile evenly."""

    width: float = 20.0
    height: float = 20.0
    holes: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0]])
    scalable: bool = False


@dataclass
class SearchSpec:
    """Control of the search."""

    weights: WeightsSpec = field(default_factory=WeightsSpec)
    optimizer: str = "pattern_greedy"
    patterns: list[str] = field(default_factory=lambda: ["square", "hex_x", "hex_y"])
    layout_goal: str = "compact"
    fixed_pitch: Optional[float] = None
    angle_step: float = 15.0
    angle_min: float = 0.0
    angle_max: float = 360.0
    allowed_angles: Optional[list[float]] = None
    time_limit_s: float = 20.0
    max_candidates: int = 2_000_000
    seed: int = 1
    top_k: int = 5
    refine_fraction: float = 0.35
    stagnation_s: Optional[float] = 6.0
    workers: int = 1
    # Repeating pattern (optimizer periodic_tile). pattern chooses the hole lattice, pattern_pitch the distance to
    # the nearest hole (None = search it). The motor arrangement repeats in blocks of at most max_block_holes holes.
    pattern: str = "square"
    pattern_pitch: Optional[float] = None  # mm
    pattern_pitch_y: Optional[float] = None  # mm, second distance of rectangle and staggered rows
    max_block_holes: int = 12
    custom_tile: Optional[CustomTileSpec] = None  # pattern "custom"
    # Pattern "free". A tile holds tile_rods rods and repeats over the build area.
    tile_rods: int = 2
    tile_width: Optional[float] = None  # mm, None = search the smallest width
    tile_height: Optional[float] = None  # mm, None = search the smallest height
    tile_step: float = 0.5  # mm, raster of tile sizes and rod spacings


# ---------------------------------------------------------------------------
# 2. Project
# ---------------------------------------------------------------------------
@dataclass
class Project:
    name: str = "Blindsight"
    target_count: int = 12
    clearance: float = 1.0
    tolerance: float = 0.05
    rod: RodSpec = field(default_factory=RodSpec)
    motor: MotorSpec = field(default_factory=MotorSpec)
    stack: StackSpec = field(default_factory=StackSpec)
    bounds: BoundsSpec = field(default_factory=BoundsSpec)
    obstacles: list[ObstacleSpec] = field(default_factory=list)
    search: SearchSpec = field(default_factory=SearchSpec)

    @property
    def required_gap(self) -> float:
        """Effective minimum distance of all parts."""
        return self.clearance + self.tolerance

    # -- (De)serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        """Read and validate a project. Raises ConfigError with all problems found."""
        errs: list[str] = []
        proj = _build(cls, data, "", errs)
        if errs:
            raise ConfigError(errs)
        proj.validate()
        return proj

    @classmethod
    def from_json(cls, text: str) -> "Project":
        try:
            return cls.from_dict(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ConfigError(tr("config.invalid_json", error=str(exc))) from exc
        except RecursionError:
            raise ConfigError(tr("config.json_too_deep")) from None

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())

    # -- Validation ------------------------------------------------------------
    def validate(self) -> None:
        """Check every field on its own (FIELD_META) first, then the relations between fields.

        The relation checks assume valid single values and therefore only run when the field
        checks found no problem."""
        errs: list[str] = []
        _validate_fields(self, errs)
        if errs:
            raise ConfigError(errs)
        for check in (_check_motor, _check_stack, _check_bounds, _check_obstacles, _check_search):
            check(self, errs)
        if errs:
            raise ConfigError(errs)

    # -- Angles ----------------------------------------------------------------
    def allowed_angle_list(self) -> list[float]:
        """Permitted motor angles in degrees, in [0, 360), ascending and without duplicates."""
        search = self.search
        if search.allowed_angles is not None:
            angles = {normalize_angle_deg(a) for a in search.allowed_angles}
        else:
            if search.angle_step <= 0:
                raise ConfigError(tr("config.angle_step_positive"))
            if (search.angle_max - search.angle_min) / search.angle_step > MAX_ANGLE_COUNT:
                raise ConfigError(tr("config.angle_step_small", count=MAX_ANGLE_COUNT))
            angles = set()
            a = search.angle_min
            while a < search.angle_max - EPS:
                angles.add(normalize_angle_deg(a))
                a += search.angle_step
        if not angles:
            raise ConfigError(tr("config.no_angles"))
        return sorted(angles)

    def angles_for_plane(self, plane: int) -> list[float]:
        """Permitted angles of a layer (the global list, replaced by plane_angles)."""
        own = self.stack.plane_angles.get(str(plane))
        if own:
            return sorted({normalize_angle_deg(a) for a in own})
        return self.allowed_angle_list()


def _check_motor(proj: Project, errs: list[str]) -> None:
    motor = proj.motor
    if motor.axis_height > motor.height:
        errs.append(tr("config.axis_outside"))
    lo, hi = motor.center_distance_min, motor.center_distance_max
    if (lo is None) != (hi is None):
        errs.append(tr("config.cd_together"))
    elif lo is not None and hi is not None:
        if hi < lo:
            errs.append(tr("config.cd_max_below_min"))
        elif not lo - EPS <= motor.center_distance <= hi + EPS:
            errs.append(tr("config.cd_outside", cd=motor.center_distance, lo=lo, hi=hi))
    if motor.sketch is not None:
        _, sketch_errors = check_sketch_motor(motor)
        errs.extend(sketch_errors)
    elif motor.outline is not None:
        _check_outline(motor.outline, errs)


def _check_stack(proj: Project, errs: list[str]) -> None:
    stack = proj.stack
    n = stack.n_motor_planes
    before = len(errs)
    if stack.mode == "gaps":
        if len(stack.gaps) < n:
            errs.append(tr("config.gaps_count", n=n))
        elif any(g <= 0 for g in stack.gaps[:n]):
            errs.append(tr("config.gaps_positive"))
    elif stack.mode == "distances":
        dist = stack.distances[:n]
        if len(dist) < n:
            errs.append(tr("config.distances_count", n=n))
        elif any(x <= 0 for x in dist) or any(dist[i] >= dist[i + 1] for i in range(len(dist) - 1)):
            errs.append(tr("config.distances_order"))
    if stack.thicknesses is not None:
        if len(stack.thicknesses) < n:
            errs.append(tr("config.thicknesses_count", n=n))
        elif any(t <= 0 for t in stack.thicknesses):
            errs.append(tr("config.thicknesses_positive"))
    if len(errs) == before:
        errs.extend(plane_overlap_errors(stack))
    if stack.allowed_planes is not None:
        bad = [p for p in stack.allowed_planes if not 1 <= p <= n]
        if bad:
            errs.append(tr("config.allowed_unknown", planes=bad, n=n))
        if not stack.allowed_planes:
            errs.append(tr("config.allowed_empty"))
    for key, zones in stack.mount_zones.items():
        _check_plane_key("stack.mount_zones", key, n, errs)
        for zone in zones:
            if len(zone) != 4 or zone[2] <= zone[0] or zone[3] <= zone[1]:
                errs.append(tr("config.zone_shape", key=key))
    for key, cap in stack.max_per_plane.items():
        _check_plane_key("stack.max_per_plane", key, n, errs)
        if cap < 0:
            errs.append(tr("config.capacity_negative", key=key))
    for key, angles in stack.plane_angles.items():
        _check_plane_key("stack.plane_angles", key, n, errs)
        if not angles:
            errs.append(tr("config.plane_angles_empty", key=key))


def plane_overlap_errors(stack: StackSpec) -> list[LocalText]:
    """Messages for a layer reaching into the next one (distance smaller than the board thickness)."""
    tops = stack.plane_tops()
    out = []
    for i in range(len(tops) - 1):
        bottom = tops[i] - stack.plane_thickness(i)
        if tops[i + 1] >= bottom:
            out.append(tr("config.planes_overlap", a=i, b=i + 1, distance=tops[i] - tops[i + 1], thickness=stack.plane_thickness(i)))
    return out


def _check_bounds(proj: Project, errs: list[str]) -> None:
    bounds = proj.bounds
    if bounds.width <= 0 or bounds.height <= 0:
        errs.append(tr("config.bounds_area"))
    elif 2 * bounds.edge_margin >= min(bounds.width, bounds.height):
        errs.append(tr("config.edge_margin"))


def _check_obstacles(proj: Project, errs: list[str]) -> None:
    n = proj.stack.n_motor_planes
    for i, obstacle in enumerate(proj.obstacles):
        tag = f"obstacles[{i}]"
        if obstacle.shape not in OBSTACLE_SHAPES:
            errs.append(tr("config.obstacle_shape", tag=tag))
        if obstacle.z1 < obstacle.z0:
            errs.append(tr("config.obstacle_z", tag=tag))
        if obstacle.shape == "rect" and (obstacle.w <= 0 or obstacle.h <= 0):
            errs.append(tr("config.obstacle_size", tag=tag))
        if obstacle.shape == "circle" and obstacle.r <= 0:
            errs.append(tr("config.obstacle_radius", tag=tag))
        if obstacle.plane is not None and not 1 <= obstacle.plane <= n:
            errs.append(tr("config.obstacle_plane", tag=tag, plane=obstacle.plane, n=n))


def _check_search(proj: Project, errs: list[str]) -> None:
    search = proj.search
    for pattern in search.patterns:
        if pattern not in PATTERNS:
            errs.append(tr("config.unknown_pattern", pattern=pattern, known=", ".join(PATTERNS)))
    if not search.patterns:
        errs.append(tr("config.no_pattern"))
    if len(search.patterns) != len(set(search.patterns)):
        errs.append(tr("config.duplicate_pattern"))
    if search.angle_max <= search.angle_min:
        errs.append(tr("config.angle_range"))
    if sum(search.weights.as_dict().values()) <= 0:
        errs.append(tr("config.weights_zero"))
    _check_custom_tile(search, errs)
    try:
        proj.allowed_angle_list()
    except ConfigError as exc:
        errs.extend(exc.errors)


def _check_custom_tile(search: SearchSpec, errs: list[str]) -> None:
    tile = search.custom_tile
    if tile is None:
        if search.pattern == "custom":
            errs.append(tr("config.custom_tile_missing"))
        return
    if not (is_finite_number(tile.width) and is_finite_number(tile.height) and tile.width > 0 and tile.height > 0):
        errs.append(tr("config.custom_tile_size"))
        return
    inside = all(len(h) == 2 and all(is_finite_number(c) for c in h) and 0 <= h[0] < tile.width and 0 <= h[1] < tile.height
                 for h in tile.holes)
    if not tile.holes or not inside:
        errs.append(tr("config.custom_tile_holes"))


def _check_plane_key(label: str, key: str, n: int, errs: list[str]) -> None:
    if not (key.isdigit() and 1 <= int(key) <= n):
        errs.append(tr("config.plane_key", label=label, key=key, n=n))


def _check_outline(outline: list[list[float]], errs: list[str]) -> None:
    if len(outline) < 3 or any(len(p) != 2 for p in outline):
        errs.append(tr("config.outline_points"))
        return
    area = signed_area(outline)
    if abs(area) < EPS_AREA:
        errs.append(tr("config.outline_area"))
        return
    ccw = outline if area > 0 else list(reversed(outline))
    if not is_convex_ccw(ccw):
        errs.append(tr("config.outline_convex"))


# ---------------------------------------------------------------------------
# 3. Field description. Source of validation, UI forms and documentation.
#   kind  len (mm), lenlist (list of lengths in mm), num, int, text, enum,
#         list (list of numbers without unit), listint, liststr
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Meta:
    """Description of a configuration field for validation, UI and documentation."""

    path: str
    kind: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    strict_lo: bool = False  # True. The value must be > lo
    options: Optional[tuple[str, ...]] = None  # permitted values of an enum
    group: str = ""
    optional: bool = False  # None allowed

    @property
    def label(self) -> LocalText:
        return tr(f"field.{self.path}.label")

    @property
    def tip(self) -> LocalText:
        return tr(f"field.{self.path}.tip")

    def option_label(self, value: str) -> LocalText:
        return tr(f"option.{self.path}.{value}")


FIELD_META: list[Meta] = [
    Meta("name", "text", group="general"),
    Meta("target_count", "int", 1, 100000, group="general"),
    Meta("clearance", "len", 0, 1000, group="general"),
    Meta("tolerance", "len", 0, 1000, group="general"),
    Meta("rod.diameter", "len", 0, 1000, True, group="rod"),
    Meta("rod.stroke", "len", 0, 100000, True, group="rod"),
    Meta("rod.engage_below", "len", 0, 100000, group="rod"),
    Meta("rod.engage_above", "len", 0, 100000, group="rod"),
    Meta("rod.length_tolerance", "len", 0, 100000, group="rod"),
    Meta("rod.retract_depth", "len", 0, 100000, group="rod"),
    Meta("rod.hole_clearance", "len", 0, 1000, group="rod"),
    Meta("motor.width", "len", 0, 10000, True, group="motor"),
    Meta("motor.depth", "len", 0, 10000, True, group="motor"),
    Meta("motor.height", "len", 0, 10000, True, group="motor"),
    Meta("motor.shaft_x", "len", -10000, 10000, group="motor"),
    Meta("motor.axis_height", "len", 0, 10000, group="motor"),
    Meta("motor.gear_diameter", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_width", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_gap", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance_min", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_max", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_steps", "int", 1, 50, group="motor"),
    Meta("motor.own_clearance", "len", 0, 1000, group="motor"),
    Meta("motor.mount", "enum", options=MOUNT_MODES, group="motor"),
    Meta("stack.n_motor_planes", "int", 1, 1000, group="stack"),
    Meta("stack.mode", "enum", options=STACK_MODES, group="stack"),
    Meta("stack.uniform_spacing", "len", 0, 100000, True, group="stack"),
    Meta("stack.gaps", "lenlist", group="stack"),
    Meta("stack.distances", "lenlist", group="stack"),
    Meta("stack.thickness", "len", 0, 1000, True, group="stack"),
    Meta("stack.g0_thickness", "len", 0, 1000, True, group="stack"),
    Meta("stack.thicknesses", "lenlist", group="stack", optional=True),
    Meta("stack.allowed_planes", "listint", group="stack", optional=True),
    Meta("bounds.width", "len", 0, 1e6, True, group="bounds"),
    Meta("bounds.height", "len", 0, 1e6, True, group="bounds"),
    Meta("bounds.edge_margin", "len", 0, 1e6, group="bounds"),
    Meta("bounds.parts_in_bounds", "enum", options=("all", "rods"), group="bounds"),
    Meta("search.optimizer", "enum", options=("pattern_greedy", "anneal_free", "exhaustive_small", "periodic_tile"), group="search"),
    Meta("search.layout_goal", "enum", options=("compact", "spread"), group="search"),
    Meta("search.patterns", "liststr", group="search"),
    Meta("search.fixed_pitch", "len", 0, 100000, True, group="search", optional=True),
    Meta("search.angle_step", "num", 0, 360, True, group="search"),
    Meta("search.angle_min", "num", -3600, 3600, group="search"),
    Meta("search.angle_max", "num", -3600, 3600, group="search"),
    Meta("search.allowed_angles", "list", group="search", optional=True),
    Meta("search.time_limit_s", "num", 0, 86400, True, group="search"),
    Meta("search.max_candidates", "int", 1, 10**12, group="search"),
    Meta("search.seed", "int", 0, 2**31 - 1, group="search"),
    Meta("search.top_k", "int", 1, 50, group="search"),
    Meta("search.refine_fraction", "num", 0, 0.9, group="search"),
    Meta("search.stagnation_s", "num", 0, 86400, True, group="search", optional=True),
    Meta("search.pattern", "enum", options=PATTERN_KINDS, group="search"),
    Meta("search.pattern_pitch", "len", 0, 1e5, True, group="search", optional=True),
    Meta("search.pattern_pitch_y", "len", 0, 1e5, True, group="search", optional=True),
    Meta("search.max_block_holes", "int", 1, 36, group="search"),
    Meta("search.tile_rods", "int", 1, 8, group="search"),
    Meta("search.tile_width", "len", 0, 1e5, True, group="search", optional=True),
    Meta("search.tile_height", "len", 0, 1e5, True, group="search", optional=True),
    Meta("search.tile_step", "len", 0, 100, True, group="search"),
    Meta("search.workers", "int", 1, 64, group="search"),
    Meta("search.weights.count", "num", 0, 1000, group="weights"),
    Meta("search.weights.area", "num", 0, 1000, group="weights"),
    Meta("search.weights.uniformity", "num", 0, 1000, group="weights"),
    Meta("search.weights.regularity", "num", 0, 1000, group="weights"),
]
META_BY_PATH = {m.path: m for m in FIELD_META}
NUMERIC_KINDS = ("len", "num", "int")
NUMBER_LIST_KINDS = ("list", "lenlist", "listint")


def _get(obj: Any, path: str) -> Any:
    for key in path.split("."):
        obj = getattr(obj, key)
    return obj


def _validate_fields(proj: Project, errs: list[str]) -> None:
    """Check every FIELD_META field on its own, plus the numbers in lists without own meta."""
    for meta in FIELD_META:
        value = _get(proj, meta.path)
        if value is None:
            if not meta.optional:
                errs.append(tr("value.missing", path=meta.path))
            continue
        if meta.kind in NUMERIC_KINDS:
            _check_number(meta, value, errs)
        elif meta.kind == "enum":
            allowed = list(meta.options or ())
            if value not in allowed:
                errs.append(tr("value.enum", path=meta.path, value=value, allowed=allowed))
        elif meta.kind in NUMBER_LIST_KINDS:
            if not all(is_finite_number(x) for x in value):
                errs.append(tr("value.list_numbers", path=meta.path))
    for i, obstacle in enumerate(proj.obstacles):
        for name in ("x", "y", "w", "h", "r", "angle", "z0", "z1"):
            if not is_finite_number(getattr(obstacle, name)):
                errs.append(tr("value.finite", path=f"obstacles[{i}].{name}"))
    for key, zones in proj.stack.mount_zones.items():
        if not all(is_finite_number(c) for zone in zones for c in zone):
            errs.append(tr("value.coordinates", path=f"stack.mount_zones[{key}]"))
    if proj.motor.outline is not None:
        if not all(is_finite_number(c) for p in proj.motor.outline for c in p):
            errs.append(tr("value.coordinates", path="motor.outline"))


def _check_number(meta: Meta, value: Any, errs: list[str]) -> None:
    if not is_finite_number(value):
        errs.append(tr("value.finite", path=meta.path))
        return
    if meta.lo is not None:
        if meta.strict_lo and value <= meta.lo:
            errs.append(tr("value.greater", path=meta.path, lo=meta.lo, value=value))
        elif not meta.strict_lo and value < meta.lo:
            errs.append(tr("value.at_least", path=meta.path, lo=meta.lo, value=value))
    if meta.hi is not None and value > meta.hi:
        errs.append(tr("value.at_most", path=meta.path, hi=meta.hi, value=value))


_isnum = is_finite_number  # name from earlier versions


# ---------------------------------------------------------------------------
# 4. Type driven reading. Checks types and converts integral floats to int.
# ---------------------------------------------------------------------------
_BAD = object()  # marker of an invalid value (the message is already in errs)


def _build(cls, data: Any, path: str, errs: list[str]):
    """Build a dataclass from a dictionary. Invalid fields keep their default."""
    if not isinstance(data, dict):
        errs.append(tr("value.object", path=path.rstrip(".") or cls.__name__))
        return cls()
    hints = typing.get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    for key in sorted(set(data) - names, key=str):
        errs.append(tr("value.unknown_field", path=f"{path}{key}", cls=cls.__name__))
    kwargs: dict[str, Any] = {}
    for key, raw in data.items():
        if key in names:
            value = _coerce(raw, hints[key], f"{path}{key}", errs)
            if value is not _BAD:
                kwargs[key] = value
    return cls(**kwargs)


def _coerce(value: Any, hint: Any, path: str, errs: list[str]):
    """Check value against the type hint. Returns the (converted) value or _BAD."""
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):  # Optional[X] or X | None
        if value is None:
            return None
        inner = [a for a in args if a is not type(None)][0]
        return _coerce(value, inner, path, errs)
    if dataclasses.is_dataclass(hint):
        return _build(hint, value, path + ".", errs)
    if hint is bool:
        if not isinstance(value, bool):
            errs.append(tr("value.bool", path=path))
            return _BAD
        return value
    if hint is float:
        if not is_finite_number(value):
            errs.append(tr("value.finite", path=path))
            return _BAD
        return float(value)
    if hint is int:
        if not is_finite_number(value) or int(value) != value:
            errs.append(tr("value.integer", path=path))
            return _BAD
        return int(value)
    if hint is str:
        if not isinstance(value, str):
            errs.append(tr("value.text", path=path))
            return _BAD
        return value
    if origin is list:
        if not isinstance(value, list):
            errs.append(tr("value.list", path=path))
            return _BAD
        items = [_coerce(v, args[0], f"{path}[{i}]", errs) for i, v in enumerate(value)]
        return [v for v in items if v is not _BAD]
    if origin is dict:
        if not isinstance(value, dict):
            errs.append(tr("value.object", path=path))
            return _BAD
        return {str(k): _coerce(v, args[1], f"{path}[{k}]", errs) for k, v in value.items()}
    return value


def motor_from_dict(data: Any) -> MotorSpec:
    """Read a MotorSpec from a dictionary (type checks as in Project.from_dict, without project validation)."""
    errs: list[str] = []
    motor = _build(MotorSpec, data, "motor.", errs)
    if errs:
        raise ConfigError(errs)
    return motor


def schema() -> dict[str, Any]:
    """Description of all fields for the UI (labels in the current language)."""
    return {
        "fields": [
            {
                "path": m.path, "label": m.label, "tip": m.tip, "kind": m.kind, "lo": m.lo, "hi": m.hi,
                "strict_lo": m.strict_lo, "options": [[o, m.option_label(o)] for o in m.options] if m.options else None,
                "group": m.group, "optional": m.optional,
            }
            for m in FIELD_META
        ]
    }
