"""Geometriemodell. Uebersetzt die Konfiguration in konkrete Ebenen und Bauteile.

Trennung der Begriffe fuer die Gewindestange (siehe RodGeometry).
  1. feste Motorebene (Montageflaeche, z_mount)
  2. Laenge unter der Motorebene (length_below_mount)
  3. maximaler Hub oberhalb von G0 (stroke)
  4. Gewindeueberstand und Sicherheitszuschlaege (engage_below, length_tolerance)

Koordinatensysteme
  * Welt. x, y in der Draufsicht, z = 0 ist die Oberseite von G0, nach unten negativ.
  * Stangenrahmen. Ursprung ist die Achse der eigenen Gewindestange. Gehaeuse und
    Zahnrad werden hier beschrieben und bei der Platzierung um die Stange gedreht.

Annahmen des vereinfachten Modells (bewusst klein gehalten)
  * Gehaeuse = konvexes Prisma (Rechteck, Umriss oder Skizze), Zahnrad = Quader der
    Abmessungen Durchmesser mal Breite (konservative Einhuellende eines Zylinders),
    keine Zahngeometrie.
  * Der Eingriff Zahnrad zu Gewinde ist nur ueber den Achsabstand (center_distance)
    festgelegt. Er gilt nicht als Kollision. Die mechanische Funktion muss mit den
    realen Bauteilen separat validiert werden.
  * Die Stange wird als Zylinder ueber ihren gesamten Verfahrweg modelliert
    (Huelle von eingefahrener bis ausgefahrener Stellung).

Das Modell liest die Konfiguration einmal beim Erzeugen. Spaetere Aenderungen am
Project wirken erst in einem neuen Model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

from .config import ConfigError, Project
from .errors import SketchError
from .geometry import BBox, Footprint, Point, Prism, point_polygon_distance, rotate, z_gap
from .sketch import housing_polygon
from .units import EPS, KEY_DIGITS

PARTS_CACHE_LIMIT = 400_000  # Anzahl zwischengespeicherter Platzierungen, danach wird geleert

# Bauteilarten. Die Beschriftung erscheint in Meldungen wie "Motor liegt ausserhalb des Bauraums".
KIND_HOUSING, KIND_GEAR, KIND_ROD, KIND_OBSTACLE = "housing", "gear", "rod", "obstacle"
PART_LABELS = {KIND_HOUSING: "Motor", KIND_GEAR: "Zahnrad", KIND_ROD: "Stange"}


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
    """Berechnete Laengen einer Stange fuer eine bestimmte Motorebene (mm, z=0 ist G0 Oberseite).

    ``stroke``, ``tip_extended`` und ``length_above_g0`` haben immer denselben Wert. Sie bleiben
    getrennt, weil sie in der Ausgabe unterschiedliche Fragen beantworten."""

    plane_index: int
    z_mount: float  # Montageflaeche des Motors
    z_axis: float  # Hoehe der Zahnradachse
    stroke: float  # Hub oberhalb von G0
    tip_extended: float  # Spitze bei maximalem Ausfahren (= stroke)
    tip_retracted: float  # Spitze eingefahren (= -retract_depth)
    bottom_extended: float  # Stangenende unten bei maximalem Ausfahren
    bottom_retracted: float  # Stangenende unten eingefahren (tiefster Punkt der Huelle)
    length: float  # erforderliche Gesamtlaenge
    length_below_mount: float  # Teil der Stange unter der Montageflaeche (ausgefahren)
    length_above_g0: float  # Teil der Stange ueber G0 bei maximalem Hub
    engage_below_actual: float  # tatsaechliches Gewinde unter der Achse bei max. Ausfahren
    engage_above_actual: float  # tatsaechliches Gewinde ueber der Achse bei vollem Einfahren

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Part:
    """Ein Bauteil im Layout."""

    kind: str  # KIND_HOUSING | KIND_GEAR | KIND_ROD | KIND_OBSTACLE
    prism: Prism
    owner: Optional[int] = None  # Unit Id, None bei festen Hindernissen
    label: str = ""


class PlaneStack:
    """Die Ebenen G0 bis Gn mit Hoehen und Dicken (aus StackSpec)."""

    def __init__(self, project: Project):
        stack = project.stack
        self.planes: list[Plane] = [
            Plane(i, f"G{i}", z_top, stack.plane_thickness(i)) for i, z_top in enumerate(stack.plane_tops())
        ]
        for upper, lower in zip(self.planes, self.planes[1:]):
            if lower.z_top >= upper.z_bottom:
                raise ConfigError(
                    f"Ebenen {upper.name} und {lower.name} überlappen. Abstand {upper.z_top - lower.z_top:.2f} mm "
                    f"ist kleiner als die Dicke von {upper.name} ({upper.thickness:.2f} mm)"
                )

    def __getitem__(self, i: int) -> Plane:
        return self.planes[i]

    @property
    def motor_planes(self) -> list[Plane]:
        return self.planes[1:]

    def free_height_above(self, i: int) -> float:
        """Freier Raum ueber der Oberseite von Ebene i bis zur Unterseite der Ebene darueber (inf fuer G0)."""
        if i <= 0:
            return math.inf
        return self.planes[i - 1].z_bottom - self.planes[i].z_top

    def free_height_below(self, i: int) -> float:
        """Freier Raum unter Ebene i bis zur Oberseite der naechsten unteren Ebene (inf bei der letzten)."""
        if i + 1 < len(self.planes):
            return self.planes[i].z_bottom - self.planes[i + 1].z_top
        return math.inf


class Model:
    """Kompiliertes Projekt. Erzeugt Bauteile fuer Platzierungen und prueft statische Bedingungen."""

    def __init__(self, project: Project):
        project.validate()
        self.project = project
        motor = project.motor
        # Konstante Groessen aus der Konfiguration
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
        # Zwischenspeicher
        self._parts_cache: dict[tuple, list[Part]] = {}
        self._housing_cache: dict[float, list[Point]] = {}
        self._cd_problem_cache: dict[float, str] = {}
        # Abgeleitete Geometrie (Reihenfolge wichtig. Stangen vor Ebenenpruefung, Gehaeuse vor Radius)
        self._rod_geo = {p.index: self._compute_rod(p) for p in self.stack.motor_planes}
        self._plane_problems = {p.index: self._check_plane(p) for p in self.stack.motor_planes}
        self.obstacles = self._build_obstacles()
        self.housing_nominal = self._housing_polygon()
        self.unit_radius = self._compute_unit_radius()

    # -- Hoehen ---------------------------------------------------------------
    @property
    def _mount_top(self) -> bool:
        """True, wenn der Motor auf der Ebene steht, False, wenn er darunter haengt."""
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

    # -- Gewindestange -------------------------------------------------------
    def _compute_rod(self, plane: Plane) -> RodGeometry:
        rod = self.project.rod
        z_axis = self._axis_z(plane)
        z_mount = self._mount_z(plane)
        tip_extended = rod.stroke  # Spitze bei vollem Hub, bezogen auf Oberseite G0 (z=0)
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

    # -- Statische Pruefungen ---------------------------------------------------
    def _check_plane(self, plane: Plane) -> list[str]:
        """Prueft, ob Gehaeuse und Zahnrad in den vertikalen Bauraum passen. Liefert Probleme."""
        problems: list[str] = []
        allowed = self.project.stack.allowed_planes
        gap = self.gap
        if allowed is not None and plane.index not in allowed:
            problems.append("Ebene ist nicht als Motorebene erlaubt")
        housing_z = self._housing_z(plane)
        gear_z = self._gear_z(plane)
        for other in self.stack.planes:
            # Das Gehaeuse sitzt auf der eigenen Ebene. Das Zahnrad muss dagegen auch von ihr Abstand halten.
            if other.index != plane.index:
                dist = z_gap(*housing_z, other.z_bottom, other.z_top)
                if dist < gap - EPS:
                    problems.append(
                        f"Motorgehäuse (Höhe {housing_z[1] - housing_z[0]:.1f} mm) passt nicht zwischen die Ebenen. "
                        f"Abstand zu {other.name} nur {max(dist, 0):.2f} mm, benötigt {gap:.2f} mm"
                    )
            dist = z_gap(*gear_z, other.z_bottom, other.z_top)
            if dist < gap - EPS:
                problems.append(
                    f"Zahnrad kollidiert vertikal mit {other.name} (Abstand {max(dist, 0):.2f} mm, benötigt {gap:.2f} mm)"
                )
        rod = self._rod_geo[plane.index]
        if rod.engage_above_actual < self.project.rod.engage_above - EPS:
            problems.append(
                f"Zahnradachse liegt zu nah an G0. Eingefahren nur {rod.engage_above_actual:.1f} mm Gewinde "
                f"über der Achse, benötigt {self.project.rod.engage_above:.1f} mm"
            )
        return problems

    def plane_problems(self, plane_index: int) -> list[str]:
        return list(self._plane_problems[plane_index])

    def usable_planes(self) -> list[int]:
        """Motorebenen ohne Hoehenprobleme, die erlaubt sind und mindestens einen Motor tragen duerfen."""
        return [
            p.index for p in self.stack.motor_planes
            if not self._plane_problems[p.index] and self.capacity.get(p.index, 1) > 0
        ]

    def cd_problem(self, cd: Optional[float]) -> str:
        """Leer, wenn das Gehaeuse bei diesem Achsabstand die eigene Stange freihaelt, sonst Meldung."""
        motor = self.project.motor
        key = round(motor.center_distance if cd is None else cd, 9)
        cached = self._cd_problem_cache.get(key)
        if cached is not None:
            return cached
        distance = point_polygon_distance(0.0, 0.0, self.housing_rod(cd)) - self.rod_r
        message = ""
        if distance < motor.own_clearance - EPS:
            message = (
                f"Motorgehäuse berührt die eigene Stange (Abstand {max(distance, 0):.2f} mm, benötigt "
                f"{motor.own_clearance:.2f} mm). Zahnradabstand oder Achsabstand anpassen"
            )
        self._cd_problem_cache[key] = message
        return message

    def angles_for(self, plane_index: int) -> tuple[float, ...]:
        """Erlaubte Drehwinkel (Grad) auf dieser Ebene. Unveraenderlich, weil oft in Schleifen genutzt."""
        return self._plane_angles[plane_index]

    # -- Gehaeuse im Stangenrahmen ------------------------------------------------
    def _housing_polygon(self) -> list[Point]:
        """Gehaeusekontur im Stangenrahmen (Ursprung = Stangenachse) bei nominalem Achsabstand."""
        try:
            return housing_polygon(self.project.motor)
        except SketchError as exc:
            raise ConfigError(exc.errors) from exc

    def housing_rod(self, cd: Optional[float] = None) -> list[Point]:
        """Gehaeusekontur im Stangenrahmen fuer einen Achsabstand.

        Gehaeuse und Zahnradachse gehoeren zusammen, nur die Stange bleibt im Ursprung. Ein
        groesserer Achsabstand verschiebt das Gehaeuse daher in -x."""
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
    def housing_local(self) -> list[Point]:  # Name aus frueheren Versionen
        return self.housing_nominal

    def _compute_unit_radius(self) -> float:
        """Obere Schranke fuer den Abstand aller Bauteilpunkte von der Stangenachse (fuer Raster)."""
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

    # -- Bauteile -------------------------------------------------------------
    def unit_parts(
        self, owner: int, x: float, y: float, plane_index: int, angle_deg: float, cd: Optional[float] = None
    ) -> list[Part]:
        """Gehaeuse, Zahnrad und Stangenhuelle einer Platzierung.

        (x, y) ist die Position der Gewindestange, angle_deg die Drehung des Motors um die Stange,
        cd der Achsabstand (None = nominal). Die Prismen werden zwischengespeichert und geteilt,
        die Part Objekte sind fuer jeden Aufruf neu.
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
            """Punkt im Stangenrahmen in Weltkoordinaten (Drehung um die Stange)."""
            dx, dy = rotate(px, py, angle_rad)
            return (x + dx, y + dy)

        housing = Footprint.polygon([world(px, py) for px, py in self.housing_rod(cd)])
        gear_x, gear_y = world(-(motor.center_distance if cd is None else cd), 0.0)
        gear = Footprint.rect(gear_x, gear_y, motor.gear_diameter, motor.gear_width, angle_rad)
        rod_circle = Footprint.circle(x, y, self.rod_r)
        return [
            Part(KIND_HOUSING, Prism(housing, *self._housing_z(plane)), None, PART_LABELS[KIND_HOUSING]),
            Part(KIND_GEAR, Prism(gear, *self._gear_z(plane)), None, PART_LABELS[KIND_GEAR]),
            Part(KIND_ROD, Prism(rod_circle, rod.bottom_retracted, rod.tip_extended), None, PART_LABELS[KIND_ROD]),
        ]

    def unit_bbox(self, x: float, y: float, plane_index: int, angle_deg: float, cd: Optional[float] = None) -> BBox:
        """Bounding Box aller Bauteile einer Platzierung in der Draufsicht."""
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
            if obstacle.plane is not None:  # Sperrzone. Gilt fuer die Platte und den Raum der Motoren dieser Ebene
                plane = self.stack[obstacle.plane]
                housing_z0, housing_z1 = self._housing_z(plane)
                z0, z1 = min(housing_z0, plane.z_bottom), max(housing_z1, plane.z_top)
            out.append(Part(KIND_OBSTACLE, Prism(footprint, z0, z1), None, obstacle.name or f"Hindernis {i + 1}"))
        return out

    # -- Bauraum --------------------------------------------------------------
    def within_bounds(self, parts: list[Part], plane_index: int) -> Optional[str]:
        """Gibt None zurueck, wenn alles im Bauraum (und in den Montagebereichen) liegt, sonst eine Meldung."""
        bounds = self.project.bounds
        margin = bounds.edge_margin
        x0, y0 = bounds.xmin + margin, bounds.ymin + margin
        x1, y1 = bounds.xmax - margin, bounds.ymax - margin
        for part in parts:
            if bounds.parts_in_bounds == "rods" and part.kind != KIND_ROD:
                continue
            bx0, by0, bx1, by1 = part.prism.fp.bbox
            if bx0 < x0 - EPS or by0 < y0 - EPS or bx1 > x1 + EPS or by1 > y1 + EPS:
                return f"{part.label} liegt außerhalb des Bauraums"
        zones = self.project.stack.mount_zones.get(str(plane_index))
        if zones:
            for part in parts:
                if part.kind == KIND_HOUSING and not any(_bbox_inside(part.prism.fp.bbox, zone) for zone in zones):
                    return "Motor liegt außerhalb der Montagebereiche der Ebene"
        return None


def _bbox_inside(box: BBox, zone: list[float]) -> bool:
    return box[0] >= zone[0] - EPS and box[1] >= zone[1] - EPS and box[2] <= zone[2] + EPS and box[3] <= zone[3] + EPS
