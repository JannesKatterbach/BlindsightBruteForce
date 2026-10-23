"""Kandidatengenerierung. Regelmaessige Muster fuer Stangenpositionen.

Erweitern. Ein neues Muster ist eine Funktion ``(pitch, region) -> Punkte`` und ein
Eintrag in ``PATTERNS``. Die Konfiguration prueft ``search.patterns`` gegen dieses
Register, der Optimierer ruft die Funktion ueber ``pattern_points`` auf.
Neue Reihenfolgen (wie ein Block um die Mitte gefuellt wird) sind ein Eintrag in ``ORDERS``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from .units import EPS

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1)
PointList = list[tuple[float, float]]

ROW_FACTOR_HEX = math.sqrt(3) / 2.0  # Reihenabstand eines Hexagonalgitters relativ zur Teilung


def _count(span: float, step: float) -> int:
    """Wie viele Schritte passen in die Strecke (Rundungsrauschen wird toleriert)."""
    return int(math.floor(span / step + EPS))


def _square(pitch: float, region: Rect) -> PointList:
    """Quadratraster, symmetrisch zur Mitte der Region."""
    x0, y0, x1, y1 = region
    nx, ny = _count(x1 - x0, pitch), _count(y1 - y0, pitch)
    ox = (x0 + x1) / 2.0 - nx * pitch / 2.0
    oy = (y0 + y1) / 2.0 - ny * pitch / 2.0
    return [(ox + i * pitch, oy + j * pitch) for j in range(ny + 1) for i in range(nx + 1)]


def _hex_rows(pitch: float, along: tuple[float, float], across: tuple[float, float]) -> list[tuple[float, float]]:
    """Hexagonalgitter in einem lokalen System (u entlang der Reihen, v quer dazu).

    Alle Reihen teilen einen Ursprung, jede zweite Reihe ist um pitch/2 versetzt. So haben alle
    Nachbarn exakt den Abstand pitch (gleichseitige Dreiecke)."""
    u0, u1 = along
    v0, v1 = across
    row_gap = pitch * ROW_FACTOR_HEX
    n_rows = _count(v1 - v0, row_gap)
    n_cols = _count(u1 - u0, pitch)
    v_start = (v0 + v1) / 2.0 - n_rows * row_gap / 2.0
    u_start = (u0 + u1) / 2.0 - n_cols * pitch / 2.0
    out = []
    for j in range(n_rows + 1):
        if j % 2 == 0:
            us = [u_start + i * pitch for i in range(n_cols + 1)]
        else:
            us = [u_start + pitch / 2.0 + i * pitch for i in range(n_cols)]
        out.extend((u, v_start + j * row_gap) for u in us)
    return out


def _hex_x(pitch: float, region: Rect) -> PointList:
    """Hexagonal, Reihen entlang x, jede zweite Reihe um pitch/2 versetzt."""
    x0, y0, x1, y1 = region
    return _hex_rows(pitch, (x0, x1), (y0, y1))


def _hex_y(pitch: float, region: Rect) -> PointList:
    """Hexagonal, Spalten entlang y, jede zweite Spalte um pitch/2 versetzt."""
    x0, y0, x1, y1 = region
    return [(u, v) for v, u in _hex_rows(pitch, (y0, y1), (x0, x1))]


PATTERNS: dict[str, Callable[[float, Rect], PointList]] = {
    "square": _square,
    "hex_x": _hex_x,
    "hex_y": _hex_y,
}

# Dichte relativ zum Quadratraster (Punkte pro Flaeche), fuer Abschaetzungen der Punktzahl
PATTERN_DENSITY = {"square": 1.0, "hex_x": 1.0 / ROW_FACTOR_HEX, "hex_y": 1.0 / ROW_FACTOR_HEX}


def pattern_points(kind: str, pitch: float, region: Rect) -> PointList:
    """Gitterpunkte des Musters ``kind`` in region = (x0, y0, x1, y1), zur Mitte der Region zentriert."""
    x0, y0, x1, y1 = region
    if x1 < x0 or y1 < y0 or pitch <= 0:
        return []
    try:
        generator = PATTERNS[kind]
    except KeyError:
        raise ValueError(f"Unbekanntes Muster {kind}") from None
    return generator(pitch, region)


def estimated_point_count(kind: str, pitch: float, region: Rect) -> float:
    """Grobe Abschaetzung der Punktzahl, ohne die Punkte zu erzeugen."""
    x0, y0, x1, y1 = region
    if pitch <= 0 or x1 < x0 or y1 < y0:
        return 0.0
    return (math.floor((x1 - x0) / pitch) + 1) * (math.floor((y1 - y0) / pitch) + 1) * PATTERN_DENSITY.get(kind, 1.0)


# ---------------------------------------------------------------------------
# Reihenfolge der Punkte. Ein Block waechst von der Mitte nach aussen.
#   ("euclid", None)   rundlicher Block (Abstand zur Mitte)
#   ("box", A)         rechteckiger Block mit Seitenverhaeltnis A (Breite / Hoehe)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Order:
    name: str
    shape: str  # "euclid" oder "box"
    aspect: float = 1.0


ORDER_TABLE = (
    Order("euclid", "euclid"),
    Order("box1", "box", 1.0),
    Order("box1.5", "box", 1.5),
    Order("box0.67", "box", 0.67),
)
ORDERS = tuple(o.name for o in ORDER_TABLE)  # Namen in fester Reihenfolge (die ersten zwei sind die schnellen)
_ORDER_BY_NAME = {o.name: o for o in ORDER_TABLE}


def order_points(points: Iterable[tuple[float, float]], center: tuple[float, float], order: str) -> PointList:
    """Sortiert Punkte von der Mitte nach aussen, damit ein kompakter Block entsteht."""
    cx, cy = center
    spec = _ORDER_BY_NAME[order]

    def radial(p):
        return math.hypot(p[0] - cx, p[1] - cy)

    def round_block(p):
        return (radial(p), p[1], p[0])

    def box_block(p):
        return (max(abs(p[0] - cx) / spec.aspect, abs(p[1] - cy)), radial(p), p[1], p[0])

    return sorted(points, key=round_block if spec.shape == "euclid" else box_block)
