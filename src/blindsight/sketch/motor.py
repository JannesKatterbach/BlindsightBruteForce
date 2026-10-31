"""Link between sketch and motor (MotorSpec). Sketches built from the motor fields or an outline, the housing
hull and the gear dimensions of a motor with a sketch."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Optional

from ..errors import SketchError
from ..geometry import Footprint
from ..i18n import tr
from .entities import ORIGIN, ROLE_GEAR, sketch_dict
from .solver import solve

CACHE_SIZE = 64  # solved motor sketches that are cached

# Key of the sketch -> (profile dict or None, errors). A sketch is needed several times per run (validation,
# model, service). The cache saves computing time and prevents a tight time limit from letting the
# validation pass once and fail once.
_motor_cache: "OrderedDict[str, tuple[Optional[dict], list]]" = OrderedDict()


class Builder:
    """Builds sketches from code (rectangles, closed outlines, the gear) with the relations of the UI tools."""

    def __init__(self) -> None:
        self.points: list[list[float]] = []
        self.entities: list[dict] = []
        self.constraints: list[dict] = []

    def point_entity(self, x: float, y: float, role: str = "") -> int:
        self.points.append([float(x), float(y)])
        self.entities.append({"type": "point", "points": [len(self.points) - 1], "radius": None, "construction": False, "role": role})
        return len(self.entities) - 1

    def line(self, a, b, construction: bool = False, role: str = "") -> int:
        self.points += [[float(a[0]), float(a[1])], [float(b[0]), float(b[1])]]
        n = len(self.points)
        self.entities.append({"type": "line", "points": [n - 2, n - 1], "radius": None, "construction": construction, "role": role})
        return len(self.entities) - 1

    def end(self, line: int, which: int) -> str:
        """Reference of the start (0) or end (1) point of a line."""
        return f"p{self.entities[line]['points'][which]}"

    def constrain(self, type_: str, refs: list[str], value: Optional[float] = None) -> None:
        self.constraints.append({"type": type_, "refs": refs, "value": value, "at": None, "enabled": True, "name": "", "label": None})

    def closed(self, pts: list, role: str = "") -> list[int]:
        """Closed chain of lines through pts, consecutive ends coincident."""
        lines = [self.line(pts[i], pts[(i + 1) % len(pts)], role=role) for i in range(len(pts))]
        for i, k in enumerate(lines):
            self.constrain("coincident", [self.end(k, 1), self.end(lines[(i + 1) % len(lines)], 0)])
        return lines

    def rectangle(self, x0: float, y0: float, x1: float, y1: float, role: str = "") -> list[int]:
        """Lines bottom, right, top, left with coincident corners, horizontal and vertical (like the rectangle tool)."""
        lines = self.closed([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], role)
        self.constrain("horizontal", [f"e{lines[0]}"])
        self.constrain("vertical", [f"e{lines[1]}"])
        self.constrain("horizontal", [f"e{lines[2]}"])
        self.constrain("vertical", [f"e{lines[3]}"])
        return lines

    def gear(self, cd: float, diameter: float, width: float) -> None:
        """Gear rectangle with centre point on the x axis at (-cd, 0), fully dimensioned (like the gear tool)."""
        x0, x1, y0, y1 = -cd - diameter / 2.0, -cd + diameter / 2.0, -width / 2.0, width / 2.0
        lines = self.rectangle(x0, y0, x1, y1, ROLE_GEAR)
        diagonal = self.line((x0, y0), (x1, y1), construction=True, role=ROLE_GEAR)
        self.constrain("coincident", [self.end(diagonal, 0), self.end(lines[0], 0)])
        self.constrain("coincident", [self.end(diagonal, 1), self.end(lines[2], 0)])
        centre = self.point_entity(-cd, 0.0, ROLE_GEAR)
        self.constrain("midpoint", [f"e{centre}", f"e{diagonal}"])
        self.constrain("horizontal", [f"e{centre}", ORIGIN])
        self.constrain("distance", [ORIGIN, f"e{centre}"], cd)
        self.constrain("length", [f"e{lines[0]}"], diameter)
        self.constrain("length", [f"e{lines[3]}"], width)

    def as_dict(self) -> dict:
        return {"points": self.points, "entities": self.entities, "constraints": self.constraints}


def _housing_offset(motor: Any, top: float) -> tuple[float, float]:
    """Rod position in the housing frame (gear_gap behind the top edge, rod at the gear centre height)."""
    return motor.shaft_x + motor.center_distance, top + motor.gear_gap + motor.gear_width / 2.0


def sketch_from_motor(motor: Any) -> dict:
    """Housing rectangle (width x depth) and gear from the motor fields, fully dimensioned, in the rod frame."""
    b = Builder()
    rx, ry = _housing_offset(motor, motor.depth / 2.0)
    x0, y0 = -motor.width / 2.0 - rx, -motor.depth / 2.0 - ry
    lines = b.rectangle(x0, y0, x0 + motor.width, y0 + motor.depth)
    b.constrain("length", [f"e{lines[0]}"], motor.width)
    b.constrain("length", [f"e{lines[3]}"], motor.depth)
    b.constrain("hdistance", [ORIGIN, b.end(lines[0], 0)], abs(x0))
    b.constrain("vdistance", [ORIGIN, b.end(lines[0], 0)], abs(y0))
    b.gear(motor.center_distance, motor.gear_diameter, motor.gear_width)
    return b.as_dict()


def sketch_from_outline(outline: list[list[float]], motor: Any) -> dict:
    """Outline in the housing frame (e.g. from SVG) as a closed chain of lines plus the gear, in the rod frame.

    The outline is placed relative to the gear the same way as an outline without a sketch. The gear sits
    gear_gap behind the top edge, the rod at the height of the gear centre. The outline has no dimensions."""
    poly = [list(p) for p in Footprint.polygon(outline).pts]
    rx, ry = _housing_offset(motor, max(p[1] for p in poly))
    b = Builder()
    b.closed([(x - rx, y - ry) for x, y in poly])
    b.gear(motor.center_distance, motor.gear_diameter, motor.gear_width)
    return b.as_dict()


def _cache_key(motor: Any, prefix: str) -> str:
    return json.dumps([sketch_dict(motor.sketch), prefix], sort_keys=True, default=str)


def sketch_profile(motor: Any, prefix: str = "motor.sketch") -> tuple[Optional[dict], list]:
    """Solve the sketch of a motor. Returns (profile with housing hull and gear, or None, errors with field path)."""
    key = _cache_key(motor, prefix)
    cached = _motor_cache.get(key)
    if cached is None:
        res = solve(motor.sketch)
        problems = list(res.errors) + list(res.warnings)
        errors = [tr("sketch.prefixed", prefix=prefix, message=m) for m in problems]
        cached = (res.profile if not problems else None, errors)
        _motor_cache[key] = cached
        if len(_motor_cache) > CACHE_SIZE:
            _motor_cache.popitem(last=False)
    else:
        _motor_cache.move_to_end(key)
    return cached


def motor_fields(profile: dict) -> dict:
    """Motor fields that a sketch determines (housing bounding box, gear and centre distance)."""
    box, gear = profile["bbox"], profile["gear"]
    return {"width": box["xmax"] - box["xmin"], "depth": box["ymax"] - box["ymin"], "gear_diameter": gear["diameter"],
            "gear_width": gear["width"], "center_distance": gear["center_distance"]}


def check_sketch_motor(motor: Any, prefix: str = "motor.sketch") -> tuple[list[tuple[float, float]], list]:
    """Housing hull of a motor sketch and the errors. Returns (housing, errors)."""
    prof, errors = sketch_profile(motor, prefix)
    return ([tuple(p) for p in prof["housing"]] if prof else []), list(errors)


def housing_polygon(motor: Any) -> list[tuple[float, float]]:
    """Housing outline in the rod frame at the nominal centre distance (counter clockwise).

    With a sketch it is the hull of the solved sketch, otherwise computed from the rectangle or outline.
    Raises SketchError on errors."""
    if getattr(motor, "sketch", None) is not None:
        pts, errs = check_sketch_motor(motor)
        if errs:
            raise SketchError(errs)
        return pts
    rx, ry = motor.rod_local()
    poly = Footprint.polygon(motor.outline).pts if motor.outline else Footprint.rect(0, 0, motor.width, motor.depth).pts
    return [(x - rx, y - ry) for x, y in poly]
