"""Zentrale Definition der Masseinheiten, Toleranzen und Zahlpruefungen.

Intern wird ausschliesslich in Millimetern (mm) gerechnet. Winkel stehen in der
Konfiguration in Grad, im Rechenkern (geometry.py) in Radiant. Die Web UI
rechnet Eingaben in cm oder inch mit derselben Tabelle um (sie bekommt sie ueber
``/api/schema``).

Toleranzen sind hier gesammelt, damit gleiche Begriffe ueberall gleich verglichen
werden. Wer eine Toleranz aendert, aendert sie fuer das ganze Programm.
"""

from __future__ import annotations

import math
from typing import Any

MM = 1.0
LENGTH_UNITS = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "mil": 0.0254,
}
UI_LENGTH_UNITS = ("mm", "cm", "in")  # in der Oberflaeche waehlbar

# Numerische Toleranzen
EPS = 1e-9  # allgemeiner Vergleich von Laengen in mm (Rundungsrauschen)
EPS_AREA = 1e-9  # Flaeche in mm^2, darunter gilt eine Kontur als flaechenlos
ANGLE_TOL_DEG = 1e-4  # zwei Winkel in Grad gelten als gleich
KEY_DIGITS = 6  # Rundung von Koordinaten und Winkeln fuer Cache Schluessel und Signaturen
FAR_AWAY = 1e6  # "unendlich" fuer Z Grenzen von Hindernissen (mm)


def is_finite_number(value: Any) -> bool:
    """True fuer int oder float, die endlich sind. bool zaehlt nicht als Zahl."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_angle_deg(angle_deg: float) -> float:
    """Winkel in Grad auf [0, 360) abbilden, gerundet fuer stabile Vergleiche."""
    a = round(angle_deg % 360.0, KEY_DIGITS)
    return 0.0 if a >= 360.0 else a


def to_mm(value: float, unit: str = "mm") -> float:
    """Rechnet einen Wert der angegebenen Einheit in Millimeter um."""
    try:
        return float(value) * LENGTH_UNITS[unit]
    except KeyError:
        raise ValueError(f"Unbekannte Längeneinheit '{unit}'. Erlaubt. {sorted(LENGTH_UNITS)}") from None


def from_mm(value_mm: float, unit: str = "mm") -> float:
    """Rechnet Millimeter in die angegebene Einheit um."""
    try:
        return float(value_mm) / LENGTH_UNITS[unit]
    except KeyError:
        raise ValueError(f"Unbekannte Längeneinheit '{unit}'. Erlaubt. {sorted(LENGTH_UNITS)}") from None


def deg2rad(deg: float) -> float:
    return math.radians(deg)


def rad2deg(rad: float) -> float:
    return math.degrees(rad)
