"""Bewertungsfunktion. Alle Teilziele liegen in [0, 1], 1 ist am besten.

Gesamtscore = gewichtetes Mittel (Gewichte aus WeightsSpec, normiert).
  count        platzierte Anzahl relativ zur Zielanzahl
  area         1 - genutzte Bounding Box / verfuegbarer Bauraum (Anteil freier Bauraum)
  uniformity   1 - 2 * Variationskoeffizient der Nachbarabstaende
  regularity   Ausrichtung der Nachbarn an ein Quadrat oder Hexagonalmuster
               (Bond Orientational Order Parameter psi4 und psi6)
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field

from .config import WeightsSpec
from .geometry import convex_hull, polygon_area
from .layout import Placement
from .model import Model


@dataclass
class Score:
    total: float
    terms: dict[str, float]
    weights: dict[str, float]
    metrics: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"total": self.total, "terms": self.terms, "weights": self.weights, "metrics": self.metrics}


def footprint_bbox(model: Model, placements: list[Placement]) -> tuple[float, float, float, float]:
    xs0, ys0, xs1, ys1 = math.inf, math.inf, -math.inf, -math.inf
    for i, pl in enumerate(placements):
        for p in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            if p.kind == "rod":
                b = p.prism.fp.bbox
                xs0, ys0, xs1, ys1 = min(xs0, b[0]), min(ys0, b[1]), max(xs1, b[2]), max(ys1, b[3])
            else:
                for x, y in p.prism.fp.pts:
                    xs0, ys0, xs1, ys1 = min(xs0, x), min(ys0, y), max(xs1, x), max(ys1, y)
    return xs0, ys0, xs1, ys1


def evaluate(model: Model, placements: list[Placement], weights: WeightsSpec, target: int) -> Score:
    n = len(placements)
    w = {"count": weights.count, "area": weights.area, "uniformity": weights.uniformity, "regularity": weights.regularity}
    wsum = sum(w.values())
    wn = {k: v / wsum for k, v in w.items()}
    if n == 0:
        return Score(0.0, {k: 0.0 for k in w}, wn, {"count": 0})

    bounds_area = model.project.bounds.width * model.project.bounds.height
    x0, y0, x1, y1 = footprint_bbox(model, placements)
    area = max((x1 - x0) * (y1 - y0), 1e-9)
    hull_pts = []
    for i, pl in enumerate(placements):
        for p in model.unit_parts(i, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            hull_pts.extend(p.prism.fp.outline() if p.kind != "rod" else [(pl.x, pl.y)])
    hull_area = polygon_area(convex_hull(hull_pts))

    pts = [(pl.x, pl.y) for pl in placements]
    nn: list[float] = []
    psi4: list[float] = []
    psi6: list[float] = []
    for i, (px, py) in enumerate(pts):
        ds = sorted((math.hypot(px - qx, py - qy), j) for j, (qx, qy) in enumerate(pts) if j != i)
        if not ds:
            continue
        nn.append(ds[0][0])
        for k, bucket in ((4, psi4), (6, psi6)):
            near = ds[:k]
            if len(near) < k:
                continue
            acc = sum(cmath.exp(1j * k * math.atan2(pts[j][1] - py, pts[j][0] - px)) for _, j in near)
            bucket.append(abs(acc) / k)

    if len(nn) >= 2:
        mean = sum(nn) / len(nn)
        var = sum((d - mean) ** 2 for d in nn) / len(nn)
        cv = math.sqrt(var) / mean if mean > 0 else 0.0
        uniformity = max(0.0, 1.0 - 2.0 * cv)
        reg4 = sum(psi4) / len(psi4) if psi4 else 0.0
        reg6 = sum(psi6) / len(psi6) if psi6 else 0.0
        regularity = max(reg4, reg6)
    else:
        mean, cv, uniformity, regularity, reg4, reg6 = (nn[0] if nn else 0.0), 0.0, 1.0, 1.0, 1.0, 1.0

    terms = {
        "count": min(1.0, n / max(1, target)),
        "area": max(0.0, 1.0 - area / bounds_area),
        "uniformity": uniformity,
        "regularity": regularity,
    }
    total = sum(wn[k] * terms[k] for k in terms)
    planes_used: dict[int, int] = {}
    for pl in placements:
        planes_used[pl.plane] = planes_used.get(pl.plane, 0) + 1
    metrics = {
        "count": n,
        "target": target,
        "footprint_width": x1 - x0,
        "footprint_height": y1 - y0,
        "footprint_area": area,
        "hull_area": hull_area,
        "mean_nn_distance": mean,
        "nn_cv": cv,
        "psi4": reg4,
        "psi6": reg6,
        **{f"plane_{k}_units": v for k, v in sorted(planes_used.items())},
    }
    return Score(total, terms, wn, metrics)


def upper_bound_count(model: Model) -> int:
    """Strenge obere Schranke der Stangenzahl aus Kreispackungsdichte.

    Kreise mit Durchmesser d_eff = Stangendurchmesser + Abstand dichter als hexagonal
    (Dichte pi/sqrt(12)) lassen sich nicht packen. Die Kreise liegen in dem um d_eff/2
    vergroesserten Bereich der Stangenmittelpunkte. Motoren werden hier ignoriert,
    die Schranke ist daher meist weit von der Realitaet entfernt.
    """
    b = model.project.bounds
    d = model.project.rod.diameter + model.gap
    w = b.width - 2 * b.edge_margin - model.project.rod.diameter
    h = b.height - 2 * b.edge_margin - model.project.rod.diameter
    if w < 0 or h < 0:
        return 0
    a_enl = w * h + 2 * (w + h) * d / 2.0 + math.pi * (d / 2.0) ** 2
    density = math.pi / math.sqrt(12.0)
    return int(math.floor(density * a_enl / (math.pi * (d / 2.0) ** 2) + 1e-9))
