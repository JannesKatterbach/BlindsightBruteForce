"""Understandable diagnosis of why a configuration yields no or too few solutions."""

from __future__ import annotations

from collections import Counter as Tally

from .i18n import tr
from .layout import Layout, Placement
from .model import Model

PROBE_GRID = 9  # probe points per axis across the usable build area


def single_unit_report(model: Model) -> list[str]:
    """Checks without optimisation. An empty list means a single unit is possible.

    If no layer is usable, its problems are reported. Otherwise a single unit is tried on a grid across
    the build area (minus the edge margin) with all layers, angles and centre distances. If everything
    fails, the report names the most frequent reason.
    """
    usable = model.usable_planes()
    if not usable:
        msgs = [tr("diagnose.plane_problem", plane=p.name, problem=problem)
                for p in model.stack.motor_planes for problem in model.plane_problems(p.index)]
        msgs.append(tr("diagnose.no_plane"))
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
        tr("diagnose.single_fails", reason=most_common),
        tr("diagnose.unit_size", radius=model.unit_radius, width=bounds.width, height=bounds.height),
    ]


def _probe_points(model: Model) -> list[tuple[float, float]]:
    """Uniform grid across the area of the rod holes (centre first)."""
    bounds = model.project.bounds
    margin = bounds.rod_margin
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
