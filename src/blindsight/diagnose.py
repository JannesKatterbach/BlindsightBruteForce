"""Verstaendliche Diagnose, warum eine Konfiguration keine oder zu wenige Loesungen liefert."""

from __future__ import annotations

from collections import Counter as Tally

from .layout import Layout, Placement
from .model import Model

PROBE_GRID = 9  # Probepunkte je Achse ueber den nutzbaren Bauraum


def single_unit_report(model: Model) -> list[str]:
    """Pruefungen ohne Optimierung. Leere Liste heisst, eine Einzeleinheit ist moeglich.

    Ist keine Ebene nutzbar, werden deren Probleme gemeldet. Sonst wird eine einzelne Einheit
    auf einem Gitter ueber den Bauraum (abzueglich Randabstand) mit allen Ebenen, Winkeln und
    Achsabstaenden probiert. Scheitert alles, nennt der Bericht den haeufigsten Grund.
    """
    usable = model.usable_planes()
    if not usable:
        msgs = [f"{p.name}. {problem}" for p in model.stack.motor_planes for problem in model.plane_problems(p.index)]
        msgs.append("Keine Motorebene ist nutzbar. Ebenenabstand erhöhen, Motor niedriger wählen oder Montage ändern")
        return msgs
    bounds = model.project.bounds
    layout = Layout(model)
    reasons: Tally[str] = Tally()
    for x, y in _probe_points(model):
        for plane in usable:
            for angle in model.angles_for(plane):
                for cd in model.center_distances:
                    result = layout.check(Placement(x, y, plane, angle, cd))
                    if result.ok:
                        return []
                    reasons[result.reason] += 1
    most_common = reasons.most_common(1)[0][0]
    return [
        f"Selbst eine einzelne Einheit passt nicht in den Bauraum. Häufigster Grund. {most_common}",
        f"Die Einheit reicht bis {model.unit_radius:.1f} mm von der Stangenachse. "
        f"Bauraum {bounds.width:.0f} mal {bounds.height:.0f} mm",
    ]


def _probe_points(model: Model) -> list[tuple[float, float]]:
    """Gleichmaessiges Gitter ueber den Bauraum abzueglich Randabstand (Mitte zuerst)."""
    bounds = model.project.bounds
    margin = bounds.edge_margin
    x0, x1 = bounds.xmin + margin, bounds.xmax - margin
    y0, y1 = bounds.ymin + margin, bounds.ymax - margin
    if x1 < x0:
        x0 = x1 = (bounds.xmin + bounds.xmax) / 2.0
    if y1 < y0:
        y0 = y1 = (bounds.ymin + bounds.ymax) / 2.0
    n = PROBE_GRID
    points = [
        (x0 + (x1 - x0) * i / (n - 1), y0 + (y1 - y0) * j / (n - 1)) for i in range(n) for j in range(n)
    ]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return sorted(points, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
