"""Geometric model. Turns the configuration into concrete layers and parts.

Separate terms of the threaded rod (see RodGeometry)
  1. fixed motor layer (mounting face, z_mount)
  2. length below the motor layer (length_below_mount)
  3. maximum stroke above G0 (stroke)
  4. thread overhang and safety allowances (engage_below, length_tolerance)

Coordinate systems
  * World. x, y in top view with the origin (0, 0) at the bottom left corner of the build area,
    z = 0 is the top face of G0, negative below.
  * Rod frame. The origin is the axis of the unit's own threaded rod. Housing and gear are described
    here and rotated about the rod when placed.

Assumptions of the simplified model (kept small on purpose)
  * Housing = convex prism (rectangle, outline or sketch), gear = box of diameter x width (a
    conservative envelope of a cylinder), no tooth geometry.
  * The mesh of gear and thread is only defined by the centre distance (center_distance). It does not
    count as a collision. The mechanical function must be validated separately with the real parts.
  * The rod is modelled as a cylinder over its whole travel (hull from the retracted to the extended
    position).

The model reads the configuration once when it is created. Later changes to the Project only take
effect in a new Model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

from .config import ConfigError, Project
from .errors import SketchError
from .geometry import BBox, Footprint, Point, Prism, point_polygon_distance, rotate, z_gap
from .i18n import LocalText, tr
from .sketch import housing_polygon
from .units import EPS, KEY_DIGITS

PARTS_CACHE_LIMIT = 400_000  # number of cached placements, the cache is cleared afterwards

# Part kinds. Their label appears in messages like "Motor lies outside the build area".
KIND_HOUSING, KIND_GEAR, KIND_ROD, KIND_OBSTACLE = "housing", "gear", "rod", "obstacle"


def part_label(kind: str) -> LocalText:
    return tr(f"part.{kind}")


@dataclass(frozen=True)
class Plane:
    index: int  # 0 = G0
    name: str
    z_top: float
    thickness: float

    @property
    def z_bottom(self) -> float:
        return self.z_top - self.thickness


@dataclass(frozen=True)
class RodGeometry:
    """Computed lengths of a rod for one motor layer (mm, z = 0 is the top face of G0).

    ``stroke``, ``tip_extended`` and ``length_above_g0`` always have the same value. They stay separate
    because they answer different questions in the output."""

    plane_index: int
    z_mount: float  # mounting face of the motor
    z_axis: float  # height of the gear axis
    stroke: float  # stroke above G0
    tip_extended: float  # tip when fully extended (= stroke)
    tip_retracted: float  # tip when retracted (= -retract_depth)
    bottom_extended: float  # lower rod end when fully extended
    bottom_retracted: float  # lower rod end when retracted (lowest point of the hull)
    length: float  # required total length
    length_below_mount: float  # part of the rod below the mounting face (extended)
    length_above_g0: float  # part of the rod above G0 at full stroke
    engage_below_actual: float  # actual thread below the axis when fully extended
    engage_above_actual: float  # actual thread above the axis when fully retracted

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Part:
    """A part of the layout."""

    kind: str  # KIND_HOUSING | KIND_GEAR | KIND_ROD | KIND_OBSTACLE
    prism: Prism
    owner: Optional[int] = None  # unit id, None for fixed obstacles
    label: str = ""


class PlaneStack:
    """The layers G0 to Gn with heights and thicknesses (from StackSpec)."""

    def __init__(self, project: Project):
        stack = project.stack
        self.planes: list[Plane] = [
            Plane(i, f"G{i}", z_top, stack.plane_thickness(i)) for i, z_top in enumerate(stack.plane_tops())
        ]
        for upper, lower in zip(self.planes, self.planes[1:]):
            if lower.z_top >= upper.z_bottom:
                raise ConfigError(tr("model.planes_overlap", upper=upper.name, lower=lower.name,
                                     distance=upper.z_top - lower.z_top, thickness=upper.thickness))

    def __getitem__(self, i: int) -> Plane:
        return self.planes[i]

    @property
    def motor_planes(self) -> list[Plane]:
        return self.planes[1:]

    def free_height_above(self, i: int) -> float:
        """Free space above the top face of layer i up to the bottom face of the layer above (inf for G0)."""
        if i <= 0:
            return math.inf
        return self.planes[i - 1].z_bottom - self.planes[i].z_top

    def free_height_below(self, i: int) -> float:
        """Free space below layer i down to the top face of the next lower layer (inf for the last one)."""
        if i + 1 < len(self.planes):
            return self.planes[i].z_bottom - self.planes[i + 1].z_top
        return math.inf


class Model:
    """Compiled project. Creates parts for placements and checks static conditions."""

    def __init__(self, project: Project):
        project.validate()
        self.project = project
        motor = project.motor
        # Constant values from the configuration
        self.stack = PlaneStack(project)
        self.gap = project.required_gap
        self.rod_r = project.rod.diameter / 2.0
        self.hole_r = self.rod_r + project.rod.hole_clearance
        self.angles = project.allowed_angle_list()
        self._plane_angles = {
            i: tuple(project.angles_for_plane(i)) for i in range(1, project.stack.n_motor_planes + 1)
        }
        self.center_distances = motor.center_distances()
        self.capacity = {int(k): v for k, v in project.stack.max_per_plane.items()}
        # Caches
        self._parts_cache: dict[tuple, list[Part]] = {}
        self._housing_cache: dict[float, list[Point]] = {}
        self._cd_problem_cache: dict[float, str] = {}
        # Derived geometry (order matters. Rods before the layer check, housing before the radius)
        self._rod_geo = {p.index: self._compute_rod(p) for p in self.stack.motor_planes}
        self._plane_problems = {p.index: self._check_plane(p) for p in self.stack.motor_planes}
        self.obstacles = self._build_obstacles()
        self.housing_nominal = self._housing_polygon()
        self.unit_radius = self._compute_unit_radius()

    # -- Heights ---------------------------------------------------------------
    @property
    def _mount_top(self) -> bool:
        """True if the motor stands on the layer, False if it hangs below it."""
        return self.project.motor.mount == "top"

    def _mount_z(self, plane: Plane) -> float:
        return plane.z_top if self._mount_top else plane.z_bottom

    def _axis_z(self, plane: Plane) -> float:
        axis_height = self.project.motor.axis_height
        return self._mount_z(plane) + (axis_height if self._mount_top else -axis_height)

    def _housing_z(self, plane: Plane) -> tuple[float, float]:
        z_mount, height = self._mount_z(plane), self.project.motor.height
        return (z_mount, z_mount + height) if self._mount_top else (z_mount - height, z_mount)

    def _gear_z(self, plane: Plane) -> tuple[float, float]:
        z_axis = self._axis_z(plane)
        r = self.project.motor.gear_radius
        return (z_axis - r, z_axis + r)

    # -- Threaded rod -------------------------------------------------------
    def _compute_rod(self, plane: Plane) -> RodGeometry:
        rod = self.project.rod
        z_axis = self._axis_z(plane)
        z_mount = self._mount_z(plane)
        tip_extended = rod.stroke  # tip at full stroke, relative to the top face of G0 (z = 0)
        bottom_extended = z_axis - rod.engage_below - rod.length_tolerance
        length = tip_extended - bottom_extended
        tip_retracted = -rod.retract_depth
        return RodGeometry(
            plane_index=plane.index,
            z_mount=z_mount,
            z_axis=z_axis,
            stroke=rod.stroke,
            tip_extended=tip_extended,
            tip_retracted=tip_retracted,
            bottom_extended=bottom_extended,
            bottom_retracted=tip_retracted - length,
            length=length,
            length_below_mount=max(0.0, z_mount - bottom_extended),
            length_above_g0=rod.stroke,
            engage_below_actual=z_axis - bottom_extended,
            engage_above_actual=tip_retracted - z_axis,
        )

    def rod_geometry(self, plane_index: int) -> RodGeometry:
        return self._rod_geo[plane_index]

    # -- Static checks ---------------------------------------------------
    def _check_plane(self, plane: Plane) -> list[str]:
        """Check whether housing and gear fit into the vertical space. Returns the problems."""
        problems: list[str] = []
        allowed = self.project.stack.allowed_planes
        gap = self.gap
        if allowed is not None and plane.index not in allowed:
            problems.append(tr("model.plane_not_allowed"))
        housing_z = self._housing_z(plane)
        gear_z = self._gear_z(plane)
        for other in self.stack.planes:
            # The housing sits on its own layer. The gear in contrast must keep its distance from it too.
            if other.index != plane.index:
                dist = z_gap(*housing_z, other.z_bottom, other.z_top)
                if dist < gap - EPS:
                    problems.append(tr("model.housing_vertical", height=housing_z[1] - housing_z[0], other=other.name,
                                       distance=max(dist, 0), gap=gap))
            dist = z_gap(*gear_z, other.z_bottom, other.z_top)
            if dist < gap - EPS:
                problems.append(tr("model.gear_vertical", other=other.name, distance=max(dist, 0), gap=gap))
        rod = self._rod_geo[plane.index]
        if rod.engage_above_actual < self.project.rod.engage_above - EPS:
            problems.append(tr("model.axis_near_g0", actual=rod.engage_above_actual, required=self.project.rod.engage_above))
        return problems

    def plane_problems(self, plane_index: int) -> list[str]:
        return list(self._plane_problems[plane_index])

    def usable_planes(self) -> list[int]:
        """Motor layers without height problems that are allowed and may carry at least one motor."""
        return [
            p.index for p in self.stack.motor_planes
            if not self._plane_problems[p.index] and self.capacity.get(p.index, 1) > 0
        ]

    def cd_problem(self, cd: Optional[float]) -> str:
        """Empty if the housing keeps clear of its own rod at this centre distance, otherwise a message."""
        motor = self.project.motor
        key = round(motor.center_distance if cd is None else cd, 9)
        cached = self._cd_problem_cache.get(key)
        if cached is not None:
            return cached
        distance = point_polygon_distance(0.0, 0.0, self.housing_rod(cd)) - self.rod_r
        message = ""
        if distance < motor.own_clearance - EPS:
            message = tr("model.own_rod", distance=max(distance, 0), required=motor.own_clearance)
        self._cd_problem_cache[key] = message
        return message

    def angles_for(self, plane_index: int) -> tuple[float, ...]:
        """Permitted angles (degrees) on this layer. Immutable because it is used in hot loops."""
        return self._plane_angles[plane_index]

    # -- Housing in the rod frame ------------------------------------------------
    def _housing_polygon(self) -> list[Point]:
        """Housing outline in the rod frame (origin = rod axis) at the nominal centre distance."""
        try:
            return housing_polygon(self.project.motor)
        except SketchError as exc:
            raise ConfigError(exc.errors) from exc

    def housing_rod(self, cd: Optional[float] = None) -> list[Point]:
        """Housing outline in the rod frame for a centre distance.

        Housing and gear axis belong together, only the rod stays at the origin. A larger centre
        distance therefore moves the housing in -x."""
        nominal = self.project.motor.center_distance
        if cd is None or abs(cd - nominal) < EPS:
            return self.housing_nominal
        key = round(cd, 9)
        cached = self._housing_cache.get(key)
        if cached is None:
            dx = nominal - cd
            cached = [(x + dx, y) for x, y in self.housing_nominal]
            self._housing_cache[key] = cached
        return cached

    @property
    def housing_local(self) -> list[Point]:  # name from earlier versions
        return self.housing_nominal

    def _compute_unit_radius(self) -> float:
        """Upper bound of the distance of all part points from the rod axis (for the spatial grid)."""
        motor = self.project.motor
        radius = self.rod_r
        gear_r, gear_half_width = motor.gear_radius, motor.gear_width / 2.0
        for cd in self.center_distances:
            for x, y in self.housing_rod(cd):
                radius = max(radius, math.hypot(x, y))
            for x in (-cd - gear_r, -cd + gear_r):
                for y in (-gear_half_width, gear_half_width):
                    radius = max(radius, math.hypot(x, y))
        return radius

    # -- Parts -------------------------------------------------------------
    def unit_parts(
        self, owner: int, x: float, y: float, plane_index: int, angle_deg: float, cd: Optional[float] = None
    ) -> list[Part]:
        """Housing, gear and rod hull of a placement.

        (x, y) is the position of the threaded rod, angle_deg the rotation of the motor about the rod,
        cd the centre distance (None = nominal). The prisms are cached and shared, the Part objects are
        new for every call.
        """
        key = (
            round(x, KEY_DIGITS), round(y, KEY_DIGITS), plane_index, round(angle_deg, KEY_DIGITS),
            None if cd is None else round(cd, KEY_DIGITS),
        )
        cached = self._parts_cache.get(key)
        if cached is None:
            cached = self._build_unit_parts(x, y, plane_index, angle_deg, cd)
            if len(self._parts_cache) >= PARTS_CACHE_LIMIT:
                self._parts_cache.clear()
            self._parts_cache[key] = cached
        return [Part(p.kind, p.prism, owner, p.label) for p in cached]

    def _build_unit_parts(self, x: float, y: float, plane_index: int, angle_deg: float, cd: Optional[float]) -> list[Part]:
        motor = self.project.motor
        plane = self.stack[plane_index]
        rod = self._rod_geo[plane_index]
        angle_rad = math.radians(angle_deg)

        def world(px: float, py: float) -> Point:
            """Point of the rod frame in world coordinates (rotation about the rod)."""
            dx, dy = rotate(px, py, angle_rad)
            return (x + dx, y + dy)

        housing = Footprint.polygon([world(px, py) for px, py in self.housing_rod(cd)])
        gear_x, gear_y = world(-(motor.center_distance if cd is None else cd), 0.0)
        gear = Footprint.rect(gear_x, gear_y, motor.gear_diameter, motor.gear_width, angle_rad)
        rod_circle = Footprint.circle(x, y, self.rod_r)
        return [
            Part(KIND_HOUSING, Prism(housing, *self._housing_z(plane)), None, part_label(KIND_HOUSING)),
            Part(KIND_GEAR, Prism(gear, *self._gear_z(plane)), None, part_label(KIND_GEAR)),
            Part(KIND_ROD, Prism(rod_circle, rod.bottom_retracted, rod.tip_extended), None, part_label(KIND_ROD)),
        ]

    def unit_bbox(self, x: float, y: float, plane_index: int, angle_deg: float, cd: Optional[float] = None) -> BBox:
        """Bounding box of all parts of a placement in top view."""
        boxes = [p.prism.fp.bbox for p in self.unit_parts(0, x, y, plane_index, angle_deg, cd)]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def _build_obstacles(self) -> list[Part]:
        out = []
        for i, obstacle in enumerate(self.project.obstacles):
            if obstacle.shape == "circle":
                footprint = Footprint.circle(obstacle.x, obstacle.y, obstacle.r)
            else:
                footprint = Footprint.rect(obstacle.x, obstacle.y, obstacle.w, obstacle.h, math.radians(obstacle.angle))
            z0, z1 = obstacle.z0, obstacle.z1
            if obstacle.plane is not None:  # keep out zone. Applies to the board and the motor space of this layer
                plane = self.stack[obstacle.plane]
                housing_z0, housing_z1 = self._housing_z(plane)
                z0, z1 = min(housing_z0, plane.z_bottom), max(housing_z1, plane.z_top)
            out.append(Part(KIND_OBSTACLE, Prism(footprint, z0, z1), None, obstacle.name or tr("part.obstacle_numbered", n=i + 1)))
        return out

    # -- Build area --------------------------------------------------------------
    def within_bounds(self, parts: list[Part], plane_index: int) -> Optional[str]:
        """None if everything lies inside the build area (and the mounting areas), otherwise a message."""
        bounds = self.project.bounds
        margin = bounds.edge_margin
        x0, y0 = bounds.xmin + margin, bounds.ymin + margin
        x1, y1 = bounds.xmax - margin, bounds.ymax - margin
        for part in parts:
            if bounds.parts_in_bounds == "rods" and part.kind != KIND_ROD:
                continue
            bx0, by0, bx1, by1 = part.prism.fp.bbox
            if bx0 < x0 - EPS or by0 < y0 - EPS or bx1 > x1 + EPS or by1 > y1 + EPS:
                return tr("model.outside_bounds", part=part.label)
        zones = self.project.stack.mount_zones.get(str(plane_index))
        if zones:
            for part in parts:
                if part.kind == KIND_HOUSING and not any(_bbox_inside(part.prism.fp.bbox, zone) for zone in zones):
                    return tr("model.outside_zones")
        return None


def _bbox_inside(box: BBox, zone: list[float]) -> bool:
    return box[0] >= zone[0] - EPS and box[1] >= zone[1] - EPS and box[2] <= zone[2] + EPS and box[3] <= zone[3] + EPS
