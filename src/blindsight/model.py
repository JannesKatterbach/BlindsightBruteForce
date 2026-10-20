"""Geometriemodell. Uebersetzt die Konfiguration in konkrete Ebenen und Bauteile.

Trennung der Begriffe fuer die Gewindestange (siehe RodGeometry).
  1. feste Motorebene (Montageflaeche, z_mount)
  2. Laenge unter der Motorebene (length_below_mount)
  3. maximaler Hub oberhalb von G0 (stroke)
  4. Gewindeueberstand und Sicherheitszuschlaege (engage_below, length_tolerance)

Annahmen des vereinfachten Modells (bewusst klein gehalten)
  * Gehaeuse = Quader, Zahnrad = Quader der Abmessungen Durchmesser mal Breite
    (konservative Einhuellende eines Zylinders), keine Zahngeometrie.
  * Der Eingriff Zahnrad zu Gewinde ist nur ueber den Achsabstand (center_distance)
    festgelegt. Er gilt nicht als Kollision. Die mechanische Funktion muss mit den
    realen Bauteilen separat validiert werden.
  * Die Stange wird als Zylinder ueber ihren gesamten Verfahrweg modelliert
    (Huelle von eingefahrener bis ausgefahrener Stellung).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .config import ConfigError, Project
from .geometry import Footprint, Prism, rect_corners, rotate_point, z_gap


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
    """Berechnete Laengen einer Stange fuer eine bestimmte Motorebene (mm, z=0 ist G0 Oberseite)."""

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
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Part:
    """Ein Bauteil im Layout."""

    kind: str  # "housing" | "gear" | "rod" | "obstacle"
    prism: Prism
    owner: Optional[int] = None  # Unit Id, None bei festen Hindernissen
    label: str = ""


class PlaneStack:
    def __init__(self, project: Project):
        s = project.stack
        n = s.n_motor_planes
        tops = [0.0]
        if s.mode == "uniform":
            tops += [-(i * s.uniform_spacing) for i in range(1, n + 1)]
        elif s.mode == "gaps":
            z = 0.0
            for g in s.gaps[:n]:
                z -= g
                tops.append(z)
        else:
            tops += [-d for d in s.distances[:n]]
        self.planes: list[Plane] = []
        for i, z in enumerate(tops):
            self.planes.append(Plane(i, f"G{i}", z, s.g0_thickness if i == 0 else s.thickness))
        for a, b in zip(self.planes, self.planes[1:]):
            if b.z_top >= a.z_bottom:
                raise ConfigError(
                    f"Ebenen {a.name} und {b.name} ueberlappen. Abstand {a.z_top - b.z_top:.2f} mm "
                    f"ist kleiner als die Dicke von {a.name} ({a.thickness:.2f} mm)"
                )

    def __getitem__(self, i: int) -> Plane:
        return self.planes[i]

    @property
    def motor_planes(self) -> list[Plane]:
        return self.planes[1:]

    def free_height_above(self, i: int) -> float:
        """Freier Raum ueber der Oberseite von Ebene i bis zur Unterseite der naechsten oberen Ebene."""
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
        self.stack = PlaneStack(project)
        self.gap = project.required_gap
        self.angles = project.allowed_angle_list()
        self._rod_geo: dict[int, RodGeometry] = {}
        self._plane_problems: dict[int, list[str]] = {}
        self._parts_cache: dict[tuple, list[Part]] = {}
        self.obstacles = self._build_obstacles()
        self.rod_r = project.rod.diameter / 2.0
        self.hole_r = self.rod_r + project.rod.hole_clearance
        for p in self.stack.motor_planes:
            self._rod_geo[p.index] = self._compute_rod(p)
            self._plane_problems[p.index] = self._check_plane(p)
        self.unit_radius = self._compute_unit_radius()

    # -- Gewindestange -------------------------------------------------------
    def _mount_z(self, plane: Plane) -> float:
        return plane.z_top if self.project.motor.mount == "top" else plane.z_bottom

    def _axis_z(self, plane: Plane) -> float:
        m = self.project.motor
        zm = self._mount_z(plane)
        return zm + m.axis_height if m.mount == "top" else zm - m.axis_height

    def _compute_rod(self, plane: Plane) -> RodGeometry:
        rod = self.project.rod
        z_axis = self._axis_z(plane)
        z_mount = self._mount_z(plane)
        tip_ext = rod.stroke  # Spitze bei vollem Hub, bezogen auf Oberseite G0 (z=0)
        bottom_ext = z_axis - rod.engage_below - rod.length_tolerance
        length = tip_ext - bottom_ext
        tip_ret = -rod.retract_depth
        bottom_ret = tip_ret - length
        return RodGeometry(
            plane_index=plane.index,
            z_mount=z_mount,
            z_axis=z_axis,
            stroke=rod.stroke,
            tip_extended=tip_ext,
            tip_retracted=tip_ret,
            bottom_extended=bottom_ext,
            bottom_retracted=bottom_ret,
            length=length,
            length_below_mount=max(0.0, z_mount - bottom_ext),
            length_above_g0=rod.stroke,
            engage_below_actual=z_axis - bottom_ext,
            engage_above_actual=tip_ret - z_axis,
        )

    def rod_geometry(self, plane_index: int) -> RodGeometry:
        return self._rod_geo[plane_index]

    # -- Z Pruefung je Ebene ---------------------------------------------------
    def _housing_z(self, plane: Plane) -> tuple[float, float]:
        m = self.project.motor
        zm = self._mount_z(plane)
        return (zm, zm + m.height) if m.mount == "top" else (zm - m.height, zm)

    def _gear_z(self, plane: Plane) -> tuple[float, float]:
        za = self._axis_z(plane)
        r = self.project.motor.gear_radius
        return (za - r, za + r)

    def _check_plane(self, plane: Plane) -> list[str]:
        """Prueft, ob Gehaeuse und Zahnrad in den vertikalen Bauraum passen. Liefert Probleme."""
        problems: list[str] = []
        s = self.project.stack
        gap = self.gap
        if s.allowed_planes is not None and plane.index not in s.allowed_planes:
            problems.append("Ebene ist nicht als Motorebene erlaubt")
        hz = self._housing_z(plane)
        gz = self._gear_z(plane)
        for other in self.stack.planes:
            if other.index != plane.index:
                g = z_gap(hz[0], hz[1], other.z_bottom, other.z_top)
                if g < gap - 1e-9:
                    problems.append(
                        f"Motorgehaeuse (Hoehe {hz[1] - hz[0]:.1f} mm) passt nicht zwischen die Ebenen. "
                        f"Abstand zu {other.name} nur {max(g, 0):.2f} mm, benoetigt {gap:.2f} mm"
                    )
            g = z_gap(gz[0], gz[1], other.z_bottom, other.z_top)
            if g < gap - 1e-9:
                problems.append(
                    f"Zahnrad kollidiert vertikal mit {other.name} (Abstand {max(g, 0):.2f} mm, benoetigt {gap:.2f} mm)"
                )
        geo = self._rod_geo[plane.index]
        if geo.engage_above_actual < self.project.rod.engage_above - 1e-9:
            problems.append(
                f"Zahnradachse liegt zu nah an G0. Eingefahren nur {geo.engage_above_actual:.1f} mm Gewinde "
                f"ueber der Achse, benoetigt {self.project.rod.engage_above:.1f} mm"
            )
        m = self.project.motor
        # Gehaeuse gegen eigene Stange (rein lokal, unabhaengig von der Position)
        rx, ry = m.rod_local
        own = Footprint.rect(0, 0, m.width, m.depth).pts
        from .geometry import point_polygon_distance

        d = point_polygon_distance(rx, ry, own) - self.rod_r
        if d < m.own_clearance - 1e-9:
            problems.append(
                f"Motorgehaeuse beruehrt die eigene Stange (Abstand {max(d, 0):.2f} mm, benoetigt "
                f"{m.own_clearance:.2f} mm). Zahnradabstand oder Achsabstand anpassen"
            )
        return problems

    def plane_problems(self, plane_index: int) -> list[str]:
        return self._plane_problems[plane_index]

    def usable_planes(self) -> list[int]:
        return [p.index for p in self.stack.motor_planes if not self._plane_problems[p.index]]

    # -- Bauteile -------------------------------------------------------------
    def _compute_unit_radius(self) -> float:
        """Obere Schranke fuer den Abstand aller Bauteilpunkte von der Stangenachse (fuer Raster)."""
        m = self.project.motor
        rx, ry = m.rod_local
        pts = rect_corners(0, 0, m.width, m.depth)
        r = max(math.hypot(x - rx, y - ry) for x, y in pts)
        gx0, gx1 = m.shaft_x - m.gear_radius, m.shaft_x + m.gear_radius
        gy0 = m.depth / 2 + m.gear_gap
        gy1 = gy0 + m.gear_width
        for x in (gx0, gx1):
            for y in (gy0, gy1):
                r = max(r, math.hypot(x - rx, y - ry))
        return max(r, self.rod_r)

    def unit_parts(self, owner: int, x: float, y: float, plane_index: int, angle_deg: float) -> list[Part]:
        """Erzeugt Gehaeuse, Zahnrad und Stangenhuelle einer Platzierung.

        (x, y) ist die Position der Gewindestange, angle_deg die Drehung des Motors um die Stange.
        """
        key = (round(x, 6), round(y, 6), plane_index, round(angle_deg, 6))
        cached = self._parts_cache.get(key)
        if cached is not None:
            return [Part(p.kind, p.prism, owner, p.label) for p in cached]
        m = self.project.motor
        geo = self._rod_geo[plane_index]
        plane = self.stack[plane_index]
        a = math.radians(angle_deg)
        rx, ry = m.rod_local

        def world(lx: float, ly: float) -> tuple[float, float]:
            return rotate_point(x + (lx - rx), y + (ly - ry), x, y, a)

        hz0, hz1 = self._housing_z(plane)
        gz0, gz1 = self._gear_z(plane)
        hc = world(0.0, 0.0)
        housing = Footprint.rect(hc[0], hc[1], m.width, m.depth, a)
        gcx, gcy = world(m.shaft_x, m.gear_center_y)
        gear = Footprint.rect(gcx, gcy, m.gear_diameter, m.gear_width, a)
        rod = Footprint.circle(x, y, self.rod_r)
        parts = [
            Part("housing", Prism(housing, hz0, hz1), owner, "Motor"),
            Part("gear", Prism(gear, gz0, gz1), owner, "Zahnrad"),
            Part("rod", Prism(rod, geo.bottom_retracted, geo.tip_extended), owner, "Stange"),
        ]
        self._parts_cache[key] = parts
        if len(self._parts_cache) > 400_000:
            self._parts_cache.clear()
        return [Part(p.kind, p.prism, owner, p.label) for p in parts]

    def _build_obstacles(self) -> list[Part]:
        out = []
        for i, o in enumerate(self.project.obstacles):
            if o.shape == "circle":
                fp = Footprint.circle(o.x, o.y, o.r)
            else:
                fp = Footprint.rect(o.x, o.y, o.w, o.h, math.radians(o.angle))
            out.append(Part("obstacle", Prism(fp, o.z0, o.z1), None, o.name or f"Hindernis {i + 1}"))
        return out

    # -- Bauraum --------------------------------------------------------------
    def within_bounds(self, parts: list[Part], plane_index: int) -> Optional[str]:
        """Gibt None zurueck, wenn alles im Bauraum liegt, sonst eine Fehlermeldung."""
        b = self.project.bounds
        mg = b.edge_margin
        x0, y0, x1, y1 = b.xmin + mg, b.ymin + mg, b.xmax - mg, b.ymax - mg
        eps = 1e-9
        for p in parts:
            if b.parts_in_bounds == "rods" and p.kind != "rod":
                continue
            bx0, by0, bx1, by1 = p.prism.fp.bbox
            if p.prism.fp.kind == "p":
                # exakt ueber Eckpunkte (bbox ist bei gedrehten Rechtecken konservativ, Ecken sind exakt)
                bx0 = min(q[0] for q in p.prism.fp.pts)
                bx1 = max(q[0] for q in p.prism.fp.pts)
                by0 = min(q[1] for q in p.prism.fp.pts)
                by1 = max(q[1] for q in p.prism.fp.pts)
            if bx0 < x0 - eps or by0 < y0 - eps or bx1 > x1 + eps or by1 > y1 + eps:
                return f"{p.label} liegt ausserhalb des Bauraums"
        zones = self.project.stack.mount_zones.get(str(plane_index))
        if zones:
            for p in parts:
                if p.kind != "housing":
                    continue
                bx0, by0, bx1, by1 = p.prism.fp.bbox
                if not any(
                    bx0 >= z[0] - eps and by0 >= z[1] - eps and bx1 <= z[2] + eps and by1 <= z[3] + eps for z in zones
                ):
                    return "Motor liegt ausserhalb der Montagebereiche der Ebene"
        return None
