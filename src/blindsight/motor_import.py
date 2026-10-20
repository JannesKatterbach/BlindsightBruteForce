"""Import von Motorgeometrie aus SVG (Schnittstelle, erste Version).

Die Kontur wird in dieselbe MotorSpec ueberfuehrt wie eine manuelle Eingabe. Damit
nutzen manuelle und importierte Motoren denselben Kollisions und Optimierungsalgorithmus.

Regel. Ist der Massstab nicht eindeutig (keine width/height mit Einheit, kein viewBox
Verhaeltnis, das dazu passt), wird ScaleRequired geworfen. Es wird nie eine Groesse geraten.
Erste Version. Unterstuetzt wird ein einzelnes <rect> beziehungsweise ein achsparalleles
Rechteck als <path>/<polygon>. Die Kontur wird auf ihre Bounding Box abgebildet.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from .config import MotorSpec
from .units import LENGTH_UNITS


class ScaleRequired(ValueError):
    """Der Massstab des SVG ist nicht eindeutig. Der Nutzer muss mm pro SVG Einheit angeben."""


class SvgImportError(ValueError):
    pass


_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$")


def _length_mm(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = _NUM.match(text)
    if not m:
        return None
    unit = m.group(2).lower()
    val = float(m.group(1))
    if unit in LENGTH_UNITS:
        return val * LENGTH_UNITS[unit]
    if unit == "":
        return None  # einheitenlos, nicht eindeutig
    if unit == "pt":
        return val * 25.4 / 72.0
    if unit == "pc":
        return val * 25.4 / 6.0
    if unit == "px":
        return None  # px ist je nach Programm 90 oder 96 dpi, nicht eindeutig
    return None


def motor_outline_from_svg(svg_text: str, mm_per_unit: Optional[float] = None) -> tuple[float, float]:
    """Liefert (Breite, Tiefe) in mm der Kontur im SVG."""
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise SvgImportError(f"SVG nicht lesbar. {exc}") from exc
    ns = lambda t: t.split("}")[-1]
    w_mm = _length_mm(root.get("width"))
    vb = root.get("viewBox")
    scale = mm_per_unit
    if scale is None:
        if w_mm is not None and vb:
            vbw = float(re.split(r"[ ,]+", vb.strip())[2])
            scale = w_mm / vbw
        else:
            raise ScaleRequired(
                "Der Massstab des SVG ist nicht eindeutig (width mit Einheit und viewBox fehlen). "
                "Bitte mm pro SVG Einheit angeben."
            )
    shapes = [e for e in root.iter() if ns(e.tag) in ("rect", "polygon")]
    if len(shapes) != 1:
        raise SvgImportError("Erwartet genau ein <rect> oder <polygon> als Motorkontur")
    e = shapes[0]
    if ns(e.tag) == "rect":
        w, h = float(e.get("width", 0)), float(e.get("height", 0))
    else:
        pts = [tuple(map(float, p.split(","))) for p in e.get("points", "").split()]
        if len(pts) < 3:
            raise SvgImportError("Polygon ohne Punkte")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or h <= 0:
        raise SvgImportError("Kontur hat keine Flaeche")
    return w * scale, h * scale


def motor_from_svg(svg_text: str, height: float, mm_per_unit: Optional[float] = None, base: Optional[MotorSpec] = None) -> MotorSpec:
    """Erzeugt eine MotorSpec. Hoehe (Z) und Zahnraddaten kommen aus base, SVG liefert nur den Grundriss."""
    w, d = motor_outline_from_svg(svg_text, mm_per_unit)
    spec = MotorSpec(**(base.__dict__ if base else {}))
    spec.width, spec.depth, spec.height = w, d, height
    return spec
