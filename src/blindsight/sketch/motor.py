"""Link between sketch and motor (MotorSpec). Conversion of legacy housing values and housing outline."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from ..errors import SketchError
from ..geometry import Footprint
from ..i18n import tr
from .polygon import gear_overlap_message
from .solver import solve
from .structure import sketch_dict

CACHE_SIZE = 64  # solved motor sketches that are cached

# Key from sketch and motor dimensions -> (housing points, errors). A sketch is needed several times per
# run (validation, model, service). The cache saves computing time and prevents a tight time limit from
# letting the validation pass once and fail once.
_motor_cache: "OrderedDict[str, tuple[list[tuple[float, float]], list[str]]]" = OrderedDict()


def _constraint(type_: str, a: Any = None, b: Any = None, value: Any = None) -> dict:
    return {"type": type_, "a": a, "b": b, "value": value, "value2": None, "ref": "rod", "enabled": True, "name": ""}


def legacy_to_sketch(motor: Any, with_constraints: bool = True) -> dict:
    """Turn the rectangle or outline of a motor into a sketch in the rod frame.

    For the rectangle, constraints that keep the rectangular shape come along."""
    outline = getattr(motor, "outline", None)
    if outline:
        poly = [list(p) for p in Footprint.polygon(outline).pts]
    else:
        poly = [list(p) for p in Footprint.rect(0, 0, motor.width, motor.depth).pts]
    rx, ry = motor.rod_local()
    pts = [[x - rx, y - ry] for x, y in poly]
    cons: list[dict] = []
    if with_constraints and not outline:
        cons = [
            _constraint("horizontal", 0), _constraint("length", 0, value=motor.width),
            _constraint("length", 1, value=motor.depth), _constraint("angle", 1, value=90.0),
            _constraint("parallel", 0, 2), _constraint("parallel", 1, 3),
        ]
    return {"points": pts, "constraints": cons}


def sketch_from_outline(outline: list[list[float]], motor: Any) -> dict:
    """Outline in the housing coordinate system (e.g. from SVG) as a sketch in the rod frame without constraints.

    The outline is placed relative to the gear the same way as an outline without a sketch. The gear sits
    gear_gap behind the top edge, the rod at the height of the gear centre."""
    poly = [list(p) for p in Footprint.polygon(outline).pts]
    top = max(p[1] for p in poly)
    rx, ry = motor.shaft_x + motor.center_distance, top + motor.gear_gap + motor.gear_width / 2.0
    return {"points": [[x - rx, y - ry] for x, y in poly], "constraints": []}


def _cache_key(motor: Any, prefix: str) -> str:
    return json.dumps(
        [sketch_dict(motor.sketch), motor.center_distance, motor.center_distances(), motor.gear_diameter,
         motor.gear_width, prefix],
        sort_keys=True, default=str,
    )


def check_sketch_motor(motor: Any, prefix: str = "motor.sketch") -> tuple[list[tuple[float, float]], list[str]]:
    """Solve the sketch of a motor and check it against the gear. Returns (housing, errors)."""
    key = _cache_key(motor, prefix)
    cached = _motor_cache.get(key)
    if cached is None:
        cached = _check_sketch_motor(motor, prefix)
        _motor_cache[key] = cached
        if len(_motor_cache) > CACHE_SIZE:
            _motor_cache.popitem(last=False)
    else:
        _motor_cache.move_to_end(key)
    pts, errs = cached
    return list(pts), list(errs)


def _check_sketch_motor(motor: Any, prefix: str) -> tuple[list[tuple[float, float]], list[str]]:
    res = solve(motor.sketch, cd=motor.center_distance)
    if not res.ok:
        return [], list(res.errors or [tr("sketch.unsolvable", prefix=prefix)])
    if not res.convex:
        return [], [tr("sketch.prefixed", prefix=prefix, message=w) for w in res.warnings]
    pts = res.sketch["points"]
    for cd in motor.center_distances():
        message = gear_overlap_message(pts, motor.center_distance, cd, motor.gear_diameter, motor.gear_width)
        if message:
            return [(p[0], p[1]) for p in pts], [tr("sketch.prefixed", prefix=prefix, message=message)]
    return [(p[0], p[1]) for p in pts], []


def housing_polygon(motor: Any) -> list[tuple[float, float]]:
    """Housing outline in the rod frame at the nominal centre distance (counter clockwise).

    With a sketch it is solved, otherwise computed from the rectangle or outline. Raises SketchError on errors."""
    if getattr(motor, "sketch", None) is not None:
        pts, errs = check_sketch_motor(motor)
        if errs:
            raise SketchError(errs)
        return pts
    rx, ry = motor.rod_local()
    poly = Footprint.polygon(motor.outline).pts if motor.outline else Footprint.rect(0, 0, motor.width, motor.depth).pts
    return [(x - rx, y - ry) for x, y in poly]
