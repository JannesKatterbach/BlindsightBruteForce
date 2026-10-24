"""Eingabedaten (Konfiguration) als Dataclasses mit schemagetriebener Validierung.

Alle Laengen in mm, Winkel in Grad. Die Konfiguration ist reines Datenmodell
und kennt weder Optimierer noch UI. Sie laesst sich als JSON laden und speichern.

Aufbau dieser Datei
  1. Dataclasses (RodSpec, MotorSpec, StackSpec, ...), Standardwerte sind Platzhalter
  2. Project mit Laden, Speichern und Validierung
  3. FIELD_META. Beschreibung jedes einfachen Feldes (Label, Hilfetext, Einheit,
     Grenzen, Auswahl). Daraus entstehen Feldpruefung, UI Formulare (/api/schema)
     und die Parametertabelle der README (docs.py)
  4. Typgetriebenes Einlesen aus JSON (_build, _coerce)

Erweitern. Ein neues einfaches Feld braucht ein Dataclass Attribut und einen
Eintrag in FIELD_META. Pruefungen, die mehrere Felder betreffen, gehoeren in die
passende ``_check_*`` Funktion in Abschnitt 2.

Wichtig. Die Standardwerte sind Platzhalter fuer ein erstes Ausprobieren und
keine Herstellerdaten. Alle mechanisch relevanten Masse muessen mit den realen
Bauteilen ueberschrieben werden.
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
from .patterns import PATTERNS
from .sketch import check_sketch_motor
from .units import EPS, EPS_AREA, FAR_AWAY, is_finite_number, normalize_angle_deg

MAX_ANGLE_COUNT = 100_000  # Schutz gegen winzige Winkelschritte

STACK_MODES = ("uniform", "gaps", "distances")
MOUNT_MODES = ("top", "bottom")
OBSTACLE_SHAPES = ("rect", "circle")


# ---------------------------------------------------------------------------
# 1. Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class RodSpec:
    """Gewindestange (vertikal)."""

    diameter: float = 4.0
    stroke: float = 50.0
    engage_below: float = 10.0
    engage_above: float = 10.0
    length_tolerance: float = 2.0
    retract_depth: float = 0.0
    hole_clearance: float = 0.5


@dataclass
class ConstraintSpec:
    """Ein Constraint der Motor Skizze (Typen und Bedeutung siehe sketch/constraints.py)."""

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
    """Parametrische Gehaeusekontur im Stangenrahmen (Ursprung = Stangenachse, mm)."""

    points: list[list[float]] = field(default_factory=list)
    constraints: list[ConstraintSpec] = field(default_factory=list)


@dataclass
class MotorSpec:
    """Motor mit seitlichem Antriebszahnrad, vereinfacht als Prisma plus Zahnradquader.

    Es gibt zwei Arten, das Gehaeuse zu beschreiben.

    Ohne Skizze (Gehaeusesystem, Motorwinkel 0 Grad, Draufsicht)
      * Gehaeuse um (0, 0) zentriert. Ein Rechteck width mal depth oder, mit
        ``outline``, ein konvexes Polygon (width und depth sind dann nur Anzeige).
      * Die Abtriebsachse verlaeuft parallel zu y bei x = shaft_x und tritt an der
        +y Seite aus. Das Zahnrad sitzt gear_gap hinter der obersten Gehaeusekante.
      * Die Gewindestange steht senkrecht im Abstand center_distance zur
        Abtriebsachse (in +x), auf Hoehe der Zahnradmitte.

    Mit Skizze (``sketch``, Stangenrahmen)
      * Ursprung ist die Stangenachse, das Zahnrad liegt bei (-center_distance, 0).
      * width, depth, shaft_x, gear_gap und outline werden ignoriert.
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
        """y der Zahnradmitte im Gehaeusesystem (hinter der obersten Kante der Kontur)."""
        top = max(p[1] for p in self.outline) if self.outline else self.depth / 2.0
        return top + self.gear_gap + self.gear_width / 2.0

    def center_distances(self) -> list[float]:
        """Zulaessige Achsabstaende, aufsteigend. Ohne Bereich nur der Nominalwert.

        Der Nominalwert ist immer enthalten (die Validierung stellt sicher, dass er im Bereich liegt)."""
        lo, hi = self.center_distance_min, self.center_distance_max
        steps = max(1, self.center_distance_steps)
        if lo is None or hi is None or steps == 1 or hi <= lo:
            return [self.center_distance]
        values = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
        if not any(abs(v - self.center_distance) < EPS for v in values):
            values.append(self.center_distance)
        return sorted(values)

    def rod_local(self, cd: Optional[float] = None) -> tuple[float, float]:
        """Position der Gewindestange im Gehaeusesystem (nur ohne Skizze sinnvoll)."""
        return (self.shaft_x + (self.center_distance if cd is None else cd), self.gear_center_y)


@dataclass
class StackSpec:
    """Ebenenaufbau. Z=0 ist die Oberseite von G0, nach unten negativ.

    mode "uniform"   gleicher Abstand uniform_spacing zwischen allen Ebenen (inkl. G0)
    mode "gaps"      gaps[i] ist der Abstand der Oberseiten von G(i) zu G(i+1)
    mode "distances" distances[i] ist der Abstand der Oberseite von G(i+1) zu G0
    """

    n_motor_planes: int = 3
    mode: str = "uniform"
    uniform_spacing: float = 20.0
    gaps: list[float] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)
    thickness: float = 1.6
    g0_thickness: float = 6.0
    thicknesses: Optional[list[float]] = None  # Dicke je Motorebene (ueberschreibt thickness)
    allowed_planes: Optional[list[int]] = None
    mount_zones: dict[str, list[list[float]]] = field(default_factory=dict)
    max_per_plane: dict[str, int] = field(default_factory=dict)
    plane_angles: dict[str, list[float]] = field(default_factory=dict)

    def plane_tops(self) -> list[float]:
        """Z der Oberseiten von G0 bis Gn (G0 bei 0, darunter negativ)."""
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
            raise ConfigError(f"stack.mode. Unbekannter Modus '{self.mode}'")
        return tops

    def plane_thickness(self, index: int) -> float:
        """Dicke der Ebene G<index> (0 = G0)."""
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
    """Festes Hindernis (Prisma). Ohne z0/z1 reicht es ueber alle Ebenen.

    Ist plane gesetzt, gilt es nur auf dieser Motorebene (Sperrzone, z.B. Loch oder Bauteil
    in der Platine), die Z Spanne ergibt sich dann aus der Ebene und der Motorhoehe.
    Der Winkel ``angle`` ist in Grad.
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
    """Prioritaeten der Optimierungsziele (relative Gewichte, werden normiert).

    Jedes Feld entspricht einem Eintrag in ``scoring.OBJECTIVES``."""

    count: float = 10.0
    area: float = 8.0
    uniformity: float = 2.0
    regularity: float = 1.0

    def as_dict(self) -> dict[str, float]:
        return dataclasses.asdict(self)


@dataclass
class SearchSpec:
    """Steuerung der Suche."""

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


# ---------------------------------------------------------------------------
# 2. Projekt
# ---------------------------------------------------------------------------
@dataclass
class Project:
    name: str = "Unbenannt"
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
        """Wirksamer Mindestabstand aller Bauteile."""
        return self.clearance + self.tolerance

    # -- (De)Serialisierung ------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        """Liest und validiert ein Projekt. Wirft ConfigError mit allen gefundenen Problemen."""
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
            raise ConfigError(f"Ungültiges JSON. {exc}") from exc
        except RecursionError:
            raise ConfigError("JSON zu tief verschachtelt") from None

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())

    # -- Validierung -------------------------------------------------------
    def validate(self) -> None:
        """Prueft erst jedes Feld einzeln (FIELD_META), dann die Zusammenhaenge.

        Die Zusammenhangspruefungen setzen gueltige Einzelwerte voraus und laufen daher nur,
        wenn die Feldpruefung fehlerfrei war."""
        errs: list[str] = []
        _validate_fields(self, errs)
        if errs:
            raise ConfigError(errs)
        for check in (_check_motor, _check_stack, _check_bounds, _check_obstacles, _check_search):
            check(self, errs)
        if errs:
            raise ConfigError(errs)

    # -- Winkel ------------------------------------------------------------
    def allowed_angle_list(self) -> list[float]:
        """Zulaessige Motorwinkel in Grad, in [0, 360), aufsteigend und ohne Duplikate."""
        search = self.search
        if search.allowed_angles is not None:
            angles = {normalize_angle_deg(a) for a in search.allowed_angles}
        else:
            if search.angle_step <= 0:
                raise ConfigError("search.angle_step. Muss positiv sein")
            if (search.angle_max - search.angle_min) / search.angle_step > MAX_ANGLE_COUNT:
                raise ConfigError(f"search.angle_step. Zu klein, ergibt über {MAX_ANGLE_COUNT} Winkel")
            angles = set()
            a = search.angle_min
            while a < search.angle_max - EPS:
                angles.add(normalize_angle_deg(a))
                a += search.angle_step
        if not angles:
            raise ConfigError("search.allowed_angles. Keine zulässigen Motorwinkel")
        return sorted(angles)

    def angles_for_plane(self, plane: int) -> list[float]:
        """Zulaessige Winkel einer Ebene (globale Liste, durch plane_angles ersetzt)."""
        own = self.stack.plane_angles.get(str(plane))
        if own:
            return sorted({normalize_angle_deg(a) for a in own})
        return self.allowed_angle_list()


def _check_motor(proj: Project, errs: list[str]) -> None:
    motor = proj.motor
    if motor.axis_height > motor.height:
        errs.append("motor.axis_height. Die Abtriebsachse liegt außerhalb der Motorhöhe")
    lo, hi = motor.center_distance_min, motor.center_distance_max
    if (lo is None) != (hi is None):
        errs.append("motor.center_distance_min. Achsabstand min und max müssen zusammen angegeben werden")
    elif lo is not None and hi is not None:
        if hi < lo:
            errs.append("motor.center_distance_max. Muss >= center_distance_min sein")
        elif not lo - EPS <= motor.center_distance <= hi + EPS:
            errs.append(
                f"motor.center_distance. Der Achsabstand {motor.center_distance:g} liegt außerhalb des Bereichs "
                f"{lo:g} bis {hi:g}"
            )
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
            errs.append(f"stack.gaps. Modus 'gaps' braucht {n} Abstände (G0-G1, G1-G2, ...)")
        elif any(g <= 0 for g in stack.gaps[:n]):
            errs.append("stack.gaps. Alle Ebenenabstände müssen positiv sein")
    elif stack.mode == "distances":
        dist = stack.distances[:n]
        if len(dist) < n:
            errs.append(f"stack.distances. Modus 'distances' braucht {n} Abstände zu G0")
        elif any(x <= 0 for x in dist) or any(dist[i] >= dist[i + 1] for i in range(len(dist) - 1)):
            errs.append("stack.distances. Abstände zu G0 müssen positiv und streng aufsteigend sein")
    if stack.thicknesses is not None:
        if len(stack.thicknesses) < n:
            errs.append(f"stack.thicknesses. {n} Dicken erwartet (eine je Motorebene)")
        elif any(t <= 0 for t in stack.thicknesses):
            errs.append("stack.thicknesses. Alle Dicken müssen positiv sein")
    if len(errs) == before:
        errs.extend(plane_overlap_errors(stack))
    if stack.allowed_planes is not None:
        bad = [p for p in stack.allowed_planes if not 1 <= p <= n]
        if bad:
            errs.append(f"stack.allowed_planes. Ebenen {bad} existieren nicht (1..{n})")
        if not stack.allowed_planes:
            errs.append("stack.allowed_planes. Darf nicht leer sein (None = alle Ebenen)")
    for key, zones in stack.mount_zones.items():
        _check_plane_key("stack.mount_zones", key, n, errs)
        for zone in zones:
            if len(zone) != 4 or zone[2] <= zone[0] or zone[3] <= zone[1]:
                errs.append(f"stack.mount_zones[{key}]. Bereich muss [xmin, ymin, xmax, ymax] mit xmax>xmin, ymax>ymin sein")
    for key, cap in stack.max_per_plane.items():
        _check_plane_key("stack.max_per_plane", key, n, errs)
        if cap < 0:
            errs.append(f"stack.max_per_plane[{key}]. Darf nicht negativ sein")
    for key, angles in stack.plane_angles.items():
        _check_plane_key("stack.plane_angles", key, n, errs)
        if not angles:
            errs.append(f"stack.plane_angles[{key}]. Darf nicht leer sein")


def plane_overlap_errors(stack: StackSpec) -> list[str]:
    """Meldungen, wenn eine Ebene in die naechste hineinragt (Abstand kleiner als die Plattendicke)."""
    tops = stack.plane_tops()
    out = []
    for i in range(len(tops) - 1):
        bottom = tops[i] - stack.plane_thickness(i)
        if tops[i + 1] >= bottom:
            out.append(
                f"stack. Ebenen G{i} und G{i + 1} überlappen. Abstand {tops[i] - tops[i + 1]:.2f} mm "
                f"ist kleiner als die Dicke von G{i} ({stack.plane_thickness(i):.2f} mm)"
            )
    return out


def _check_bounds(proj: Project, errs: list[str]) -> None:
    bounds = proj.bounds
    if bounds.width <= 0 or bounds.height <= 0:
        errs.append("bounds. Bauraum hat keine positive Fläche (Breite und Höhe größer 0)")
    elif 2 * bounds.edge_margin >= min(bounds.width, bounds.height):
        errs.append("bounds.edge_margin. Randabstand ist größer als der halbe Bauraum")


def _check_obstacles(proj: Project, errs: list[str]) -> None:
    n = proj.stack.n_motor_planes
    for i, obstacle in enumerate(proj.obstacles):
        tag = f"obstacles[{i}]"
        if obstacle.shape not in OBSTACLE_SHAPES:
            errs.append(f"{tag}.shape. Muss 'rect' oder 'circle' sein")
        if obstacle.z1 < obstacle.z0:
            errs.append(f"{tag}. z1 muss >= z0 sein")
        if obstacle.shape == "rect" and (obstacle.w <= 0 or obstacle.h <= 0):
            errs.append(f"{tag}. Breite und Höhe müssen positiv sein")
        if obstacle.shape == "circle" and obstacle.r <= 0:
            errs.append(f"{tag}.r. Radius muss positiv sein")
        if obstacle.plane is not None and not 1 <= obstacle.plane <= n:
            errs.append(f"{tag}.plane. Ebene {obstacle.plane} existiert nicht (1..{n})")


def _check_search(proj: Project, errs: list[str]) -> None:
    search = proj.search
    for pattern in search.patterns:
        if pattern not in PATTERNS:
            errs.append(f"search.patterns. Unbekanntes Muster '{pattern}' ({', '.join(PATTERNS)})")
    if not search.patterns:
        errs.append("search.patterns. Mindestens ein Muster ist nötig")
    if len(search.patterns) != len(set(search.patterns)):
        errs.append("search.patterns. Muster doppelt angegeben")
    if search.angle_max <= search.angle_min:
        errs.append("search.angle_max. Muss größer als angle_min sein")
    if sum(search.weights.as_dict().values()) <= 0:
        errs.append("search.weights. Nicht alle Gewichte dürfen 0 sein")
    try:
        proj.allowed_angle_list()
    except ConfigError as exc:
        errs.extend(exc.errors)


def _check_plane_key(label: str, key: str, n: int, errs: list[str]) -> None:
    if not (key.isdigit() and 1 <= int(key) <= n):
        errs.append(f"{label}. Schlüssel '{key}' ist keine Motorebene (1..{n})")


def _check_outline(outline: list[list[float]], errs: list[str]) -> None:
    if len(outline) < 3 or any(len(p) != 2 for p in outline):
        errs.append("motor.outline. Mindestens 3 Punkte [x, y] nötig")
        return
    area = signed_area(outline)
    if abs(area) < EPS_AREA:
        errs.append("motor.outline. Kontur hat keine Fläche")
        return
    ccw = outline if area > 0 else list(reversed(outline))
    if not is_convex_ccw(ccw):
        errs.append("motor.outline. Kontur muss konvex sein (nicht konvexe Motoren bitte als Hülle angeben)")


# ---------------------------------------------------------------------------
# 3. Feldbeschreibung. Quelle fuer Validierung, UI Formulare und Doku.
#   kind  len (mm, in der UI umrechenbar), lenlist (Liste von Laengen in mm), num, int,
#         text, enum, list (Zahlenliste ohne Einheit), listint, liststr
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Meta:
    """Beschreibung eines Konfigurationsfeldes fuer Validierung, UI und Doku."""

    path: str
    label: str
    tip: str
    kind: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    strict_lo: bool = False  # True. Wert muss > lo sein
    options: Optional[tuple[tuple[str, str], ...]] = None
    group: str = ""
    optional: bool = False  # None erlaubt


FIELD_META: list[Meta] = [
    Meta("name", "Name", "Bezeichnung des Projekts", "text", group="general"),
    Meta("target_count", "Gewünschte Anzahl Stangen", "So viele Gewindestangen mit Motoren sollen platziert werden", "int", 1, 100000, group="general"),
    Meta("clearance", "Sicherheitsabstand", "Mindestabstand zwischen allen fremden Bauteilen", "len", 0, 1000, group="general"),
    Meta("tolerance", "Toleranz", "Wird zum Sicherheitsabstand addiert (Fertigung, Rundung). Wirksamer Abstand = Sicherheitsabstand + Toleranz", "len", 0, 1000, group="general"),
    Meta("rod.diameter", "Durchmesser", "Außendurchmesser des Gewindes", "len", 0, 1000, True, group="rod"),
    Meta("rod.stroke", "Maximaler Hub über G0", "So weit muss jede Stange oberhalb von G0 ausfahren können, unabhängig von der Motorebene", "len", 0, 100000, True, group="rod"),
    Meta("rod.engage_below", "Gewinde unter Zahnradachse (ausgefahren)", "Mindestgewinde unter der Zahnradachse bei maximalem Ausfahren", "len", 0, 100000, group="rod"),
    Meta("rod.engage_above", "Gewinde über Zahnradachse (eingefahren)", "Mindestgewinde über der Zahnradachse bei vollem Einfahren", "len", 0, 100000, group="rod"),
    Meta("rod.length_tolerance", "Längenzuschlag", "Zusätzlicher Sicherheitszuschlag der Stangenlänge", "len", 0, 100000, group="rod"),
    Meta("rod.retract_depth", "Spitze eingefahren unter G0", "Tiefe der Stangenspitze unter G0 bei vollem Einfahren (0 = bündig)", "len", 0, 100000, group="rod"),
    Meta("rod.hole_clearance", "Radiales Lochspiel", "Spiel der Durchgangslöcher in den Ebenen (je Seite)", "len", 0, 1000, group="rod"),
    Meta("motor.width", "Breite (x)", "Gehäusebreite quer zur Welle", "len", 0, 10000, True, group="motor"),
    Meta("motor.depth", "Tiefe (y, Wellenrichtung)", "Gehäusetiefe entlang der Welle", "len", 0, 10000, True, group="motor"),
    Meta("motor.height", "Höhe (z)", "Gehäusehöhe senkrecht zur Ebene", "len", 0, 10000, True, group="motor"),
    Meta("motor.shaft_x", "Abtriebsachse, x Versatz", "Seitlicher Versatz der Abtriebsachse zur Gehäusemitte", "len", -10000, 10000, group="motor"),
    Meta("motor.axis_height", "Achshöhe über Montagefläche", "Höhe der Abtriebsachse über der Montagefläche", "len", 0, 10000, group="motor"),
    Meta("motor.gear_diameter", "Zahnrad Durchmesser", "Außendurchmesser des Antriebszahnrads", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_width", "Zahnrad Breite", "Axiale Breite des Zahnrads", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_gap", "Abstand Gehäuse zu Zahnrad", "Axialer Abstand zwischen Gehäusekante und Zahnrad", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance", "Achsabstand Zahnrad zu Stange", "Abstand der Abtriebsachse zur Stangenachse. Der Eingriff ist nur über diesen Abstand modelliert", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance_min", "Achsabstand min (optional)", "Untergrenze, wenn der Optimierer den Achsabstand variieren darf", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_max", "Achsabstand max (optional)", "Obergrenze, wenn der Optimierer den Achsabstand variieren darf", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_steps", "Achsabstand Stufen", "Anzahl der Stufen zwischen min und max (1 = nur nominal)", "int", 1, 50, group="motor"),
    Meta("motor.own_clearance", "Eigenabstand Gehäuse zur Stange", "Mindestabstand des Gehäuses zur eigenen Stange", "len", 0, 1000, group="motor"),
    Meta("motor.mount", "Montage", "Motor steht auf der Ebene oder hängt darunter", "enum", group="motor",
         options=(("top", "Motor steht auf der Ebene"), ("bottom", "Motor hängt unter der Ebene"))),
    Meta("stack.n_motor_planes", "Anzahl Motorebenen", "Anzahl der Ebenen G1 bis Gn, keine feste Obergrenze", "int", 1, 1000, group="stack"),
    Meta("stack.mode", "Abstandsmodus", "Wie die Ebenenhöhen angegeben werden", "enum", group="stack",
         options=(("uniform", "Einheitlicher Abstand"), ("gaps", "Einzelabstände G(i) zu G(i+1)"), ("distances", "Abstand jeder Ebene zu G0"))),
    Meta("stack.uniform_spacing", "Einheitlicher Ebenenabstand", "Abstand zwischen allen Ebenen (Modus uniform)", "len", 0, 100000, True, group="stack"),
    Meta("stack.gaps", "Einzelabstände (Liste)", "Abstände G0-G1, G1-G2, ... (Modus gaps)", "lenlist", group="stack"),
    Meta("stack.distances", "Abstände zu G0 (Liste)", "Abstand jeder Motorebene zu G0, aufsteigend (Modus distances)", "lenlist", group="stack"),
    Meta("stack.thickness", "Dicke Motorebenen", "Plattendicke der Ebenen G1 bis Gn", "len", 0, 1000, True, group="stack"),
    Meta("stack.g0_thickness", "Dicke G0", "Plattendicke der oberen Referenzebene", "len", 0, 1000, True, group="stack"),
    Meta("stack.thicknesses", "Dicke je Ebene (Liste, optional)", "Eigene Dicke für jede Motorebene, überschreibt die gemeinsame Dicke", "lenlist", group="stack", optional=True),
    Meta("stack.allowed_planes", "Erlaubte Motorebenen (Liste, leer = alle)", "Nur diese Ebenen dürfen Motoren tragen", "listint", group="stack", optional=True),
    Meta("bounds.width", "Breite (x)", "Ausdehnung des Bauraums in x ab dem Ursprung unten links", "len", 0, 1e6, True, group="bounds"),
    Meta("bounds.height", "Höhe (y)", "Ausdehnung des Bauraums in y ab dem Ursprung unten links", "len", 0, 1e6, True, group="bounds"),
    Meta("bounds.edge_margin", "Randabstand", "Zusätzlicher Abstand aller Bauteile zum Rand", "len", 0, 1e6, group="bounds"),
    Meta("bounds.parts_in_bounds", "Im Bauraum müssen liegen", "Alle Bauteile oder nur die Stangen", "enum", group="bounds",
         options=(("all", "alle Bauteile"), ("rods", "nur Stangen"))),
    Meta("search.optimizer", "Optimierer", "Suchstrategie", "enum", group="search",
         options=(("pattern_greedy", "Muster und lokale Suche"), ("anneal_free", "Freie Verteilung (Annealing)"), ("exhaustive_small", "Exakt auf Raster (kleine Aufgaben)"))),
    Meta("search.layout_goal", "Anordnungsziel", "compact packt dicht (kleine Fläche), spread verteilt gleichmäßig über den ganzen Bauraum", "enum", group="search",
         options=(("compact", "Kompakt (kleine Grundfläche)"), ("spread", "Verteilt über den Bauraum"))),
    Meta("search.patterns", "Muster (square, hex_x, hex_y)", "Verteilungsstruktur der Kandidaten", "liststr", group="search"),
    Meta("search.fixed_pitch", "Feste Teilung (optional)", "Nur diese Rasterteilung verwenden statt sie zu suchen", "len", 0, 100000, True, group="search", optional=True),
    Meta("search.angle_step", "Winkelschritt (Grad)", "Raster der zulässigen Motorwinkel", "num", 0, 360, True, group="search"),
    Meta("search.angle_min", "Winkel von (Grad)", "Kleinster Motorwinkel", "num", -3600, 3600, group="search"),
    Meta("search.angle_max", "Winkel bis (Grad, exklusiv)", "360 = voller Kreis", "num", -3600, 3600, group="search"),
    Meta("search.allowed_angles", "Nur diese Winkel (Liste, leer = Raster)", "Explizite Liste erlaubter Motorwinkel", "list", group="search", optional=True),
    Meta("search.time_limit_s", "Zeitlimit (s)", "Maximale Rechenzeit", "num", 0, 86400, True, group="search"),
    Meta("search.max_candidates", "Max. Kandidaten", "Maximale Anzahl geprüften Platzierungen", "int", 1, 10**12, group="search"),
    Meta("search.seed", "Seed", "Zufallsstartwert für reproduzierbare Läufe", "int", 0, 2**31 - 1, group="search"),
    Meta("search.top_k", "Anzahl Lösungen", "Wie viele beste Lösungen behalten werden", "int", 1, 50, group="search"),
    Meta("search.refine_fraction", "Anteil lokale Suche", "Zeitanteil der Verfeinerung (0 bis 0.9)", "num", 0, 0.9, group="search"),
    Meta("search.stagnation_s", "Stagnation (s, optional)", "Beenden, wenn das Ziel erreicht ist und sich so lange nichts verbessert", "num", 0, 86400, True, group="search", optional=True),
    Meta("search.workers", "Parallele Läufe", "Anzahl Prozesse für unabhängige Seeds (1 = ohne Parallelisierung)", "int", 1, 64, group="search"),
    Meta("search.weights.count", "Anzahl Stangen", "Gewicht des Ziels Anzahl", "num", 0, 1000, group="weights"),
    Meta("search.weights.area", "Kleine Grundfläche", "Gewicht des Ziels Grundfläche", "num", 0, 1000, group="weights"),
    Meta("search.weights.uniformity", "Gleichmäßige Verteilung", "Gewicht der gleichmäßigen Nachbarabstände", "num", 0, 1000, group="weights"),
    Meta("search.weights.regularity", "Regelmäßiges Muster", "Gewicht der Quadrat oder Hexagonalordnung", "num", 0, 1000, group="weights"),
]
META_BY_PATH = {m.path: m for m in FIELD_META}
NUMERIC_KINDS = ("len", "num", "int")
NUMBER_LIST_KINDS = ("list", "lenlist", "listint")


def _get(obj: Any, path: str) -> Any:
    for key in path.split("."):
        obj = getattr(obj, key)
    return obj


def _validate_fields(proj: Project, errs: list[str]) -> None:
    """Prueft jedes Feld aus FIELD_META einzeln plus die Zahlen in Listen ohne eigene Meta."""
    for meta in FIELD_META:
        value = _get(proj, meta.path)
        if value is None:
            if not meta.optional:
                errs.append(f"{meta.path}. Wert fehlt")
            continue
        if meta.kind in NUMERIC_KINDS:
            _check_number(meta, value, errs)
        elif meta.kind == "enum":
            allowed = [option[0] for option in (meta.options or ())]
            if value not in allowed:
                errs.append(f"{meta.path}. Unzulässiger Wert '{value}'. Erlaubt. {allowed}")
        elif meta.kind in NUMBER_LIST_KINDS:
            if not all(is_finite_number(x) for x in value):
                errs.append(f"{meta.path}. Alle Einträge müssen endliche Zahlen sein")
    for i, obstacle in enumerate(proj.obstacles):
        for name in ("x", "y", "w", "h", "r", "angle", "z0", "z1"):
            if not is_finite_number(getattr(obstacle, name)):
                errs.append(f"obstacles[{i}].{name}. Muss eine endliche Zahl sein")
    for key, zones in proj.stack.mount_zones.items():
        if not all(is_finite_number(c) for zone in zones for c in zone):
            errs.append(f"stack.mount_zones[{key}]. Koordinaten müssen endliche Zahlen sein")
    if proj.motor.outline is not None:
        if not all(is_finite_number(c) for p in proj.motor.outline for c in p):
            errs.append("motor.outline. Koordinaten müssen endliche Zahlen sein")


def _check_number(meta: Meta, value: Any, errs: list[str]) -> None:
    if not is_finite_number(value):
        errs.append(f"{meta.path}. Muss eine endliche Zahl sein")
        return
    if meta.lo is not None:
        too_small = value <= meta.lo if meta.strict_lo else value < meta.lo
        if too_small:
            relation = "größer als" if meta.strict_lo else "mindestens"
            errs.append(f"{meta.path}. Muss {relation} {meta.lo:g} sein (ist {value:g})")
    if meta.hi is not None and value > meta.hi:
        errs.append(f"{meta.path}. Darf höchstens {meta.hi:g} sein (ist {value:g})")


_isnum = is_finite_number  # Name aus frueheren Versionen


# ---------------------------------------------------------------------------
# 4. Typgetriebenes Einlesen. Prueft Typen und wandelt ganzzahlige Floats in int um.
# ---------------------------------------------------------------------------
_BAD = object()  # Markierung fuer einen ungueltigen Wert (die Fehlermeldung steht schon in errs)


def _build(cls, data: Any, path: str, errs: list[str]):
    """Baut eine Dataclass aus einem Dictionary. Ungueltige Felder behalten ihren Standardwert."""
    if not isinstance(data, dict):
        errs.append(f"{path.rstrip('.') or cls.__name__}. Objekt erwartet")
        return cls()
    hints = typing.get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    for key in sorted(set(data) - names, key=str):
        errs.append(f"{path}{key}. Unbekanntes Feld in {cls.__name__}")
    kwargs: dict[str, Any] = {}
    for key, raw in data.items():
        if key in names:
            value = _coerce(raw, hints[key], f"{path}{key}", errs)
            if value is not _BAD:
                kwargs[key] = value
    return cls(**kwargs)


def _coerce(value: Any, hint: Any, path: str, errs: list[str]):
    """Prueft value gegen die Typangabe hint. Gibt den (umgewandelten) Wert oder _BAD zurueck."""
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):  # Optional[X] oder X | None
        if value is None:
            return None
        inner = [a for a in args if a is not type(None)][0]
        return _coerce(value, inner, path, errs)
    if dataclasses.is_dataclass(hint):
        return _build(hint, value, path + ".", errs)
    if hint is bool:
        if not isinstance(value, bool):
            errs.append(f"{path}. Muss true oder false sein")
            return _BAD
        return value
    if hint is float:
        if not is_finite_number(value):
            errs.append(f"{path}. Muss eine endliche Zahl sein")
            return _BAD
        return float(value)
    if hint is int:
        if not is_finite_number(value) or int(value) != value:
            errs.append(f"{path}. Muss eine ganze Zahl sein")
            return _BAD
        return int(value)
    if hint is str:
        if not isinstance(value, str):
            errs.append(f"{path}. Muss Text sein")
            return _BAD
        return value
    if origin is list:
        if not isinstance(value, list):
            errs.append(f"{path}. Liste erwartet")
            return _BAD
        items = [_coerce(v, args[0], f"{path}[{i}]", errs) for i, v in enumerate(value)]
        return [v for v in items if v is not _BAD]
    if origin is dict:
        if not isinstance(value, dict):
            errs.append(f"{path}. Objekt erwartet")
            return _BAD
        return {str(k): _coerce(v, args[1], f"{path}[{k}]", errs) for k, v in value.items()}
    return value


def motor_from_dict(data: Any) -> MotorSpec:
    """Liest eine MotorSpec aus einem Dictionary (Typpruefung wie bei Project.from_dict, ohne Projektvalidierung)."""
    errs: list[str] = []
    motor = _build(MotorSpec, data, "motor.", errs)
    if errs:
        raise ConfigError(errs)
    return motor


def schema() -> dict[str, Any]:
    """Beschreibung aller Felder fuer die UI (JSON serialisierbar)."""
    return {
        "fields": [
            {
                "path": m.path, "label": m.label, "tip": m.tip, "kind": m.kind, "lo": m.lo, "hi": m.hi,
                "strict_lo": m.strict_lo, "options": [list(o) for o in m.options] if m.options else None,
                "group": m.group, "optional": m.optional,
            }
            for m in FIELD_META
        ]
    }
