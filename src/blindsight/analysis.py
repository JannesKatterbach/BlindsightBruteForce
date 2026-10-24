"""Abgeleitete Groessen einer Konfiguration ohne Optimierung (fuer UI und Skripte)."""

from __future__ import annotations

from .config import Project
from .model import Model


def analyze(project: Project) -> dict:
    """Ebenen mit Hoehen, Stangengeometrie und Problemen, dazu Einheitenradius und Sicherheitsabstand."""
    model = Model(project)
    planes = []
    for plane in model.stack.planes:
        entry = {
            "index": plane.index, "name": plane.name, "z_top": plane.z_top, "z_bottom": plane.z_bottom,
            "thickness": plane.thickness,
        }
        if plane.index > 0:
            entry["rod"] = model.rod_geometry(plane.index).as_dict()
            entry["problems"] = model.plane_problems(plane.index)
            entry["free_above"] = model.stack.free_height_above(plane.index)
        planes.append(entry)
    return {"planes": planes, "unit_radius": model.unit_radius, "required_gap": model.gap}
