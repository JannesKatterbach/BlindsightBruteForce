"""Exporter Protokoll und gemeinsame, formatunabhaengige Geometriedaten.

Alle Exporter (SVG, JSON, spaeter DXF oder CAD) arbeiten auf dem Dictionary aus
build_geometry und kennen weder Optimierer noch UI.
"""

from __future__ import annotations

from typing import Protocol

from ..layout import Placement, layout_from_placements
from ..model import Model


class Exporter(Protocol):
    extension: str  # Dateiendung und Name in der API (/api/export/<job>.<extension>)
    mime: str
    label: str  # Bezeichnung in der UI


    def export(self, geometry: dict) -> str: ...


def build_geometry(model: Model, placements: list[Placement]) -> dict:
    """Vollstaendige, serialisierbare Geometrie einer Anordnung (alle Masse in mm)."""
    proj = model.project
    lay = layout_from_placements(model, placements)
    units = []
    for uid in sorted(lay.units):
        pl = lay.units[uid]
        parts = []
        for p in lay.parts_of(uid):
            parts.append({
                "kind": p.kind,
                "z0": p.prism.z0,
                "z1": p.prism.z1,
                "shape": p.prism.fp.kind,
                "outline": [list(pt) for pt in p.prism.fp.outline()],
                **({"cx": p.prism.fp.cx, "cy": p.prism.fp.cy, "r": p.prism.fp.r} if p.prism.fp.kind == "c" else {}),
            })
        units.append({
            "id": uid,
            "x": pl.x,
            "y": pl.y,
            "plane": pl.plane,
            "angle": pl.angle,
            "cd": pl.cd,
            "rod": model.rod_geometry(pl.plane).as_dict(),
            "parts": parts,
        })
    obstacles = []
    for o in model.obstacles:
        obstacles.append({
            "label": o.label, "z0": o.prism.z0, "z1": o.prism.z1, "shape": o.prism.fp.kind,
            "outline": [list(pt) for pt in o.prism.fp.outline()],
        })
    b = proj.bounds
    return {
        "name": proj.name,
        "units_of_length": "mm",
        "bounds": {"xmin": b.xmin, "ymin": b.ymin, "xmax": b.xmax, "ymax": b.ymax, "edge_margin": b.edge_margin},
        "clearance": proj.clearance,
        "tolerance": proj.tolerance,
        "required_gap": model.gap,
        "rod_diameter": proj.rod.diameter,
        "hole_diameter": 2 * model.hole_r,
        "stroke": proj.rod.stroke,
        "planes": [
            {"index": p.index, "name": p.name, "z_top": p.z_top, "z_bottom": p.z_bottom, "thickness": p.thickness}
            for p in model.stack.planes
        ],
        "units": units,
        "obstacles": obstacles,
        "collisions": [c.as_dict() for c in lay.all_collisions()],
        "closest_pairs": lay.closest_pairs(12),
    }


def rod_passes(geometry: dict, unit: dict, plane_index: int) -> bool:
    """Durchquert die Stange der Einheit die Ebene (Durchgangsloch noetig)?"""
    pl = geometry["planes"][plane_index]
    rod = unit["rod"]
    return rod["bottom_retracted"] <= pl["z_top"] and rod["tip_extended"] >= pl["z_bottom"]


def holes_by_plane(geometry: dict) -> dict[int, list[dict]]:
    """Durchgangsloecher je Ebene (inklusive G0). Jede Stange braucht ein Loch in jeder Ebene, die sie durchquert."""
    out: dict[int, list[dict]] = {p["index"]: [] for p in geometry["planes"]}
    for u in geometry["units"]:
        for p in geometry["planes"]:
            if rod_passes(geometry, u, p["index"]):
                out[p["index"]].append({"unit": u["id"], "x": u["x"], "y": u["y"], "d": geometry["hole_diameter"]})
    return out
