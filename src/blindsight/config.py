"""Eingabedaten (Konfiguration) als Dataclasses mit schemagetriebener Validierung.

Alle Laengen in mm, Winkel in Grad. Die Konfiguration ist reines Datenmodell
und kennt weder Optimierer noch UI. Sie laesst sich als JSON laden und speichern.

FIELD_META beschreibt jedes Feld (Label, Hilfetext, Einheit, Grenzen, Auswahl).
Daraus entstehen Validierung, UI Formulare (/api/schema) und die Dokumentation.

Wichtig. Die Standardwerte sind Platzhalter fuer ein erstes Ausprobieren und
keine Herstellerdaten. Alle mechanisch relevanten Masse muessen mit den realen
Bauteilen ueberschrieben werden.
"""

from __future__ import annotations

import dataclasses
import json
import math
import typing
from dataclasses import dataclass, field
from typing import Any, Optional


class ConfigError(ValueError):
    """Ungueltige Konfiguration. errors enthaelt alle gefundenen Probleme."""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


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
    """Ein Constraint der Motor Skizze (siehe sketch.py)."""

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

    Lokales Koordinatensystem in der Draufsicht (Motorwinkel 0 Grad).
      Mit sketch gilt ein anderes System. Ursprung ist die Stangenachse, Zahnrad bei (-center_distance, 0),
      width, depth, shaft_x, gear_gap und outline werden dann ignoriert (siehe sketch.py).
      Gehaeuse ist um (0, 0) zentriert. Ohne outline ein Rechteck width mal depth,
      mit outline ein konvexes Polygon (dann sind width und depth nur noch die
      Bounding Box fuer die Anzeige und die Lage des Zahnrads).
      Die Abtriebsachse verlaeuft parallel zu y und tritt an der +y Seite aus.
      Sie liegt bei x = shaft_x (relativ zur Gehaeusemitte).
      Das Zahnrad sitzt axial gear_gap hinter der Gehaeusekante (depth/2), Breite gear_width.
      Die Gewindestange steht senkrecht, Abstand center_distance zur Abtriebsachse
      in +x Richtung, in y auf Hoehe der Zahnradmitte.
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
    sketch: Optional[SketchSpec] = None  # ersetzt Rechteck und outline, siehe sketch.py

    @property
    def gear_radius(self) -> float:
        return self.gear_diameter / 2.0

    @property
    def gear_center_y(self) -> float:
        # Das Zahnrad sitzt hinter der obersten Kante der Kontur (bei zentrierter Kontur ist das depth / 2)
        top = max(p[1] for p in self.outline) if self.outline else self.depth / 2.0
        return top + self.gear_gap + self.gear_width / 2.0

    def center_distances(self) -> list[float]:
        """Zulaessige Achsabstaende (nominal, wenn kein Bereich angegeben ist)."""
        lo = self.center_distance if self.center_distance_min is None else self.center_distance_min
        hi = self.center_distance if self.center_distance_max is None else self.center_distance_max
        n = max(1, self.center_distance_steps)
        if n == 1 or hi <= lo:
            return [self.center_distance]
        vals = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
        if not any(abs(v - self.center_distance) < 1e-9 for v in vals):
            vals.append(self.center_distance)
        return sorted(vals)

    def rod_local(self, cd: Optional[float] = None) -> tuple[float, float]:
        """Position der Gewindestange im lokalen Motorsystem."""
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


@dataclass
class BoundsSpec:
    """Zulaessiger Bauraum in der Draufsicht (Rechteck)."""

    xmin: float = 0.0
    ymin: float = 0.0
    xmax: float = 120.0
    ymax: float = 120.0
    edge_margin: float = 0.0
    parts_in_bounds: str = "all"

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin


@dataclass
class ObstacleSpec:
    """Festes Hindernis (Prisma). Ohne z0/z1 reicht es ueber alle Ebenen.

    Ist plane gesetzt, gilt es nur auf dieser Motorebene (Sperrzone, z.B. Loch oder Bauteil
    in der Platine), die Z Spanne ergibt sich dann aus der Ebene und der Motorhoehe.
    """

    shape: str = "rect"
    x: float = 0.0
    y: float = 0.0
    w: float = 10.0
    h: float = 10.0
    r: float = 5.0
    angle: float = 0.0
    z0: float = -1e6
    z1: float = 1e6
    plane: Optional[int] = None
    name: str = ""


@dataclass
class WeightsSpec:
    """Prioritaeten der Optimierungsziele (relative Gewichte, werden normiert)."""

    count: float = 10.0
    area: float = 8.0
    uniformity: float = 2.0
    regularity: float = 1.0


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
            raise ConfigError(f"Ungueltiges JSON. {exc}") from exc
        except RecursionError:
            raise ConfigError("JSON zu tief verschachtelt") from None

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())

    # -- Validierung -------------------------------------------------------
    def validate(self) -> None:
        errs: list[str] = []
        _validate_meta(self, errs)
        if errs:  # semantische Pruefungen setzen gueltige Einzelwerte voraus
            raise ConfigError(errs)
        self._validate_semantics(errs)
        if errs:
            raise ConfigError(errs)

    def _validate_semantics(self, errs: list[str]) -> None:
        r, m, s, b, se = self.rod, self.motor, self.stack, self.bounds, self.search
        n = s.n_motor_planes
        if m.axis_height > m.height:
            errs.append("motor.axis_height. Die Abtriebsachse liegt ausserhalb der Motorhoehe")
        if s.mode == "gaps":
            if len(s.gaps) < n:
                errs.append(f"stack.gaps. Modus 'gaps' braucht {n} Abstaende (G0-G1, G1-G2, ...)")
            elif any(g <= 0 for g in s.gaps[:n]):
                errs.append("stack.gaps. Alle Ebenenabstaende muessen positiv sein")
        elif s.mode == "distances":
            d = s.distances[:n]
            if len(d) < n:
                errs.append(f"stack.distances. Modus 'distances' braucht {n} Abstaende zu G0")
            elif any(x <= 0 for x in d) or any(d[i] >= d[i + 1] for i in range(len(d) - 1)):
                errs.append("stack.distances. Abstaende zu G0 muessen positiv und streng aufsteigend sein")
        if s.thicknesses is not None:
            if len(s.thicknesses) < n:
                errs.append(f"stack.thicknesses. {n} Dicken erwartet (eine je Motorebene)")
            elif any(t <= 0 for t in s.thicknesses):
                errs.append("stack.thicknesses. Alle Dicken muessen positiv sein")
        if s.mode == "uniform" and s.uniform_spacing <= 0:
            errs.append("stack.uniform_spacing. Muss groesser als 0 sein")
        if s.allowed_planes is not None:
            bad = [p for p in s.allowed_planes if not 1 <= p <= n]
            if bad:
                errs.append(f"stack.allowed_planes. Ebenen {bad} existieren nicht (1..{n})")
            if not s.allowed_planes:
                errs.append("stack.allowed_planes. Darf nicht leer sein (None = alle Ebenen)")
        for key, zones in s.mount_zones.items():
            _check_plane_key("stack.mount_zones", key, n, errs)
            for z in zones:
                if len(z) != 4 or z[2] <= z[0] or z[3] <= z[1]:
                    errs.append(f"stack.mount_zones[{key}]. Bereich muss [xmin, ymin, xmax, ymax] mit xmax>xmin, ymax>ymin sein")
        for key, cap in s.max_per_plane.items():
            _check_plane_key("stack.max_per_plane", key, n, errs)
            if cap < 0:
                errs.append(f"stack.max_per_plane[{key}]. Darf nicht negativ sein")
        for key, angs in s.plane_angles.items():
            _check_plane_key("stack.plane_angles", key, n, errs)
            if not angs:
                errs.append(f"stack.plane_angles[{key}]. Darf nicht leer sein")
        if b.xmax <= b.xmin or b.ymax <= b.ymin:
            errs.append("bounds. Bauraum hat keine positive Flaeche (xmax>xmin, ymax>ymin)")
        elif 2 * b.edge_margin >= min(b.width, b.height):
            errs.append("bounds.edge_margin. Randabstand ist groesser als der halbe Bauraum")
        for i, o in enumerate(self.obstacles):
            tag = f"obstacles[{i}]"
            if o.shape not in ("rect", "circle"):
                errs.append(f"{tag}.shape. Muss 'rect' oder 'circle' sein")
            if o.z1 < o.z0:
                errs.append(f"{tag}. z1 muss >= z0 sein")
            if o.shape == "rect" and (o.w <= 0 or o.h <= 0):
                errs.append(f"{tag}. Breite und Hoehe muessen positiv sein")
            if o.shape == "circle" and o.r <= 0:
                errs.append(f"{tag}.r. Radius muss positiv sein")
            if o.plane is not None and not 1 <= o.plane <= n:
                errs.append(f"{tag}.plane. Ebene {o.plane} existiert nicht (1..{n})")
        for p in se.patterns:
            if p not in ("square", "hex_x", "hex_y"):
                errs.append(f"search.patterns. Unbekanntes Muster '{p}' (square, hex_x, hex_y)")
        if not se.patterns:
            errs.append("search.patterns. Mindestens ein Muster ist noetig")
        if se.angle_max <= se.angle_min:
            errs.append("search.angle_max. Muss groesser als angle_min sein")
        if m.sketch is not None:
            from .sketch import check_sketch_motor

            _, serrs = check_sketch_motor(m)
            errs.extend(serrs)
        elif m.outline is not None:
            _check_outline(m.outline, errs)
        if m.center_distance_min is not None and m.center_distance_max is not None and m.center_distance_max < m.center_distance_min:
            errs.append("motor.center_distance_max. Muss >= center_distance_min sein")
        w = se.weights
        if w.count + w.area + w.uniformity + w.regularity <= 0:
            errs.append("search.weights. Nicht alle Gewichte duerfen 0 sein")
        if len(se.patterns) != len(set(se.patterns)):
            errs.append("search.patterns. Muster doppelt angegeben")
        try:
            self.allowed_angle_list()
        except ConfigError as exc:
            errs.extend(exc.errors)
        for key, angs in s.plane_angles.items():
            if any(not math.isfinite(a) for a in angs):
                errs.append(f"stack.plane_angles[{key}]. Winkel muessen endlich sein")

    def allowed_angle_list(self) -> list[float]:
        """Zulaessige Motorwinkel in Grad (aufsteigend, ohne Duplikate)."""
        se = self.search
        if se.allowed_angles is not None:
            angs = sorted({round(a % 360.0, 6) for a in se.allowed_angles})
        else:
            if se.angle_step <= 0:
                raise ConfigError("search.angle_step. Muss positiv sein")
            if (se.angle_max - se.angle_min) / se.angle_step > 100_000:
                raise ConfigError("search.angle_step. Zu klein, ergibt ueber 100000 Winkel")
            angs = []
            a = se.angle_min
            while a < se.angle_max - 1e-9:
                angs.append(round(a % 360.0, 6))
                a += se.angle_step
            angs = sorted(set(angs))
        if not angs:
            raise ConfigError("search.allowed_angles. Keine zulaessigen Motorwinkel")
        return angs

    def angles_for_plane(self, plane: int) -> list[float]:
        """Zulaessige Winkel einer Ebene (globale Liste, durch plane_angles ersetzt)."""
        own = self.stack.plane_angles.get(str(plane))
        if own:
            return sorted({round(a % 360.0, 6) for a in own})
        return self.allowed_angle_list()


def _check_plane_key(label: str, key: str, n: int, errs: list[str]) -> None:
    if not (key.isdigit() and 1 <= int(key) <= n):
        errs.append(f"{label}. Schluessel '{key}' ist keine Motorebene (1..{n})")


def _check_outline(outline: list[list[float]], errs: list[str]) -> None:
    if len(outline) < 3 or any(len(p) != 2 for p in outline):
        errs.append("motor.outline. Mindestens 3 Punkte [x, y] noetig")
        return
    pts = [(p[0], p[1]) for p in outline]
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    if abs(area) < 1e-9:
        errs.append("motor.outline. Kontur hat keine Flaeche")
        return
    sign = 1 if area > 0 else -1
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        cx, cy = pts[(i + 2) % len(pts)]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cr * sign < -1e-9:
            errs.append("motor.outline. Kontur muss konvex sein (nicht konvexe Motoren bitte als Huelle angeben)")
            return


# ---------------------------------------------------------------------------
# Feldbeschreibung. Quelle fuer Validierung, UI Formulare und Doku.
#   kind  len (mm, in der UI umrechenbar), num, int, text, enum, list, listint, liststr
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Meta:
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


_P = "project"
FIELD_META: list[Meta] = [
    Meta("name", "Name", "Bezeichnung des Projekts", "text", group="general"),
    Meta("target_count", "Gewuenschte Anzahl Stangen", "So viele Gewindestangen mit Motoren sollen platziert werden", "int", 1, 100000, group="general"),
    Meta("clearance", "Sicherheitsabstand", "Mindestabstand zwischen allen fremden Bauteilen", "len", 0, 1000, group="general"),
    Meta("tolerance", "Toleranz", "Wird zum Sicherheitsabstand addiert (Fertigung, Rundung). Wirksamer Abstand = Sicherheitsabstand + Toleranz", "len", 0, 1000, group="general"),
    Meta("rod.diameter", "Durchmesser", "Aussendurchmesser des Gewindes", "len", 0, 1000, True, group="rod"),
    Meta("rod.stroke", "Maximaler Hub ueber G0", "So weit muss jede Stange oberhalb von G0 ausfahren koennen, unabhaengig von der Motorebene", "len", 0, 100000, True, group="rod"),
    Meta("rod.engage_below", "Gewinde unter Zahnradachse (ausgefahren)", "Mindestgewinde unter der Zahnradachse bei maximalem Ausfahren", "len", 0, 100000, group="rod"),
    Meta("rod.engage_above", "Gewinde ueber Zahnradachse (eingefahren)", "Mindestgewinde ueber der Zahnradachse bei vollem Einfahren", "len", 0, 100000, group="rod"),
    Meta("rod.length_tolerance", "Laengenzuschlag", "Zusaetzlicher Sicherheitszuschlag der Stangenlaenge", "len", 0, 100000, group="rod"),
    Meta("rod.retract_depth", "Spitze eingefahren unter G0", "Tiefe der Stangenspitze unter G0 bei vollem Einfahren (0 = buendig)", "len", 0, 100000, group="rod"),
    Meta("rod.hole_clearance", "Radiales Lochspiel", "Spiel der Durchgangsloecher in den Ebenen (je Seite)", "len", 0, 1000, group="rod"),
    Meta("motor.width", "Breite (x)", "Gehaeusebreite quer zur Welle", "len", 0, 10000, True, group="motor"),
    Meta("motor.depth", "Tiefe (y, Wellenrichtung)", "Gehaeusetiefe entlang der Welle", "len", 0, 10000, True, group="motor"),
    Meta("motor.height", "Hoehe (z)", "Gehaeusehoehe senkrecht zur Ebene", "len", 0, 10000, True, group="motor"),
    Meta("motor.shaft_x", "Abtriebsachse, x Versatz", "Seitlicher Versatz der Abtriebsachse zur Gehaeusemitte", "len", -10000, 10000, group="motor"),
    Meta("motor.axis_height", "Achshoehe ueber Montageflaeche", "Hoehe der Abtriebsachse ueber der Montageflaeche", "len", 0, 10000, group="motor"),
    Meta("motor.gear_diameter", "Zahnrad Durchmesser", "Aussendurchmesser des Antriebszahnrads", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_width", "Zahnrad Breite", "Axiale Breite des Zahnrads", "len", 0, 10000, True, group="motor"),
    Meta("motor.gear_gap", "Abstand Gehaeuse zu Zahnrad", "Axialer Abstand zwischen Gehaeusekante und Zahnrad", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance", "Achsabstand Zahnrad zu Stange", "Abstand der Abtriebsachse zur Stangenachse. Der Eingriff ist nur ueber diesen Abstand modelliert", "len", 0, 10000, group="motor"),
    Meta("motor.center_distance_min", "Achsabstand min (optional)", "Untergrenze, wenn der Optimierer den Achsabstand variieren darf", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_max", "Achsabstand max (optional)", "Obergrenze, wenn der Optimierer den Achsabstand variieren darf", "len", 0, 10000, group="motor", optional=True),
    Meta("motor.center_distance_steps", "Achsabstand Stufen", "Anzahl der Stufen zwischen min und max (1 = nur nominal)", "int", 1, 50, group="motor"),
    Meta("motor.own_clearance", "Eigenabstand Gehaeuse zur Stange", "Mindestabstand des Gehaeuses zur eigenen Stange", "len", 0, 1000, group="motor"),
    Meta("motor.mount", "Montage", "Motor steht auf der Ebene oder haengt darunter", "enum", group="motor",
         options=(("top", "Motor steht auf der Ebene"), ("bottom", "Motor haengt unter der Ebene"))),
    Meta("stack.n_motor_planes", "Anzahl Motorebenen", "Anzahl der Ebenen G1 bis Gn, keine feste Obergrenze", "int", 1, 1000, group="stack"),
    Meta("stack.mode", "Abstandsmodus", "Wie die Ebenenhoehen angegeben werden", "enum", group="stack",
         options=(("uniform", "Einheitlicher Abstand"), ("gaps", "Einzelabstaende G(i) zu G(i+1)"), ("distances", "Abstand jeder Ebene zu G0"))),
    Meta("stack.uniform_spacing", "Einheitlicher Ebenenabstand", "Abstand zwischen allen Ebenen (Modus uniform)", "len", 0, 100000, True, group="stack"),
    Meta("stack.gaps", "Einzelabstaende (Liste)", "Abstaende G0-G1, G1-G2, ... (Modus gaps)", "list", group="stack"),
    Meta("stack.distances", "Abstaende zu G0 (Liste)", "Abstand jeder Motorebene zu G0, aufsteigend (Modus distances)", "list", group="stack"),
    Meta("stack.thickness", "Dicke Motorebenen", "Plattendicke der Ebenen G1 bis Gn", "len", 0, 1000, True, group="stack"),
    Meta("stack.g0_thickness", "Dicke G0", "Plattendicke der oberen Referenzebene", "len", 0, 1000, True, group="stack"),
    Meta("stack.thicknesses", "Dicke je Ebene (Liste, optional)", "Eigene Dicke fuer jede Motorebene, ueberschreibt die gemeinsame Dicke", "list", group="stack", optional=True),
    Meta("stack.allowed_planes", "Erlaubte Motorebenen (Liste, leer = alle)", "Nur diese Ebenen duerfen Motoren tragen", "listint", group="stack", optional=True),
    Meta("bounds.xmin", "x min", "Bauraum, linke Grenze", "len", -1e6, 1e6, group="bounds"),
    Meta("bounds.xmax", "x max", "Bauraum, rechte Grenze", "len", -1e6, 1e6, group="bounds"),
    Meta("bounds.ymin", "y min", "Bauraum, untere Grenze", "len", -1e6, 1e6, group="bounds"),
    Meta("bounds.ymax", "y max", "Bauraum, obere Grenze", "len", -1e6, 1e6, group="bounds"),
    Meta("bounds.edge_margin", "Randabstand", "Zusaetzlicher Abstand aller Bauteile zum Rand", "len", 0, 1e6, group="bounds"),
    Meta("bounds.parts_in_bounds", "Im Bauraum muessen liegen", "Alle Bauteile oder nur die Stangen", "enum", group="bounds",
         options=(("all", "alle Bauteile"), ("rods", "nur Stangen"))),
    Meta("search.optimizer", "Optimierer", "Suchstrategie", "enum", group="search",
         options=(("pattern_greedy", "Muster und lokale Suche"), ("anneal_free", "Freie Verteilung (Annealing)"), ("exhaustive_small", "Exakt auf Raster (kleine Aufgaben)"))),
    Meta("search.layout_goal", "Anordnungsziel", "compact packt dicht (kleine Flaeche), spread verteilt gleichmaessig ueber den ganzen Bauraum", "enum", group="search",
         options=(("compact", "Kompakt (kleine Grundflaeche)"), ("spread", "Verteilt ueber den Bauraum"))),
    Meta("search.patterns", "Muster (square, hex_x, hex_y)", "Verteilungsstruktur der Kandidaten", "liststr", group="search"),
    Meta("search.fixed_pitch", "Feste Teilung (optional)", "Nur diese Rasterteilung verwenden statt sie zu suchen", "len", 0, 100000, True, group="search", optional=True),
    Meta("search.angle_step", "Winkelschritt (Grad)", "Raster der zulaessigen Motorwinkel", "num", 0, 360, True, group="search"),
    Meta("search.angle_min", "Winkel von (Grad)", "Kleinster Motorwinkel", "num", -3600, 3600, group="search"),
    Meta("search.angle_max", "Winkel bis (Grad, exklusiv)", "360 = voller Kreis", "num", -3600, 3600, group="search"),
    Meta("search.allowed_angles", "Nur diese Winkel (Liste, leer = Raster)", "Explizite Liste erlaubter Motorwinkel", "list", group="search", optional=True),
    Meta("search.time_limit_s", "Zeitlimit (s)", "Maximale Rechenzeit", "num", 0, 86400, True, group="search"),
    Meta("search.max_candidates", "Max. Kandidaten", "Maximale Anzahl geprueften Platzierungen", "int", 1, 10**12, group="search"),
    Meta("search.seed", "Seed", "Zufallsstartwert fuer reproduzierbare Laeufe", "int", 0, 2**31 - 1, group="search"),
    Meta("search.top_k", "Anzahl Loesungen", "Wie viele beste Loesungen behalten werden", "int", 1, 50, group="search"),
    Meta("search.refine_fraction", "Anteil lokale Suche", "Zeitanteil der Verfeinerung (0 bis 0.9)", "num", 0, 0.9, group="search"),
    Meta("search.stagnation_s", "Stagnation (s, optional)", "Beenden, wenn das Ziel erreicht ist und sich so lange nichts verbessert", "num", 0, 86400, True, group="search", optional=True),
    Meta("search.workers", "Parallele Laeufe", "Anzahl Prozesse fuer unabhaengige Seeds (1 = ohne Parallelisierung)", "int", 1, 64, group="search"),
    Meta("search.weights.count", "Anzahl Stangen", "Gewicht des Ziels Anzahl", "num", 0, 1000, group="weights"),
    Meta("search.weights.area", "Kleine Grundflaeche", "Gewicht des Ziels Grundflaeche", "num", 0, 1000, group="weights"),
    Meta("search.weights.uniformity", "Gleichmaessige Verteilung", "Gewicht der gleichmaessigen Nachbarabstaende", "num", 0, 1000, group="weights"),
    Meta("search.weights.regularity", "Regelmaessiges Muster", "Gewicht der Quadrat oder Hexagonalordnung", "num", 0, 1000, group="weights"),
]
META_BY_PATH = {m.path: m for m in FIELD_META}


def _get(obj: Any, path: str) -> Any:
    for k in path.split("."):
        obj = getattr(obj, k)
    return obj


def _validate_meta(proj: Project, errs: list[str]) -> None:
    for m in FIELD_META:
        v = _get(proj, m.path)
        if v is None:
            if not m.optional:
                errs.append(f"{m.path}. Wert fehlt")
            continue
        if m.kind in ("len", "num", "int"):
            if not _isnum(v):
                errs.append(f"{m.path}. Muss eine endliche Zahl sein")
                continue
            if m.lo is not None and ((v <= m.lo) if m.strict_lo else (v < m.lo)):
                errs.append(f"{m.path}. Muss {'groesser als' if m.strict_lo else 'mindestens'} {m.lo:g} sein (ist {v:g})")
            if m.hi is not None and v > m.hi:
                errs.append(f"{m.path}. Darf hoechstens {m.hi:g} sein (ist {v:g})")
        elif m.kind == "enum":
            if v not in [o[0] for o in (m.options or ())]:
                errs.append(f"{m.path}. Unzulaessiger Wert '{v}'. Erlaubt. {[o[0] for o in m.options]}")
        elif m.kind in ("list", "listint"):
            if not all(_isnum(x) for x in v):
                errs.append(f"{m.path}. Alle Eintraege muessen endliche Zahlen sein")
    # Felder ohne Meta (Obstacles, Zonen)
    for i, o in enumerate(proj.obstacles):
        for name in ("x", "y", "w", "h", "r", "angle", "z0", "z1"):
            if not _isnum(getattr(o, name)):
                errs.append(f"obstacles[{i}].{name}. Muss eine endliche Zahl sein")
    for key, zones in proj.stack.mount_zones.items():
        for z in zones:
            if not all(_isnum(c) for c in z):
                errs.append(f"stack.mount_zones[{key}]. Koordinaten muessen endliche Zahlen sein")
    if proj.motor.outline is not None:
        if not all(_isnum(c) for p in proj.motor.outline for c in p):
            errs.append("motor.outline. Koordinaten muessen endliche Zahlen sein")


def _isnum(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------------------------------------------------------------------------
# Typgetriebenes Einlesen. Prueft Typen, wandelt ganzzahlige Floats in int um.
# ---------------------------------------------------------------------------
def _build(cls, data: Any, path: str, errs: list[str]):
    if not isinstance(data, dict):
        errs.append(f"{path or cls.__name__}. Objekt erwartet")
        return cls()
    hints = typing.get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    for key in sorted(set(data) - names):
        errs.append(f"{path + key}. Unbekanntes Feld in {cls.__name__}")
    kwargs: dict[str, Any] = {}
    for key, val in data.items():
        if key not in names:
            continue
        kwargs[key] = _coerce(val, hints[key], f"{path}{key}", errs)
    default = cls()
    for key, val in kwargs.items():
        if val is _BAD:
            kwargs[key] = getattr(default, key)
    return cls(**kwargs)


_BAD = object()


def _coerce(val: Any, hint: Any, path: str, errs: list[str]):
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is typing.Union:  # Optional[X]
        if val is None:
            return None
        inner = [a for a in args if a is not type(None)][0]
        return _coerce(val, inner, path, errs)
    if dataclasses.is_dataclass(hint):
        return _build(hint, val, path + ".", errs)
    if hint is float:
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
            errs.append(f"{path}. Muss eine endliche Zahl sein")
            return _BAD
        return float(val)
    if hint is int:
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or int(val) != val:
            errs.append(f"{path}. Muss eine ganze Zahl sein")
            return _BAD
        return int(val)
    if hint is str:
        if not isinstance(val, str):
            errs.append(f"{path}. Muss Text sein")
            return _BAD
        return val
    if origin is list:
        if not isinstance(val, list):
            errs.append(f"{path}. Liste erwartet")
            return _BAD
        out = [_coerce(v, args[0], f"{path}[{i}]", errs) for i, v in enumerate(val)]
        return [v for v in out if v is not _BAD] if _BAD in out else out
    if origin is dict:
        if not isinstance(val, dict):
            errs.append(f"{path}. Objekt erwartet")
            return _BAD
        return {str(k): _coerce(v, args[1], f"{path}[{k}]", errs) for k, v in val.items()}
    return val


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
