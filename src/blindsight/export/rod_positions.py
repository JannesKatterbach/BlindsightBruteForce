"""Rod positions per layer as JSON, the drilling pattern of every layer (G0 first, then G1 to Gn).

Coordinates are in mm with the origin (0, 0) at the bottom left corner of the build area, x to the
right and y up. Per layer the rods are split by when they reach into the layer
  always_present          in every position of the stroke (a hole is always occupied)
  present_when_retracted  only when the rod is retracted (lower layers)
  present_when_extended   only when the rod is extended
  present_during_travel   only between the end positions (rare, the rod is shorter than its travel)
Rods that never reach a layer are not listed for it.
"""

from __future__ import annotations

import json

from .base import PRESENCE_ALWAYS, PRESENCE_EXTENDED, PRESENCE_RETRACTED, PRESENCE_TRAVEL, rod_presence

FORMAT_ID = "blindsight.rod_positions"
FORMAT_VERSION = 1
DIGITS = 6
PRESENCE_KEYS = {
    PRESENCE_ALWAYS: "always_present",
    PRESENCE_RETRACTED: "present_when_retracted",
    PRESENCE_EXTENDED: "present_when_extended",
    PRESENCE_TRAVEL: "present_during_travel",
}


def rod_positions(geometry: dict) -> dict:
    """Rod positions per layer as a JSON compatible dictionary."""
    bounds = geometry["bounds"]
    x0, y0 = bounds["xmin"], bounds["ymin"]  # origin of the build area (0, 0)
    layers = []
    for plane in geometry["planes"]:
        layer = {"name": plane["name"], "index": plane["index"], "z_top": plane["z_top"], "z_bottom": plane["z_bottom"]}
        layer.update({key: [] for key in PRESENCE_KEYS.values()})
        for unit in geometry["units"]:
            presence = rod_presence(unit["rod"], plane)
            if presence is None:
                continue
            layer[PRESENCE_KEYS[presence]].append({
                "id": unit["id"], "x": round(unit["x"] - x0, DIGITS), "y": round(unit["y"] - y0, DIGITS),
                "motor_layer": f"G{unit['plane']}",
            })
        layers.append(layer)
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": geometry["name"],
        "units": {"length": "mm", "angle": "deg"},
        "origin": "bottom left corner of the build area, x to the right, y up, z = 0 at the top face of G0",
        "build_area": {"width": bounds["xmax"] - x0, "height": bounds["ymax"] - y0},
        "rod_diameter": geometry["rod_diameter"],
        "hole_diameter": geometry["hole_diameter"],
        "layers": layers,
    }


class RodPositionsExporter:
    name = "rods"
    extension = "json"
    filename = "blindsight-rods.json"
    mime = "application/json"
    label = "Schraubenpositionen (JSON)"

    def export(self, geometry: dict) -> str:
        return json.dumps(rod_positions(geometry), indent=2, ensure_ascii=False)
