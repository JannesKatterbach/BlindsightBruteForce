"""Derived values of a configuration without optimisation (for the UI and scripts)."""

from __future__ import annotations

from .config import Project
from .model import Model


def analyze(project: Project) -> dict:
    """Layers with heights, rod geometry and problems, unit radius, safety clearance and the motor outline."""
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
    motor = project.motor
    cd, r, h = motor.center_distance, motor.gear_radius, motor.gear_width / 2.0
    shape = {"housing": [list(p) for p in model.housing_nominal],
             "gear": [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]]}  # rod frame, nominal centre distance
    return {"planes": planes, "unit_radius": model.unit_radius, "required_gap": model.gap, "motor": shape}
