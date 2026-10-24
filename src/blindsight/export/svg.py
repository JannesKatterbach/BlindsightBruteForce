"""True to scale SVG export.

One SVG unit is exactly 1 mm (viewBox in mm, width and height in mm). Y is mirrored (svg_y = ymax - y)
so that the view looks like a normal coordinate system with Y up. The origin of the drawing is the
bottom left corner of the build area.

Structure
  <g id="top">         shared top view of all units (at the origin)
  <g id="plane-1"> ...  one sheet per motor layer (shifted to the right), shows motors, gears, rods
                        and the through holes of this layer
The file is a geometric result and not a finished PCB layout.
"""

from __future__ import annotations

import math
from typing import Callable, Optional
from xml.sax.saxutils import escape

from ..i18n import tr
from .base import rod_passes

PLANE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"]
SHEET_GAP = 20.0  # mm between the sheets
DECIMALS = 4  # decimals of the coordinates


def _color(plane: int) -> str:
    return PLANE_COLORS[(plane - 1) % len(PLANE_COLORS)]


def _f(v: float) -> str:
    """Compact number with at most DECIMALS decimals (without -0 and trailing zeros)."""
    v = round(v, DECIMALS)
    if v == 0:
        v = 0.0  # -0.0 becomes 0
    text = f"{v:.{DECIMALS}f}"
    return text.rstrip("0").rstrip(".")


def _nearest_neighbor_pairs(units: list[dict]) -> list[tuple[dict, dict]]:
    """Every unit with its nearest neighbour, every pair only once (even if mutual)."""
    pairs: dict[tuple[int, int], tuple[dict, dict]] = {}
    for u in units:
        nearest = min((v for v in units if v is not u), key=lambda v: math.hypot(v["x"] - u["x"], v["y"] - u["y"]))
        key = (min(u["id"], nearest["id"]), max(u["id"], nearest["id"]))
        pairs.setdefault(key, (u, nearest))
    return [pairs[k] for k in sorted(pairs)]


class SvgExporter:
    name = "svg"  # key in EXPORTERS and in the API
    extension = "svg"
    filename = "blindsight.svg"
    mime = "image/svg+xml"

    def __init__(self, show_distances: bool = True, per_plane_sheets: bool = True):
        self.show_distances = show_distances
        self.per_plane_sheets = per_plane_sheets

    def export(self, geometry: dict) -> str:
        b = geometry["bounds"]
        w = b["xmax"] - b["xmin"]
        h = b["ymax"] - b["ymin"]
        sheets: list[tuple[str, Optional[int]]] = [("top", None)]
        if self.per_plane_sheets:
            sheets += [(f"plane-{p['index']}", p["index"]) for p in geometry["planes"][1:]]
        total_w = len(sheets) * w + (len(sheets) - 1) * SHEET_GAP
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(total_w)}mm" height="{_f(h)}mm" '
            f'viewBox="0 0 {_f(total_w)} {_f(h)}" data-unit="mm" data-scale="1 SVG unit = 1 mm">',
            f"<title>{escape(geometry['name'])}</title>",
            f"<desc>{escape(tr('svg.desc', x=_f(b['xmin']), y=_f(b['ymin'])))}</desc>",
        ]
        for idx, (gid, plane) in enumerate(sheets):
            dx = idx * (w + SHEET_GAP)
            transform = f' transform="translate({_f(dx)} 0)"' if idx else ""
            out.append(f'<g id="{gid}"{transform}>')
            out.extend(_Sheet(geometry, plane, self.show_distances).render())
            out.append("</g>")
        out.append("</svg>")
        return "\n".join(out)


class _Sheet:
    """One sheet. plane None is the top view of all layers, otherwise the view of one motor layer."""

    def __init__(self, geometry: dict, plane: Optional[int], show_distances: bool):
        self.geometry = geometry
        self.plane = plane
        self.show_distances = show_distances
        b = geometry["bounds"]
        self.fx: Callable[[float], float] = lambda x: x - b["xmin"]
        self.fy: Callable[[float], float] = lambda y: b["ymax"] - y

    def render(self) -> list[str]:
        return self._frame() + self._obstacles() + self._motors() + self._rods() + self._distances() + self._collisions()

    def _poly(self, outline, cls: str, extra: str = "") -> str:
        pts = " ".join(f"{_f(self.fx(x))},{_f(self.fy(y))}" for x, y in outline)
        return f'<polygon class="{cls}" points="{pts}" {extra}/>'

    def _shows_unit(self, u: dict) -> bool:
        """The unit appears on the sheet (own layer or its rod passes through the layer)."""
        return self.plane is None or u["plane"] == self.plane or rod_passes(self.geometry, u, self.plane)

    def _frame(self) -> list[str]:
        b = self.geometry["bounds"]
        w, h = b["xmax"] - b["xmin"], b["ymax"] - b["ymin"]
        out = [f'<rect class="bounds" x="0" y="0" width="{_f(w)}" height="{_f(h)}" fill="none" stroke="#000" stroke-width="0.3"/>']
        margin = b["edge_margin"]
        if margin > 0:
            out.append(
                f'<rect class="edge-margin" x="{_f(margin)}" y="{_f(margin)}" width="{_f(w - 2 * margin)}" '
                f'height="{_f(h - 2 * margin)}" fill="none" stroke="#888" stroke-width="0.15" stroke-dasharray="1 1"/>'
            )
        title = tr("svg.top_title") if self.plane is None else tr("svg.plane_title", plane=self.plane)
        out.append(f'<text x="2" y="{_f(h - 2)}" font-size="4" fill="#333">{escape(title)}</text>')
        return out

    def _obstacles(self) -> list[str]:
        return [self._poly(o["outline"], "obstacle", 'fill="#ccc" stroke="#555" stroke-width="0.2"')
                for o in self.geometry["obstacles"]]

    def _motors(self) -> list[str]:
        """Housings and gears, on layer sheets only the motors of this layer."""
        out = []
        for u in self.geometry["units"]:
            if self.plane is not None and u["plane"] != self.plane:
                continue
            col = _color(u["plane"])
            for p in u["parts"]:
                if p["kind"] == "housing":
                    out.append(self._poly(
                        p["outline"], "housing",
                        f'data-unit="{u["id"]}" data-plane="{u["plane"]}" fill="{col}" fill-opacity="0.35" '
                        f'stroke="{col}" stroke-width="0.25"',
                    ))
                elif p["kind"] == "gear":
                    out.append(self._poly(
                        p["outline"], "gear", f'data-unit="{u["id"]}" fill="{col}" fill-opacity="0.8" stroke="#222" stroke-width="0.2"',
                    ))
        return out

    def _rods(self) -> list[str]:
        geometry = self.geometry
        r = geometry["rod_diameter"] / 2.0
        hole_r = geometry["hole_diameter"] / 2.0
        out = []
        for u in geometry["units"]:
            if not self._shows_unit(u):
                continue
            cx, cy = self.fx(u["x"]), self.fy(u["y"])
            if self.plane is not None:
                out.append(
                    f'<circle class="hole" data-unit="{u["id"]}" cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(hole_r)}" '
                    'fill="none" stroke="#000" stroke-width="0.2"/>'
                )
            out.append(
                f'<circle class="rod" data-unit="{u["id"]}" data-plane="{u["plane"]}" data-x="{_f(u["x"])}" '
                f'data-y="{_f(u["y"])}" cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="#222" stroke="none"/>'
            )
            if self.plane is None:
                out.append(f'<text x="{_f(cx + r + 0.6)}" y="{_f(cy - r - 0.3)}" font-size="2.2" fill="#000">{u["id"]}</text>')
        return out

    def _distances(self) -> list[str]:
        """Distance of every rod to its nearest one (top view only)."""
        units = self.geometry["units"]
        if self.plane is not None or not self.show_distances or len(units) < 2:
            return []
        out = ['<g id="distances" stroke="#777" stroke-width="0.12" stroke-dasharray="0.8 0.8" font-size="2">']
        for u, v in _nearest_neighbor_pairs(units):
            d = math.hypot(v["x"] - u["x"], v["y"] - u["y"])
            x1, y1, x2, y2 = self.fx(u["x"]), self.fy(u["y"]), self.fx(v["x"]), self.fy(v["y"])
            out.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"/>')
            out.append(f'<text x="{_f((x1 + x2) / 2)}" y="{_f((y1 + y2) / 2)}" stroke="none" fill="#555">{d:.1f}</text>')
        out.append("</g>")
        return out

    def _collisions(self) -> list[str]:
        return [
            f'<circle class="collision" cx="{_f(self.fx(c["x"]))}" cy="{_f(self.fy(c["y"]))}" r="2" fill="none" '
            'stroke="#e00" stroke-width="0.4"/>'
            for c in self.geometry.get("collisions", [])
        ]
