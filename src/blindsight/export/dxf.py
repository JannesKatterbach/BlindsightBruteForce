"""DXF Export (ASCII, Format R12, Einheit mm, Y nach oben, Ursprung wie in der Konfiguration).

Layer
  BOUNDS            Bauraum
  OBSTACLES         feste Hindernisse
  TOP_RODS          Stangen (Kreise) in der Draufsicht
  Gn_MOTOR          Gehaeusekonturen der Motoren auf Ebene n
  Gn_GEAR           Zahnradkonturen auf Ebene n
  Gn_HOLES          Durchgangsloecher der Ebene n (inklusive G0 als G0_HOLES)
"""

from __future__ import annotations

from .base import holes_by_plane


class DxfExporter:
    extension = "dxf"
    mime = "application/dxf"

    def export(self, geometry: dict) -> str:
        ents: list[tuple[str, str]] = []  # (Layer, Entitaetstext)
        layers: set[str] = {"BOUNDS", "OBSTACLES", "TOP_RODS"}
        b = geometry["bounds"]
        ents.append(("BOUNDS", self._poly("BOUNDS", [(b["xmin"], b["ymin"]), (b["xmax"], b["ymin"]), (b["xmax"], b["ymax"]), (b["xmin"], b["ymax"])])))
        for o in geometry["obstacles"]:
            ents.append(("OBSTACLES", self._poly("OBSTACLES", o["outline"])))
        for u in geometry["units"]:
            n = u["plane"]
            ents.append(("TOP_RODS", self._circle("TOP_RODS", u["x"], u["y"], geometry["rod_diameter"] / 2)))
            for p in u["parts"]:
                if p["kind"] == "housing":
                    layers.add(f"G{n}_MOTOR")
                    ents.append((f"G{n}_MOTOR", self._poly(f"G{n}_MOTOR", p["outline"])))
                elif p["kind"] == "gear":
                    layers.add(f"G{n}_GEAR")
                    ents.append((f"G{n}_GEAR", self._poly(f"G{n}_GEAR", p["outline"])))
        for idx, holes in holes_by_plane(geometry).items():
            for h in holes:
                lay = f"G{idx}_HOLES"
                layers.add(lay)
                ents.append((lay, self._circle(lay, h["x"], h["y"], h["d"] / 2)))
        out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC",
               "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(len(layers))]
        for name in sorted(layers):
            out += ["0", "LAYER", "2", name, "70", "0", "62", "7", "6", "CONTINUOUS"]
        out += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
        out += [text for _, text in ents]
        out += ["0", "ENDSEC", "0", "EOF"]
        return "\n".join(x for chunk in out for x in chunk.split("\n")) + "\n"

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
