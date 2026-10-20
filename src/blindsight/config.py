"""Eingabedaten (Konfiguration) als Dataclasses mit Validierung.

Alle Laengen in mm, Winkel in Grad. Die Konfiguration ist reines Datenmodell
und kennt weder Optimierer noch UI. Sie laesst sich als JSON laden und speichern.

Wichtig. Die Standardwerte sind Platzhalter fuer ein erstes Ausprobieren und
keine Herstellerdaten. Alle mechanisch relevanten Masse muessen mit den realen
Bauteilen ueberschrieben werden.
"""

from __future__ import annotations

import dataclasses
import json
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

    diameter: float = 4.0  # Aussendurchmesser des Gewindes
    stroke: float = 50.0  # maximaler Hub oberhalb von G0
    engage_below: float = 10.0  # Mindestgewinde unter der Zahnradachse bei maximalem Ausfahren
    engage_above: float = 10.0  # Mindestgewinde ueber der Zahnradachse bei vollem Einfahren
    length_tolerance: float = 2.0  # zusaetzlicher Sicherheitszuschlag der Laenge
    retract_depth: float = 0.0  # Spitze liegt eingefahren so tief unter G0 (0 = buendig)
    hole_clearance: float = 0.5  # radiales Spiel der Durchgangsloecher in den Ebenen


@dataclass
class MotorSpec:
    """Motor mit seitlichem Antriebszahnrad, vereinfacht als Quader plus Zahnradquader.

    Lokales Koordinatensystem in der Draufsicht (Motorwinkel 0 Grad).
      Gehaeuse ist um (0, 0) zentriert, width entlang x, depth entlang y.
      Die Abtriebsachse verlaeuft parallel zu y und tritt an der +y Seite aus.
      Sie liegt bei x = shaft_x (relativ zur Gehaeusemitte).
      Das Zahnrad sitzt axial gear_gap hinter der Gehaeusekante, Breite gear_width.
      Die Gewindestange steht senkrecht, Abstand center_distance zur Abtriebsachse
      in +x Richtung, in y auf Hoehe der Zahnradmitte.
    """

    width: float = 12.0
    depth: float = 24.0
    height: float = 10.0
    shaft_x: float = 0.0
    axis_height: float = 5.0  # Hoehe der Abtriebsachse ueber der Montageflaeche
    gear_diameter: float = 6.0
    gear_width: float = 4.0
    gear_gap: float = 1.0  # axialer Abstand Gehaeuse zu Zahnrad
    center_distance: float = 5.0  # Abstand Abtriebsachse zu Gewindestangenachse
    own_clearance: float = 0.2  # Mindestabstand Gehaeuse zur eigenen Stange
    mount: str = "top"  # "top" Motor steht auf der Ebene, "bottom" haengt darunter

    @property
    def gear_radius(self) -> float:
        return self.gear_diameter / 2.0

    @property
    def gear_center_y(self) -> float:
        return self.depth / 2.0 + self.gear_gap + self.gear_width / 2.0

    @property
    def rod_local(self) -> tuple[float, float]:
        """Position der Gewindestange im lokalen Motorsystem."""
        return (self.shaft_x + self.center_distance, self.gear_center_y)


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
    thickness: float = 1.6  # Dicke der Motorebenen
    g0_thickness: float = 6.0  # Dicke von G0 (z.B. Holzplatte)
    allowed_planes: Optional[list[int]] = None  # erlaubte Motorebenen (1..n), None = alle
    mount_zones: dict[str, list[list[float]]] = field(default_factory=dict)  # "1": [[xmin,ymin,xmax,ymax],..]


@dataclass
class BoundsSpec:
    """Zulaessiger Bauraum in der Draufsicht (Rechteck)."""

    xmin: float = 0.0
    ymin: float = 0.0
    xmax: float = 120.0
    ymax: float = 120.0
    edge_margin: float = 0.0  # zusaetzlicher Randabstand fuer alle Bauteile
    parts_in_bounds: str = "all"  # "all" alle Bauteile, "rods" nur die Stangen

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin


@dataclass
class ObstacleSpec:
    """Festes Hindernis (Prisma). Ohne z0/z1 reicht es ueber alle Ebenen."""

    shape: str = "rect"  # "rect" oder "circle"
    x: float = 0.0
    y: float = 0.0
    w: float = 10.0
    h: float = 10.0
    r: float = 5.0
    angle: float = 0.0
    z0: float = -1e6
    z1: float = 1e6
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
    patterns: list[str] = field(default_factory=lambda: ["square", "hex_x", "hex_y"])
    angle_step: float = 15.0
    angle_min: float = 0.0
    angle_max: float = 360.0  # exklusiv, 360 = voller Kreis
    allowed_angles: Optional[list[float]] = None
    time_limit_s: float = 20.0
    max_candidates: int = 2_000_000
    seed: int = 1
    top_k: int = 5
    refine_fraction: float = 0.35  # Zeitanteil der lokalen Verfeinerung


@dataclass
class Project:
    name: str = "Unbenannt"
    target_count: int = 12
    clearance: float = 1.0  # Sicherheitsabstand zwischen Bauteilen
    tolerance: float = 0.05  # Fertigungs/Rechentoleranz, wird zum Abstand addiert
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
        proj = _build(cls, data)
        proj.validate()
        return proj

    @classmethod
    def from_json(cls, text: str) -> "Project":
        try:
            return cls.from_dict(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Ungueltiges JSON. {exc}") from exc

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())

    # -- Validierung -------------------------------------------------------
    def validate(self) -> None:
        errs: list[str] = []

        def pos(label: str, v: float, strict: bool = True):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(f"{label} muss eine Zahl sein")
            elif (v <= 0) if strict else (v < 0):
                errs.append(f"{label} muss {'groesser als' if strict else 'mindestens'} 0 sein (ist {v})")

        r, m, s, b, se = self.rod, self.motor, self.stack, self.bounds, self.search
        for label, v in (
            ("Stangendurchmesser", r.diameter),
            ("Hub", r.stroke),
            ("Motorbreite", m.width),
            ("Motortiefe", m.depth),
            ("Motorhoehe", m.height),
            ("Zahnraddurchmesser", m.gear_diameter),
            ("Zahnradbreite", m.gear_width),
            ("Ebenendicke", s.thickness),
            ("Dicke G0", s.g0_thickness),
        ):
            pos(label, v)
        for label, v in (
            ("Mindestgewinde unten", r.engage_below),
            ("Mindestgewinde oben", r.engage_above),
            ("Laengenzuschlag", r.length_tolerance),
            ("Einfahrtiefe", r.retract_depth),
            ("Lochspiel", r.hole_clearance),
            ("Zahnradabstand", m.gear_gap),
            ("Achsabstand", m.center_distance),
            ("Achshoehe", m.axis_height),
            ("Eigenabstand", m.own_clearance),
            ("Sicherheitsabstand", self.clearance),
            ("Toleranz", self.tolerance),
            ("Randabstand", b.edge_margin),
        ):
            pos(label, v, strict=False)
        if m.mount not in ("top", "bottom"):
            errs.append("Motormontage muss 'top' oder 'bottom' sein")
        if m.axis_height > m.height and not errs:
            errs.append("Die Abtriebsachse liegt ausserhalb der Motorhoehe")
        if self.target_count < 1:
            errs.append("Gewuenschte Anzahl muss mindestens 1 sein")
        if s.n_motor_planes < 1:
            errs.append("Es wird mindestens eine Motorebene benoetigt")
        if s.mode not in ("uniform", "gaps", "distances"):
            errs.append("Ebenenmodus muss 'uniform', 'gaps' oder 'distances' sein")
        elif s.mode == "uniform":
            pos("Ebenenabstand", s.uniform_spacing)
        elif s.mode == "gaps":
            if len(s.gaps) < s.n_motor_planes:
                errs.append(f"Modus 'gaps' braucht {s.n_motor_planes} Abstaende (G0-G1, G1-G2, ...)")
            elif any(g <= 0 for g in s.gaps[: s.n_motor_planes]):
                errs.append("Alle Ebenenabstaende muessen positiv sein")
        elif s.mode == "distances":
            d = s.distances[: s.n_motor_planes]
            if len(d) < s.n_motor_planes:
                errs.append(f"Modus 'distances' braucht {s.n_motor_planes} Abstaende zu G0")
            elif any(x <= 0 for x in d) or any(d[i] >= d[i + 1] for i in range(len(d) - 1)):
                errs.append("Abstaende zu G0 muessen positiv und streng aufsteigend sein")
        if s.allowed_planes is not None:
            bad = [p for p in s.allowed_planes if not 1 <= p <= s.n_motor_planes]
            if bad:
                errs.append(f"Erlaubte Motorebenen {bad} existieren nicht (1..{s.n_motor_planes})")
            if not s.allowed_planes:
                errs.append("Erlaubte Motorebenen duerfen nicht leer sein")
        if b.xmax <= b.xmin or b.ymax <= b.ymin:
            errs.append("Bauraum hat keine positive Flaeche (xmax>xmin, ymax>ymin)")
        if b.parts_in_bounds not in ("all", "rods"):
            errs.append("parts_in_bounds muss 'all' oder 'rods' sein")
        for i, o in enumerate(self.obstacles):
            if o.shape not in ("rect", "circle"):
                errs.append(f"Hindernis {i + 1}. Form muss 'rect' oder 'circle' sein")
            if o.z1 < o.z0:
                errs.append(f"Hindernis {i + 1}. z1 muss >= z0 sein")
        for p in se.patterns:
            if p not in ("square", "hex_x", "hex_y"):
                errs.append(f"Unbekanntes Muster '{p}' (square, hex_x, hex_y)")
        if not se.patterns:
            errs.append("Mindestens ein Muster ist noetig")
        if se.angle_step <= 0:
            errs.append("Winkelschritt muss positiv sein")
        if se.angle_max <= se.angle_min:
            errs.append("angle_max muss groesser als angle_min sein")
        if se.time_limit_s <= 0 or se.max_candidates < 1:
            errs.append("Zeit und Kandidatenlimit muessen positiv sein")
        w = se.weights
        if min(w.count, w.area, w.uniformity, w.regularity) < 0 or (
            w.count + w.area + w.uniformity + w.regularity <= 0
        ):
            errs.append("Gewichte duerfen nicht negativ sein und nicht alle 0")
        if errs:
            raise ConfigError(errs)

    def allowed_angle_list(self) -> list[float]:
        """Zulaessige Motorwinkel in Grad (aufsteigend, ohne Duplikate)."""
        se = self.search
        if se.allowed_angles is not None:
            angs = sorted({round(a % 360.0, 6) for a in se.allowed_angles})
        else:
            angs = []
            a = se.angle_min
            while a < se.angle_max - 1e-9:
                angs.append(round(a % 360.0, 6))
                a += se.angle_step
            angs = sorted(set(angs))
        if not angs:
            raise ConfigError("Keine zulaessigen Motorwinkel")
        return angs


def _build(cls, data: Any):
    """Baut rekursiv eine Dataclass aus einem dict. Unbekannte Schluessel sind Fehler."""
    if not isinstance(data, dict):
        raise ConfigError(f"Erwartet ein Objekt fuer {cls.__name__}")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = set(data) - set(fields)
    if unknown:
        raise ConfigError(f"Unbekannte Felder in {cls.__name__}. {sorted(unknown)}")
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for key, val in data.items():
        t = hints[key]
        if t is Project or (isinstance(t, type) and dataclasses.is_dataclass(t)):
            kwargs[key] = _build(t, val)
        elif key == "obstacles":
            kwargs[key] = [_build(ObstacleSpec, o) for o in val]
        else:
            kwargs[key] = val
    return cls(**kwargs)


def _hints(cls) -> dict[str, Any]:
    mapping = {
        Project: {
            "name": str,
            "target_count": int,
            "clearance": float,
            "tolerance": float,
            "rod": RodSpec,
            "motor": MotorSpec,
            "stack": StackSpec,
            "bounds": BoundsSpec,
            "obstacles": list,
            "search": SearchSpec,
        },
        SearchSpec: {f.name: (WeightsSpec if f.name == "weights" else object) for f in dataclasses.fields(SearchSpec)},
    }
    if cls in mapping:
        return mapping[cls]
    return {f.name: object for f in dataclasses.fields(cls)}
