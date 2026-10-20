"""Zentrale Definition der Masseinheiten.

Intern wird ausschliesslich in Millimetern (mm) und Grad (Winkel in der
Konfiguration) beziehungsweise Radiant (Rechenkern) gerechnet. Die UI darf
andere Einheiten anzeigen, rechnet aber ueber diese Modul um.
"""

from __future__ import annotations

import math

MM = 1.0
LENGTH_UNITS = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "mil": 0.0254,
}

# Numerische Toleranz fuer Gleitkomma Vergleiche in mm.
EPS = 1e-9


def to_mm(value: float, unit: str = "mm") -> float:
    """Rechnet einen Wert der angegebenen Einheit in Millimeter um."""
    try:
        return float(value) * LENGTH_UNITS[unit]
    except KeyError:
        raise ValueError(f"Unbekannte Laengeneinheit '{unit}'. Erlaubt: {sorted(LENGTH_UNITS)}") from None


def from_mm(value_mm: float, unit: str = "mm") -> float:
    """Rechnet Millimeter in die angegebene Einheit um."""
    try:
        return float(value_mm) / LENGTH_UNITS[unit]
    except KeyError:
        raise ValueError(f"Unbekannte Laengeneinheit '{unit}'. Erlaubt: {sorted(LENGTH_UNITS)}") from None


def deg2rad(deg: float) -> float:
    return math.radians(deg)


def rad2deg(rad: float) -> float:
    return math.degrees(rad)
