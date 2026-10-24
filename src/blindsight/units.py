"""Units, tolerances and number checks of the whole program.

Units. All lengths are millimetres (mm), in the configuration, in the UI, in exports and in the
computation. Time is in seconds. Motor angles are in degrees in the configuration and the UI
(accepted for use with SI) and in radians inside the geometry kernel (``geometry.py``).
Coordinates. The origin (0, 0) is the bottom left corner of the build area, x to the right, y up,
z = 0 is the top face of G0 and negative below.

Tolerances are collected here so equal concepts are compared equally everywhere.
"""

from __future__ import annotations

import math
from typing import Any

# Numeric tolerances
EPS = 1e-9  # general comparison of lengths in mm (rounding noise)
EPS_AREA = 1e-9  # area in mm^2, below this an outline counts as degenerate
ANGLE_TOL_DEG = 1e-4  # two angles in degrees count as equal
KEY_DIGITS = 6  # rounding of coordinates and angles for cache keys and signatures
FAR_AWAY = 1e6  # "infinite" z limit of obstacles (mm)


def is_finite_number(value: Any) -> bool:
    """True for finite int or float values. bool does not count as a number."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_angle_deg(angle_deg: float) -> float:
    """Map an angle in degrees to [0, 360), rounded for stable comparisons."""
    a = round(angle_deg % 360.0, KEY_DIGITS)
    return 0.0 if a >= 360.0 else a
