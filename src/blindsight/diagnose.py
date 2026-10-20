"""Verstaendliche Diagnose, warum eine Konfiguration keine oder zu wenige Loesungen liefert."""

from __future__ import annotations

from .layout import Layout, Placement
from .model import Model


def single_unit_report(model: Model) -> list[str]:
    """Pruefungen ohne Optimierung. Leere Liste heisst, eine Einzeleinheit ist moeglich."""
    msgs: list[str] = []
    usable = model.usable_planes()
    if not usable:
        for p in model.stack.motor_planes:
            for prob in model.plane_problems(p.index):
                msgs.append(f"{p.name}. {prob}")
        msgs.append("Keine Motorebene ist nutzbar. Ebenenabstand erhoehen, Motor niedriger waehlen oder Montage aendern")
        return msgs
    b = model.project.bounds
    lay = Layout(model)
    reasons: dict[str, int] = {}
    n = 9  # Probe auf einem Gitter ueber den gesamten Bauraum
    for i in range(n):
        for j in range(n):
            x = b.xmin + (b.xmax - b.xmin) * i / (n - 1)
            y = b.ymin + (b.ymax - b.ymin) * j / (n - 1)
            for plane in usable:
                for ang in model.angles_for(plane):
                    res = lay.check(Placement(x, y, plane, ang))
                    if res.ok:
                        return []
                    reasons[res.reason] = reasons.get(res.reason, 0) + 1
    top = max(reasons.items(), key=lambda kv: kv[1])[0]
    msgs.append(f"Selbst eine einzelne Einheit passt nicht in den Bauraum. Haeufigster Grund. {top}")
    r = model.unit_radius
    msgs.append(f"Die Einheit reicht bis {r:.1f} mm von der Stangenachse. Bauraum {b.width:.0f} mal {b.height:.0f} mm")
    return msgs
