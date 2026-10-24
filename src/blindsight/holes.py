"""Hole pattern files. Fixed G0 holes or an own repeating tile, in mm with the origin at the bottom left.

Format ``blindsight.holes`` (written by the hole pattern generator of the web UI)
  {"format": "blindsight.holes", "version": 1, "units": {"length": "mm"},
   "build_area": {"width": .., "height": ..},                      optional, for information
   "holes": [{"id": 0, "x": .., "y": ..}, ...],                     fixed holes of G0
   "tile": {"width": .., "height": .., "scalable": false,           optional, own repeating tile
            "holes": [{"x": .., "y": ..}, ...]}}

The export ``blindsight.rod_positions`` is read as well (the holes of G0 from all presence groups), so an
exported result can be loaded again as a fixed hole pattern.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import CustomTileSpec, Project
from .errors import ValidationError
from .i18n import tr
from .units import is_finite_number

FORMAT_HOLES = "blindsight.holes"
FORMAT_RODS = "blindsight.rod_positions"
FORMAT_VERSION = 1
SAME_HOLE_MM = 1e-6


class HolesError(ValidationError):
    """Invalid hole pattern file."""


@dataclass
class HoleDocument:
    holes: list[list[float]] = field(default_factory=list)
    tile: Optional[CustomTileSpec] = None
    build_area: Optional[dict] = None

    def as_dict(self) -> dict:
        return document(self.holes, self.tile, self.build_area)


def document(holes: list[list[float]], tile: Optional[CustomTileSpec] = None, build_area: Optional[dict] = None) -> dict:
    """File content in the format blindsight.holes."""
    out: dict[str, Any] = {"format": FORMAT_HOLES, "version": FORMAT_VERSION, "units": {"length": "mm"},
                           "origin": "bottom left corner of the build area, x to the right, y up"}
    if build_area:
        out["build_area"] = build_area
    out["holes"] = [{"id": i, "x": x, "y": y} for i, (x, y) in enumerate(holes)]
    if tile is not None:
        out["tile"] = {"width": tile.width, "height": tile.height, "scalable": tile.scalable,
                       "holes": [{"x": x, "y": y} for x, y in tile.holes]}
    return out


def _point(entry: Any, path: str, errs: list) -> Optional[list[float]]:
    if isinstance(entry, dict):
        x, y = entry.get("x"), entry.get("y")
    elif isinstance(entry, (list, tuple)) and len(entry) == 2:
        x, y = entry
    else:
        x = y = None
    if not (is_finite_number(x) and is_finite_number(y)):
        errs.append(tr("holes.bad_hole", path=path))
        return None
    return [float(x), float(y)]


def _points(entries: Any, path: str, errs: list) -> list[list[float]]:
    if not isinstance(entries, list):
        errs.append(tr("holes.bad_hole", path=path))
        return []
    points = [_point(e, f"{path}[{i}]", errs) for i, e in enumerate(entries)]
    return [p for p in points if p is not None]


def parse(data: Any) -> HoleDocument:
    """Read a hole pattern file (blindsight.holes or blindsight.rod_positions). Raises HolesError."""
    if not isinstance(data, dict):
        raise HolesError(tr("holes.not_object"))
    kind = data.get("format", FORMAT_HOLES)
    if kind not in (FORMAT_HOLES, FORMAT_RODS):
        raise HolesError(tr("holes.unknown_format", format=kind, known=[FORMAT_HOLES, FORMAT_RODS]))
    units = data.get("units") or {}
    if isinstance(units, dict) and units.get("length", "mm") != "mm":
        raise HolesError(tr("holes.unit"))
    errs: list = []
    doc = HoleDocument(build_area=data.get("build_area") if isinstance(data.get("build_area"), dict) else None)
    if kind == FORMAT_RODS:
        layers = data.get("layers") or []
        g0 = next((layer for layer in layers if isinstance(layer, dict) and layer.get("index") == 0), None) or {}
        entries = [rod for key, rods in g0.items() if key.startswith("present") or key == "always_present"
                   for rod in (rods if isinstance(rods, list) else [])]
        doc.holes = sorted(_points(entries, "layers[0]", errs), key=lambda p: (p[1], p[0]))
    else:
        doc.holes = _points(data.get("holes", []), "holes", errs)
        tile = data.get("tile")
        if tile is not None:
            doc.tile = _tile(tile, errs)
    if errs:
        raise HolesError(errs)
    if not doc.holes and doc.tile is None:
        raise HolesError(tr("holes.empty"))
    return doc


def _tile(data: Any, errs: list) -> Optional[CustomTileSpec]:
    if not isinstance(data, dict):
        errs.append(tr("holes.bad_tile"))
        return None
    width, height = data.get("width"), data.get("height")
    holes = _points(data.get("holes", []), "tile.holes", errs)
    if not (is_finite_number(width) and is_finite_number(height) and width > 0 and height > 0) or not holes \
            or not all(0 <= x < width and 0 <= y < height for x, y in holes):
        errs.append(tr("holes.bad_tile"))
        return None
    return CustomTileSpec(float(width), float(height), holes, bool(data.get("scalable", False)))


def check(project: Project, holes: list[list[float]]) -> list[dict]:
    """Problems of single holes. Outside the build area or closer than two rods may be. [{index, message}]"""
    out = []
    bounds = project.bounds
    required = project.rod.diameter + project.required_gap
    for i, (x, y) in enumerate(holes):
        if not (bounds.xmin <= x <= bounds.xmax and bounds.ymin <= y <= bounds.ymax):
            out.append({"index": i, "message": tr("holes.outside", n=i + 1, x=x, y=y)})
    order = sorted(range(len(holes)), key=lambda k: holes[k][0])
    for a, i in enumerate(order):  # sweep along x, only neighbours within the required distance matter
        for j in order[a + 1:]:
            if holes[j][0] - holes[i][0] >= required:
                break
            distance = math.hypot(holes[j][0] - holes[i][0], holes[j][1] - holes[i][1])
            if distance < required - 1e-9:
                first, second = sorted((i, j))
                out.append({"index": second, "other": first,
                            "message": tr("holes.too_close", n=second + 1, m=first + 1, distance=distance, required=required)})
    return sorted(out, key=lambda p: p["index"])
