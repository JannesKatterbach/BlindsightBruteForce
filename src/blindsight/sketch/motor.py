"""Verbindung von Skizze und Motor (MotorSpec). Umrechnung alter Gehaeuseangaben und Gehaeusekontur."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from ..errors import SketchError
from ..geometry import Footprint
from .polygon import gear_overlap_message
from .solver import solve
from .structure import sketch_dict

CACHE_SIZE = 64  # geloeste Motorskizzen, die zwischengespeichert werden

# Schluessel aus Skizze und Motormassen -> (Gehaeusepunkte, Fehler). Eine Skizze wird pro Lauf
# mehrfach gebraucht (Validierung, Modell, Service). Der Cache spart die Rechenzeit und verhindert,
# dass ein knappes Zeitlimit die Validierung einmal bestehen und einmal scheitern laesst.
_motor_cache: "OrderedDict[str, tuple[list[tuple[float, float]], list[str]]]" = OrderedDict()


def _constraint(type_: str, a: Any = None, b: Any = None, value: Any = None) -> dict:
    return {"type": type_, "a": a, "b": b, "value": value, "value2": None, "ref": "rod", "enabled": True, "name": ""}


def legacy_to_sketch(motor: Any, with_constraints: bool = True) -> dict:
    """Wandelt Rechteck oder outline eines Motors in eine Skizze im Stangenrahmen um.

    Beim Rechteck werden Constraints mitgeliefert, die die Rechteckform festhalten."""
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
    """Kontur im Gehaeuse Koordinatensystem (z.B. aus SVG) als Skizze im Stangenrahmen ohne Constraints.

    Die Kontur wird so zum Zahnrad gesetzt, wie es auch ein Umriss ohne Skizze waere. Das Zahnrad sitzt
    gear_gap hinter der obersten Kante, die Stange auf Hoehe der Zahnradmitte."""
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
    """Loest die Skizze eines Motors und prueft sie gegen das Zahnrad. Rueckgabe (Gehaeuse, Fehler)."""
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
        return [], list(res.errors or [f"{prefix}. Skizze nicht lösbar"])
    if not res.convex:
        return [], [f"{prefix}. {w}" for w in res.warnings]
    pts = res.sketch["points"]
    for cd in motor.center_distances():
        message = gear_overlap_message(pts, motor.center_distance, cd, motor.gear_diameter, motor.gear_width)
        if message:
            return [(p[0], p[1]) for p in pts], [f"{prefix}. {message}"]
    return [(p[0], p[1]) for p in pts], []


def housing_polygon(motor: Any) -> list[tuple[float, float]]:
    """Gehaeusekontur im Stangenrahmen bei nominalem Achsabstand (gegen den Uhrzeigersinn).

    Mit Skizze wird sie geloest, sonst aus Rechteck oder outline berechnet. Wirft SketchError bei Fehlern."""
    if getattr(motor, "sketch", None) is not None:
        pts, errs = check_sketch_motor(motor)
        if errs:
            raise SketchError(errs)
        return pts
    rx, ry = motor.rod_local()
    poly = Footprint.polygon(motor.outline).pts if motor.outline else Footprint.rect(0, 0, motor.width, motor.depth).pts
    return [(x - rx, y - ry) for x, y in poly]
