"""Import of motor geometry from SVG.

The outline is turned into the same MotorSpec as a manual input (outline as a convex polygon, width and
depth as the bounding box). Manual, drawn and imported motors therefore use the same collision and
optimization algorithm.

Rule. If the scale is ambiguous (no width with unit together with viewBox), ScaleRequired is raised.
A size is never guessed.

Supported. Exactly one <rect>, <polygon>, <polyline> or <path> with straight lines (M L H V Z, absolute
and relative). Paths with curves (C S Q T A) are rejected instead of silently reading control points as
corners. Non convex outlines are replaced by their convex hull (conservative) and this is reported.
SVG has Y down, the motor system has Y up (the outline is mirrored and centred on the middle of the
bounding box).
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import MotorSpec
from .geometry import convex_hull, polygon_area
from .i18n import tr
from .units import is_finite_number

# Length units that may appear in SVG files, converted to mm on import (the program itself only uses mm).
# Unitless values, px and % are ambiguous and require an explicit scale.
SVG_UNITS_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "pt": 25.4 / 72.0, "pc": 25.4 / 6.0}
CONVEX_AREA_RATIO = 0.9999  # area of the outline relative to the hull from which it counts as convex
LINE_COMMANDS = "MLHVZ"


class ScaleRequired(ValueError):
    """The scale of the SVG is ambiguous. The user has to give mm per SVG unit."""


class SvgImportError(ValueError):
    """SVG not readable or not supported (understandable message)."""


@dataclass
class ImportedOutline:
    outline: list[list[float]]  # convex, centred, Y up, in mm
    width: float
    depth: float
    was_convex: bool
    notes: list[str] = field(default_factory=list)


_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$")
_TOKEN = re.compile(r"([A-Za-z])|([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")


def _length_mm(text: Optional[str]) -> Optional[float]:
    """Length with unit in mm. None if the unit is missing or ambiguous (px, %)."""
    if not text:
        return None
    m = _NUM.match(text)
    if not m:
        return None
    unit = m.group(2).lower()
    val = float(m.group(1))
    return val * SVG_UNITS_MM[unit] if unit in SVG_UNITS_MM else None  # unitless, px and % are ambiguous


def _path_points(d: str) -> list[tuple[float, float]]:
    """Corner points of a path of straight lines. Other commands raise SvgImportError."""
    pts: list[tuple[float, float]] = []
    cmd = None
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    nums: list[float] = []

    def flush():
        nonlocal cur, start, nums
        if cmd is None:
            return
        c = cmd.upper()
        rel = cmd.islower()
        if c in "ML":
            if len(nums) % 2 or not nums:
                raise SvgImportError(tr("svg.path_coordinates"))
            for i in range(0, len(nums), 2):
                x, y = nums[i], nums[i + 1]
                cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
                pts.append(cur)
                if c == "M" and i == 0:
                    start = cur
        elif c == "H":
            for x in nums:
                cur = (cur[0] + x if rel else x, cur[1])
                pts.append(cur)
        elif c == "V":
            for y in nums:
                cur = (cur[0], cur[1] + y if rel else y)
                pts.append(cur)
        elif c == "Z":
            cur = start
        nums = []

    for m in _TOKEN.finditer(d):
        if m.group(1):
            flush()
            cmd = m.group(1)
            if cmd.upper() not in LINE_COMMANDS:
                raise SvgImportError(tr("svg.path_command", cmd=cmd))
            if cmd.upper() == "Z":
                flush()
        else:
            nums.append(float(m.group(2)))
    flush()
    if not pts:
        raise SvgImportError(tr("svg.path_empty"))
    return pts


def _shape_points(e: ET.Element, tag: str) -> list[tuple[float, float]]:
    if tag == "rect":
        x, y = float(e.get("x", 0)), float(e.get("y", 0))
        w, h = float(e.get("width", 0)), float(e.get("height", 0))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if tag in ("polygon", "polyline"):
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", e.get("points", ""))]
        if len(nums) < 6 or len(nums) % 2:
            raise SvgImportError(tr("svg.polygon_points"))
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
    return _path_points(e.get("d", ""))


def _tag(e: ET.Element) -> str:
    return e.tag.split("}")[-1] if isinstance(e.tag, str) else ""


def outline_from_svg(svg_text: Any, mm_per_unit: Any = None) -> ImportedOutline:
    """Read exactly one outline from the SVG text. Returned in mm, centred, Y up, convex.

    mm_per_unit is the scale. Without it, it is derived from width (with unit) and viewBox, otherwise
    ScaleRequired is raised."""
    if not isinstance(svg_text, str):
        raise SvgImportError(tr("svg.not_text"))
    if mm_per_unit is not None and (not is_finite_number(mm_per_unit) or mm_per_unit <= 0):
        raise SvgImportError(tr("svg.scale_positive"))
    try:
        root = ET.fromstring(svg_text)
    except (ET.ParseError, RecursionError, ValueError) as exc:
        raise SvgImportError(tr("svg.unreadable", error=str(exc))) from exc
    tag = _tag
    scale = mm_per_unit
    notes: list[str] = []
    if scale is None:
        w_mm = _length_mm(root.get("width"))
        vb = root.get("viewBox")
        if w_mm is None or not vb:
            raise ScaleRequired(tr("svg.scale_required"))
        try:
            vbw = float(re.split(r"[ ,]+", vb.strip())[2])
        except (IndexError, ValueError):
            raise ScaleRequired(tr("svg.viewbox_unreadable")) from None
        if vbw <= 0:
            raise ScaleRequired(tr("svg.viewbox_invalid"))
        scale = w_mm / vbw
    shapes = [e for e in root.iter() if tag(e) in ("rect", "polygon", "polyline", "path")]
    if len(shapes) != 1:
        raise SvgImportError(tr("svg.shape_count", n=len(shapes)))
    if shapes[0].get("transform"):
        notes.append(tr("svg.transform_ignored"))
    try:
        raw = _shape_points(shapes[0], tag(shapes[0]))
    except ValueError as exc:
        if isinstance(exc, SvgImportError):
            raise
        raise SvgImportError(tr("svg.outline_unreadable", error=str(exc))) from exc
    xs, ys = [p[0] for p in raw], [p[1] for p in raw]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    pts = [((x - cx) * scale, -(y - cy) * scale) for x, y in raw]
    hull = convex_hull(pts)
    if len(hull) < 3:
        raise SvgImportError(tr("svg.no_area"))
    area_raw = polygon_area(pts)
    area_hull = polygon_area(hull)
    convex = area_raw >= area_hull * CONVEX_AREA_RATIO
    if not convex:
        notes.append(tr("svg.not_convex"))
    w = (max(xs) - min(xs)) * scale
    d = (max(ys) - min(ys)) * scale
    if w <= 0 or d <= 0:
        raise SvgImportError(tr("svg.no_area"))
    return ImportedOutline([[x, y] for x, y in hull], w, d, convex, notes)


def motor_outline_from_svg(svg_text: str, mm_per_unit: Optional[float] = None) -> tuple[float, float]:
    """Width and depth of the outline in mm."""
    o = outline_from_svg(svg_text, mm_per_unit)
    return o.width, o.depth


def motor_from_svg(svg_text: str, height: float, mm_per_unit: Optional[float] = None, base: Optional[MotorSpec] = None) -> MotorSpec:
    """Create a MotorSpec. Height (Z) and gear data come from base, the SVG gives the footprint."""
    o = outline_from_svg(svg_text, mm_per_unit)
    spec = copy.deepcopy(base) if base is not None else MotorSpec()  # base stays unchanged
    spec.width, spec.depth, spec.height = o.width, o.depth, height
    spec.outline = o.outline
    return spec
