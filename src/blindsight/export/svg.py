"""Massstabsgetreuer SVG Export.

Eine SVG Einheit entspricht genau 1 mm (viewBox in mm, width und height in mm).
Y wird gespiegelt (svg_y = ymax - y), damit die Ansicht wie ein normales Koordinatensystem
mit Y nach oben aussieht. Der Ursprung der Zeichnung ist die untere linke Ecke des Bauraums.

Aufbau
  <g id="top">         gemeinsame Draufsicht aller Einheiten (am Ursprung)
  <g id="plane-1"> ...  je Motorebene ein Blatt (nach rechts versetzt), zeigt Motoren,
                        Zahnraeder, Stangen und die Durchgangsloecher dieser Ebene
Die Datei ist ein geometrisches Ergebnis und kein fertiges PCB Layout.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .base import rod_passes

PLANE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"]
SHEET_GAP = 20.0


def _color(plane: int) -> str:
    return PLANE_COLORS[(plane - 1) % len(PLANE_COLORS)]


def _f(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") if "." in f"{v:.4f}" else f"{v:.4f}"


class SvgExporter:
    extension = "svg"
    mime = "image/svg+xml"

    def __init__(self, show_distances: bool = True, per_plane_sheets: bool = True):
        self.show_distances = show_distances
        self.per_plane_sheets = per_plane_sheets

    def export(self, geometry: dict) -> str:
        b = geometry["bounds"]
        w = b["xmax"] - b["xmin"]
        h = b["ymax"] - b["ymin"]
        sheets = [("top", None)]
        if self.per_plane_sheets:
            sheets += [(f"plane-{p['index']}", p["index"]) for p in geometry["planes"][1:]]
        total_w = len(sheets) * w + (len(sheets) - 1) * SHEET_GAP
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(total_w)}mm" height="{_f(h)}mm" '
            f'viewBox="0 0 {_f(total_w)} {_f(h)}" data-unit="mm" data-scale="1 SVG unit = 1 mm">',
            f"<title>{escape(geometry['name'])}</title>",
            f"<desc>Project Blindsight. Massstab 1:1, Einheit mm. Ursprung links unten im Bauraum "
            f"({_f(b['xmin'])}, {_f(b['ymin'])}). Geometrisches Ergebnis, kein fertiges PCB Layout.</desc>",
        ]
        for idx, (gid, plane) in enumerate(sheets):
            dx = idx * (w + SHEET_GAP)
            tr = f' transform="translate({_f(dx)} 0)"' if idx else ""
            out.append(f'<g id="{gid}"{tr}>')
            out.extend(self._sheet(geometry, plane))
            out.append("</g>")
        out.append("</svg>")
        return "\n".join(out)

    # -- Hilfen -----------------------------------------------------------------
    @staticmethod
    def _tx(geometry: dict):
        b = geometry["bounds"]
        return lambda x: x - b["xmin"], lambda y: b["ymax"] - y

    def _poly(self, geometry: dict, outline, cls: str, extra: str = "") -> str:
        fx, fy = self._tx(geometry)
        pts = " ".join(f"{_f(fx(x))},{_f(fy(y))}" for x, y in outline)
        return f'<polygon class="{cls}" points="{pts}" {extra}/>'

    def _sheet(self, geometry: dict, plane: int | None) -> list[str]:
        fx, fy = self._tx(geometry)
        b = geometry["bounds"]
        w = b["xmax"] - b["xmin"]
        h = b["ymax"] - b["ymin"]
        out = [
            f'<rect class="bounds" x="0" y="0" width="{_f(w)}" height="{_f(h)}" fill="none" stroke="#000" stroke-width="0.3"/>'
        ]
        mg = b["edge_margin"]
        if mg > 0:
            out.append(
                f'<rect class="edge-margin" x="{_f(mg)}" y="{_f(mg)}" width="{_f(w - 2 * mg)}" height="{_f(h - 2 * mg)}" '
                'fill="none" stroke="#888" stroke-width="0.15" stroke-dasharray="1 1"/>'
            )
        for o in geometry["obstacles"]:
            out.append(self._poly(geometry, o["outline"], "obstacle", 'fill="#ccc" stroke="#555" stroke-width="0.2"'))
        units = geometry["units"]
        hole_r = geometry["hole_diameter"] / 2.0
        title = "Draufsicht aller Ebenen" if plane is None else f"Ebene G{plane}"
        out.append(f'<text x="2" y="{_f(h - 2)}" font-size="4" fill="#333">{escape(title)}</text>')
        for u in units:
            if plane is not None and u["plane"] != plane and not self._rod_passes(geometry, u, plane):
                continue
            col = _color(u["plane"])
            for p in u["parts"]:
                if p["kind"] == "housing" and (plane is None or u["plane"] == plane):
                    out.append(self._poly(
                        geometry, p["outline"], "housing",
                        f'data-unit="{u["id"]}" data-plane="{u["plane"]}" fill="{col}" fill-opacity="0.35" '
                        f'stroke="{col}" stroke-width="0.25"',
                    ))
                elif p["kind"] == "gear" and (plane is None or u["plane"] == plane):
                    out.append(self._poly(
                        geometry, p["outline"], "gear",
                        f'data-unit="{u["id"]}" fill="{col}" fill-opacity="0.8" stroke="#222" stroke-width="0.2"',
                    ))
        for u in units:
            if plane is not None and not (u["plane"] == plane or self._rod_passes(geometry, u, plane)):
                continue
            cx, cy = fx(u["x"]), fy(u["y"])
            r = geometry["rod_diameter"] / 2.0
            if plane is not None:
                out.append(
                    f'<circle class="hole" data-unit="{u["id"]}" cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(hole_r)}" '
                    'fill="none" stroke="#000" stroke-width="0.2"/>'
                )
            out.append(
                f'<circle class="rod" data-unit="{u["id"]}" data-plane="{u["plane"]}" data-x="{_f(u["x"])}" '
                f'data-y="{_f(u["y"])}" cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="#222" stroke="none"/>'
            )
            if plane is None:
                out.append(
                    f'<text x="{_f(cx + r + 0.6)}" y="{_f(cy - r - 0.3)}" font-size="2.2" fill="#000">{u["id"]}</text>'
                )
        if plane is None and self.show_distances and len(units) > 1:
            out.append('<g id="distances" stroke="#777" stroke-width="0.12" stroke-dasharray="0.8 0.8" font-size="2">')
            for u in units:
                best = min(
                    (v for v in units if v is not u),
                    key=lambda v: math.hypot(v["x"] - u["x"], v["y"] - u["y"]),
                )
                d = math.hypot(best["x"] - u["x"], best["y"] - u["y"])
                if u["id"] < best["id"] or True:
                    x1, y1, x2, y2 = fx(u["x"]), fy(u["y"]), fx(best["x"]), fy(best["y"])
                    out.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"/>')
                    out.append(
                        f'<text x="{_f((x1 + x2) / 2)}" y="{_f((y1 + y2) / 2)}" stroke="none" fill="#555">{d:.1f}</text>'
                    )
            out.append("</g>")
        for c in geometry.get("collisions", []):
            out.append(
                f'<circle class="collision" cx="{_f(fx(c["x"]))}" cy="{_f(fy(c["y"]))}" r="2" fill="none" '
                'stroke="#e00" stroke-width="0.4"/>'
            )
        return out

    @staticmethod
    def _rod_passes(geometry: dict, u: dict, plane: int) -> bool:
        return rod_passes(geometry, u, plane)
