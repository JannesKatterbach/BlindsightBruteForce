"""Bewertungsfunktion. Alle Teilziele liegen in [0, 1], 1 ist am besten.

Gesamtscore = gewichtetes Mittel (Gewichte aus WeightsSpec, normiert).
  count        platzierte Anzahl relativ zur Zielanzahl
  area         1 - genutzte Bounding Box / verfuegbarer Bauraum (Anteil freier Bauraum)
  uniformity   1 - 2 * Variationskoeffizient der Nachbarabstaende
  regularity   Ausrichtung der Nachbarn an ein Quadrat oder Hexagonalmuster
               (Bond Orientational Order Parameter psi4 und psi6)

Gleichmaessigkeit gilt fuer eine einzelne Einheit als erfuellt (1.0). Regelmaessigkeit braucht
mindestens 4 Nachbarn (psi4) und ist sonst 0, fuer jede Anzahl gleich. Frueher bekam eine einzelne
Einheit 1.0 und zwei bis vier Einheiten 0, das liess Ergebnisse sprunghaft kippen. Ein neutraler
Wert 1.0 haette dagegen kleine Anordnungen gegenueber vollstaendigen bevorzugt.

Erweitern. Ein neues Teilziel ist eine Funktion ``(LayoutStats) -> float`` in ``OBJECTIVES`` und
ein gleichnamiges Feld in ``config.WeightsSpec`` (plus FIELD_META Eintrag fuer die UI).
"""

from __future__ import annotations

import cmath
import math
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from .config import WeightsSpec
from .geometry import BBox, convex_hull, polygon_area
from .layout import Placement
from .model import KIND_ROD, Model
from .units import EPS, EPS_AREA

UNIFORMITY_CV_FACTOR = 2.0  # Variationskoeffizient 0.5 ergibt Gleichmaessigkeit 0
ORDER_NEIGHBORS = (4, 6)  # psi4 (Quadrat) und psi6 (Hexagon)


@dataclass
class Score:
    total: float
    terms: dict[str, float]
    weights: dict[str, float]
    metrics: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class LayoutStats:
    """Kennzahlen eines Layouts, aus denen die Teilziele berechnet werden."""

    count: int
    target: int
    bounds_area: float
    footprint: BBox
    footprint_area: float
    hull_area: float
    nn_distances: list[float]  # Abstand jeder Stange zur naechsten
    order: dict[int, Optional[float]]  # k -> mittleres psi_k oder None (zu wenige Nachbarn)

    @property
    def mean_nn(self) -> float:
        nn = self.nn_distances
        return sum(nn) / len(nn) if nn else 0.0

    @property
    def nn_cv(self) -> float:
        """Variationskoeffizient der Nachbarabstaende (0 bei weniger als zwei Abstaenden)."""
        nn = self.nn_distances
        if len(nn) < 2 or self.mean_nn <= 0:
            return 0.0
        var = sum((d - self.mean_nn) ** 2 for d in nn) / len(nn)
        return math.sqrt(var) / self.mean_nn


# ---------------------------------------------------------------------------
# Teilziele
# ---------------------------------------------------------------------------
def _count_term(s: LayoutStats) -> float:
    return min(1.0, s.count / max(1, s.target))


def _area_term(s: LayoutStats) -> float:
    return max(0.0, 1.0 - s.footprint_area / s.bounds_area)


def _uniformity_term(s: LayoutStats) -> float:
    if len(s.nn_distances) < 2:
        return 1.0
    return max(0.0, 1.0 - UNIFORMITY_CV_FACTOR * s.nn_cv)


def _regularity_term(s: LayoutStats) -> float:
    values = [v for v in s.order.values() if v is not None]
    return max(values) if values else 0.0


OBJECTIVES: dict[str, Callable[[LayoutStats], float]] = {
    "count": _count_term,
    "area": _area_term,
    "uniformity": _uniformity_term,
    "regularity": _regularity_term,
}


# ---------------------------------------------------------------------------
# Kennzahlen
# ---------------------------------------------------------------------------
def footprint_bbox(model: Model, placements: list[Placement]) -> BBox:
    """Bounding Box aller Bauteile aller Einheiten in der Draufsicht."""
    boxes = [model.unit_bbox(pl.x, pl.y, pl.plane, pl.angle, pl.cd) for pl in placements]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _hull_area(model: Model, placements: list[Placement]) -> float:
    """Flaeche der konvexen Huelle aller Gehaeuse und Zahnraeder (Stangen als Mittelpunkt)."""
    points = []
    for i, pl in enumerate(placements):
        for part in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            points.extend([(pl.x, pl.y)] if part.kind == KIND_ROD else part.prism.fp.outline())
    return polygon_area(convex_hull(points))


def _neighbor_stats(points: list[tuple[float, float]]) -> tuple[list[float], dict[int, Optional[float]]]:
    """Naechste Nachbarabstaende und mittlere Ordnungsparameter psi_k je k in ORDER_NEIGHBORS."""
    nn: list[float] = []
    psi: dict[int, list[float]] = {k: [] for k in ORDER_NEIGHBORS}
    for i, (px, py) in enumerate(points):
        neighbors = sorted((math.hypot(px - qx, py - qy), j) for j, (qx, qy) in enumerate(points) if j != i)
        if not neighbors:
            continue
        nn.append(neighbors[0][0])
        for k in ORDER_NEIGHBORS:
            if len(neighbors) < k:
                continue
            acc = sum(cmath.exp(1j * k * math.atan2(points[j][1] - py, points[j][0] - px)) for _, j in neighbors[:k])
            psi[k].append(abs(acc) / k)
    order = {k: (sum(v) / len(v) if v else None) for k, v in psi.items()}
    return nn, order


def layout_stats(model: Model, placements: list[Placement], target: int) -> LayoutStats:
    bounds = model.project.bounds
    box = footprint_bbox(model, placements)
    nn, order = _neighbor_stats([(pl.x, pl.y) for pl in placements])
    return LayoutStats(
        count=len(placements),
        target=target,
        bounds_area=bounds.width * bounds.height,
        footprint=box,
        footprint_area=max((box[2] - box[0]) * (box[3] - box[1]), EPS_AREA),
        hull_area=_hull_area(model, placements),
        nn_distances=nn,
        order=order,
    )


def normalized_weights(weights: WeightsSpec) -> dict[str, float]:
    raw = weights.as_dict()
    total = sum(raw.values())
    return {name: raw[name] / total for name in OBJECTIVES}


def evaluate(model: Model, placements: list[Placement], weights: WeightsSpec, target: int) -> Score:
    """Bewertet ein Layout. Rueckgabe mit Gesamtwert, Teilzielen, normierten Gewichten und Kennzahlen."""
    wn = normalized_weights(weights)
    if not placements:
        return Score(0.0, {k: 0.0 for k in OBJECTIVES}, wn, {"count": 0})
    stats = layout_stats(model, placements, target)
    terms = {name: fn(stats) for name, fn in OBJECTIVES.items()}
    total = sum(wn[k] * terms[k] for k in terms)
    return Score(total, terms, wn, _metrics(stats, placements))


def _metrics(stats: LayoutStats, placements: list[Placement]) -> dict[str, float]:
    x0, y0, x1, y1 = stats.footprint
    planes_used: dict[int, int] = {}
    for pl in placements:
        planes_used[pl.plane] = planes_used.get(pl.plane, 0) + 1
    return {
        "count": stats.count,
        "target": stats.target,
        "footprint_width": x1 - x0,
        "footprint_height": y1 - y0,
        "footprint_area": stats.footprint_area,
        "hull_area": stats.hull_area,
        "mean_nn_distance": stats.mean_nn,
        "nn_cv": stats.nn_cv,
        "psi4": stats.order[4] or 0.0,
        "psi6": stats.order[6] or 0.0,
        **{f"plane_{k}_units": v for k, v in sorted(planes_used.items())},
    }


def upper_bound_count(model: Model) -> int:
    """Strenge obere Schranke der Stangenzahl (Ungleichung von Oler).

    Je zwei Stangenachsen liegen mindestens d = Stangendurchmesser + Sicherheitsabstand auseinander
    (alle Stangen ueberlappen in der Hoehe). Die Achsen liegen im Rechteck der zulaessigen
    Mittelpunkte (Bauraum abzueglich Randabstand und Stangenradius) mit Flaeche A und Umfang P.
    Fuer Punkte mit Mindestabstand d in einem konvexen Bereich gilt
        N <= 2 / sqrt(3) * A / d^2 + P / (2 d) + 1
    Motoren werden ignoriert, die Schranke ist daher meist weit von der Realitaet entfernt.
    """
    bounds = model.project.bounds
    rod_d = model.project.rod.diameter
    d = rod_d + model.gap
    w = bounds.width - 2 * bounds.edge_margin - rod_d
    h = bounds.height - 2 * bounds.edge_margin - rod_d
    if w < -EPS or h < -EPS:
        return 0
    w, h = max(w, 0.0), max(h, 0.0)
    bound = 2.0 / math.sqrt(3.0) * (w * h) / d ** 2 + (2.0 * (w + h)) / (2.0 * d) + 1.0
    return int(math.floor(bound + 1e-9))
