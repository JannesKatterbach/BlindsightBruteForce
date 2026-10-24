"""Import von Motorgeometrie aus SVG.

Die Kontur wird in dieselbe MotorSpec ueberfuehrt wie eine manuelle Eingabe (outline als konvexes Polygon,
width und depth als Bounding Box). Manuelle, gezeichnete und importierte Motoren nutzen daher denselben
Kollisions und Optimierungsalgorithmus.

Regel. Ist der Massstab nicht eindeutig (kein width mit Einheit zusammen mit viewBox), wird ScaleRequired
geworfen. Es wird nie eine Groesse geraten.

Unterstuetzt. Genau ein <rect>, <polygon>, <polyline> oder <path> mit Geraden (M L H V Z, absolut und relativ).
Pfade mit Kurven (C S Q T A) werden abgewiesen, statt Kontrollpunkte still als Ecken zu lesen.
Nicht konvexe Konturen werden durch ihre konvexe Huelle ersetzt (konservativ) und das wird gemeldet.
Das SVG hat Y nach unten, im Motorsystem zeigt Y nach oben (die Kontur wird gespiegelt und um den
Mittelpunkt der Bounding Box zentriert).
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import MotorSpec
from .geometry import convex_hull, polygon_area
from .units import LENGTH_UNITS, is_finite_number

PT_MM = 25.4 / 72.0  # Punkt
PC_MM = 25.4 / 6.0  # Pica
CONVEX_AREA_RATIO = 0.9999  # Flaeche der Kontur relativ zur Huelle, ab der sie als konvex gilt
LINE_COMMANDS = "MLHVZ"


class ScaleRequired(ValueError):
    """Der Massstab des SVG ist nicht eindeutig. Der Nutzer muss mm pro SVG Einheit angeben."""


class SvgImportError(ValueError):
    """SVG nicht lesbar oder nicht unterstuetzt (verstaendliche Meldung)."""


@dataclass
class ImportedOutline:
    outline: list[list[float]]  # konvex, zentriert, Y nach oben, in mm
    width: float
    depth: float
    was_convex: bool
    notes: list[str] = field(default_factory=list)


_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$")
_TOKEN = re.compile(r"([A-Za-z])|([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")


def _length_mm(text: Optional[str]) -> Optional[float]:
    """Laenge mit Einheit in mm. None, wenn die Einheit fehlt oder nicht eindeutig ist (px, %)."""
    if not text:
        return None
    m = _NUM.match(text)
    if not m:
        return None
    unit = m.group(2).lower()
    val = float(m.group(1))
    if unit in LENGTH_UNITS:
        return val * LENGTH_UNITS[unit]
    if unit == "pt":
        return val * PT_MM
    if unit == "pc":
        return val * PC_MM
    return None  # einheitenlos, px und % sind nicht eindeutig


def _path_points(d: str) -> list[tuple[float, float]]:
    """Eckpunkte eines Pfads aus Geraden. Andere Befehle fuehren zu SvgImportError."""
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
                raise SvgImportError("Pfad. Ungueltige Koordinaten")
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
                raise SvgImportError(
                    f"Pfadbefehl {cmd} wird nicht unterstuetzt (nur Geraden M L H V Z). "
                    "Kurven bitte vorher in Linien umwandeln"
                )
            if cmd.upper() == "Z":
                flush()
        else:
            nums.append(float(m.group(2)))
    flush()
    if not pts:
        raise SvgImportError("Pfad ohne Punkte")
    return pts


def _shape_points(e: ET.Element, tag: str) -> list[tuple[float, float]]:
    if tag == "rect":
        x, y = float(e.get("x", 0)), float(e.get("y", 0))
        w, h = float(e.get("width", 0)), float(e.get("height", 0))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if tag in ("polygon", "polyline"):
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", e.get("points", ""))]
        if len(nums) < 6 or len(nums) % 2:
            raise SvgImportError("Polygon mit zu wenigen oder ungueltigen Punkten")
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
    return _path_points(e.get("d", ""))


def _tag(e: ET.Element) -> str:
    return e.tag.split("}")[-1] if isinstance(e.tag, str) else ""


def outline_from_svg(svg_text: Any, mm_per_unit: Any = None) -> ImportedOutline:
    """Liest genau eine Kontur aus dem SVG Text. Rueckgabe in mm, zentriert, Y nach oben, konvex.

    mm_per_unit ist der Massstab. Ohne Angabe wird er aus width (mit Einheit) und viewBox bestimmt,
    sonst wird ScaleRequired geworfen."""
    if not isinstance(svg_text, str):
        raise SvgImportError("svg muss Text sein")
    if mm_per_unit is not None and (not is_finite_number(mm_per_unit) or mm_per_unit <= 0):
        raise SvgImportError("Der Massstab muss eine positive Zahl sein")
    try:
        root = ET.fromstring(svg_text)
    except (ET.ParseError, RecursionError, ValueError) as exc:
        raise SvgImportError(f"SVG nicht lesbar. {exc}") from exc
    tag = _tag
    scale = mm_per_unit
    notes: list[str] = []
    if scale is None:
        w_mm = _length_mm(root.get("width"))
        vb = root.get("viewBox")
        if w_mm is None or not vb:
            raise ScaleRequired(
                "Der Massstab des SVG ist nicht eindeutig (width mit Einheit und viewBox fehlen). Bitte mm pro SVG Einheit angeben."
            )
        try:
            vbw = float(re.split(r"[ ,]+", vb.strip())[2])
        except (IndexError, ValueError):
            raise ScaleRequired("viewBox nicht lesbar. Bitte mm pro SVG Einheit angeben.") from None
        if vbw <= 0:
            raise ScaleRequired("viewBox ungueltig. Bitte mm pro SVG Einheit angeben.")
        scale = w_mm / vbw
    shapes = [e for e in root.iter() if tag(e) in ("rect", "polygon", "polyline", "path")]
    if len(shapes) != 1:
        raise SvgImportError(f"Erwartet genau eine Kontur (rect, polygon, polyline oder path), gefunden {len(shapes)}")
    if shapes[0].get("transform"):
        notes.append("Das Element hat eine transform Angabe, sie wird ignoriert.")
    try:
        raw = _shape_points(shapes[0], tag(shapes[0]))
    except ValueError as exc:
        if isinstance(exc, SvgImportError):
            raise
        raise SvgImportError(f"Kontur nicht lesbar. {exc}") from exc
    xs, ys = [p[0] for p in raw], [p[1] for p in raw]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    pts = [((x - cx) * scale, -(y - cy) * scale) for x, y in raw]
    hull = convex_hull(pts)
    if len(hull) < 3:
        raise SvgImportError("Kontur hat keine Flaeche")
    area_raw = polygon_area(pts)
    area_hull = polygon_area(hull)
    convex = area_raw >= area_hull * CONVEX_AREA_RATIO
    if not convex:
        notes.append("Die Kontur ist nicht konvex und wird durch ihre konvexe Huelle ersetzt.")
    w = (max(xs) - min(xs)) * scale
    d = (max(ys) - min(ys)) * scale
    if w <= 0 or d <= 0:
        raise SvgImportError("Kontur hat keine Flaeche")
    return ImportedOutline([[x, y] for x, y in hull], w, d, convex, notes)


def motor_outline_from_svg(svg_text: str, mm_per_unit: Optional[float] = None) -> tuple[float, float]:
    """Kompatibel. Breite und Tiefe der Kontur in mm."""
    o = outline_from_svg(svg_text, mm_per_unit)
    return o.width, o.depth


def motor_from_svg(svg_text: str, height: float, mm_per_unit: Optional[float] = None, base: Optional[MotorSpec] = None) -> MotorSpec:
    """Erzeugt eine MotorSpec. Hoehe (Z) und Zahnraddaten kommen aus base, SVG liefert den Grundriss."""
    o = outline_from_svg(svg_text, mm_per_unit)
    spec = copy.deepcopy(base) if base is not None else MotorSpec()  # base bleibt unveraendert
    spec.width, spec.depth, spec.height = o.width, o.depth, height
    spec.outline = o.outline
    return spec
