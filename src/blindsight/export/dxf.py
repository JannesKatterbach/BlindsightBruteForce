"""DXF export (ASCII, format R12, unit mm, Y up, origin (0, 0) at the bottom left of the build area).

Layers
  BOUNDS            board outline (build area)
  EDGE_MARGIN       keep out strip of all parts, HOLE_AREA area of the holes with the edge strip (on request)
  OBSTACLES         fixed obstacles
  TOP_RODS          rods (circles) in top view, Gn_RODS with one chosen layer
  Gn_MOTOR          housing outlines of the motors on layer n
  Gn_GEAR           gear outlines on layer n
  Gn_HOLES          through holes of layer n (including G0 as G0_HOLES)
  LABELS            numbers of the units (on request)

With one chosen layer only its holes, rods passing through it and its motors are written. For a board
outline in KiCad choose layer G0 with outline and holes and import the file onto Edge.Cuts.
"""

from __future__ import annotations

from typing import Optional

from .base import ExportOptions, chosen_contents, holes_by_plane, margin_rects, obstacles_of_layer, rod_passes

LABEL_HEIGHT = 2.0  # mm


class DxfExporter:
    name = "dxf"  # key in EXPORTERS and in the API
    extension = "dxf"
    filename = "blindsight.dxf"
    mime = "application/dxf"
    layer_choice = True
    contents = ("outline", "margins", "holes", "rods", "housings", "gears", "obstacles", "labels")
    default_contents = ("outline", "holes", "rods", "housings", "gears", "obstacles")

    def export(self, geometry: dict, options: Optional[ExportOptions] = None) -> str:
        options = options or ExportOptions()
        show = chosen_contents(self, options)
        layer = options.layer
        ents: list[str] = []
        layers: set[str] = set()

        def add(name: str, text: str) -> None:
            layers.add(name)
            ents.append(text)

        b = geometry["bounds"]
        if "outline" in show:
            add("BOUNDS", self._rect("BOUNDS", b["xmin"], b["ymin"], b["xmax"], b["ymax"]))
        if "margins" in show:
            for kind, m in margin_rects(b):
                name = kind.replace("-", "_").upper()
                add(name, self._rect(name, b["xmin"] + m, b["ymin"] + m, b["xmax"] - m, b["ymax"] - m))
        if "obstacles" in show:
            for o in obstacles_of_layer(geometry, layer):
                add("OBSTACLES", self._poly("OBSTACLES", o["outline"]))
        rods = "TOP_RODS" if layer is None else f"G{layer}_RODS"
        for u in geometry["units"]:
            n = u["plane"]
            if "rods" in show and (layer is None or rod_passes(geometry, u, layer)):
                add(rods, self._circle(rods, u["x"], u["y"], geometry["rod_diameter"] / 2))
            if not options.on_layer(n):
                continue
            for p in u["parts"]:
                if p["kind"] == "housing" and "housings" in show:
                    add(f"G{n}_MOTOR", self._poly(f"G{n}_MOTOR", p["outline"]))
                elif p["kind"] == "gear" and "gears" in show:
                    add(f"G{n}_GEAR", self._poly(f"G{n}_GEAR", p["outline"]))
        if "holes" in show:
            for idx, holes in holes_by_plane(geometry, layer).items():
                for h in holes:
                    add(f"G{idx}_HOLES", self._circle(f"G{idx}_HOLES", h["x"], h["y"], h["d"] / 2))
        if "labels" in show:
            r = geometry["hole_diameter"] / 2
            for u in geometry["units"]:
                if layer is None or rod_passes(geometry, u, layer):
                    add("LABELS", self._text("LABELS", u["x"] + r + 0.5, u["y"] + r + 0.3, str(u["id"])))
        out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
               "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(len(layers))]
        for name in sorted(layers):
            out += ["0", "LAYER", "2", name, "70", "0", "62", "7", "6", "CONTINUOUS"]
        out += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
        out += ents
        out += ["0", "ENDSEC", "0", "EOF"]
        return "\n".join(x for chunk in out for x in chunk.split("\n")) + "\n"

    @classmethod
    def _rect(cls, layer: str, x0: float, y0: float, x1: float, y1: float) -> str:
        return cls._poly(layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    @staticmethod
    def _poly(layer: str, pts) -> str:
        rows = ["0", "POLYLINE", "8", layer, "66", "1", "70", "1"]
        for x, y in pts:
            rows += ["0", "VERTEX", "8", layer, "10", f"{x:.6f}", "20", f"{y:.6f}", "30", "0.0"]
        rows += ["0", "SEQEND", "8", layer]
        return "\n".join(rows)

    @staticmethod
    def _circle(layer: str, x: float, y: float, r: float) -> str:
        return "\n".join(["0", "CIRCLE", "8", layer, "10", f"{x:.6f}", "20", f"{y:.6f}", "30", "0.0", "40", f"{r:.6f}"])

    @staticmethod
    def _text(layer: str, x: float, y: float, text: str) -> str:
        return "\n".join(["0", "TEXT", "8", layer, "10", f"{x:.6f}", "20", f"{y:.6f}", "30", "0.0",
                          "40", f"{LABEL_HEIGHT:.6f}", "1", text])
