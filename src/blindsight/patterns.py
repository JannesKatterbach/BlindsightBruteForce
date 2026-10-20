"""Kandidatengenerierung. Regelmaessige Muster fuer Stangenpositionen."""

from __future__ import annotations

import math
from typing import Iterable

Rect = tuple[float, float, float, float]


def pattern_points(kind: str, pitch: float, region: Rect) -> list[tuple[float, float]]:
    """Gitterpunkte in region = (x0, y0, x1, y1), symmetrisch zur Mitte der Region angeordnet.

    square  Quadratraster
    hex_x   hexagonal, Reihen entlang x, jede zweite Reihe um pitch/2 versetzt
    hex_y   hexagonal, Spalten entlang y, jede zweite Spalte um pitch/2 versetzt
    """
    x0, y0, x1, y1 = region
    if x1 < x0 or y1 < y0 or pitch <= 0:
        return []
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    pts: list[tuple[float, float]] = []
    eps = 1e-9
    if kind == "square":
        nx = int(math.floor((x1 - x0) / pitch + eps))
        ny = int(math.floor((y1 - y0) / pitch + eps))
        ox = cx - nx * pitch / 2.0
        oy = cy - ny * pitch / 2.0
        for j in range(ny + 1):
            for i in range(nx + 1):
                pts.append((ox + i * pitch, oy + j * pitch))
    elif kind == "hex_x":
        rs = pitch * math.sqrt(3) / 2.0
        ny = int(math.floor((y1 - y0) / rs + eps))
        oy = cy - ny * rs / 2.0
        for j in range(ny + 1):
            shift = (pitch / 2.0) if j % 2 else 0.0
            width = (x1 - x0) - shift
            if width < -eps:
                continue
            nx = int(math.floor(width / pitch + eps))
            ox = x0 + shift + (width - nx * pitch) / 2.0
            for i in range(nx + 1):
                pts.append((ox + i * pitch, oy + j * rs))
    elif kind == "hex_y":
        rs = pitch * math.sqrt(3) / 2.0
        nx = int(math.floor((x1 - x0) / rs + eps))
        ox = cx - nx * rs / 2.0
        for i in range(nx + 1):
            shift = (pitch / 2.0) if i % 2 else 0.0
            height = (y1 - y0) - shift
            if height < -eps:
                continue
            ny = int(math.floor(height / pitch + eps))
            oy = y0 + shift + (height - ny * pitch) / 2.0
            for j in range(ny + 1):
                pts.append((ox + i * rs, oy + j * pitch))
    else:
        raise ValueError(f"Unbekanntes Muster {kind}")
    return pts


ORDERS = ("euclid", "box1", "box1.5", "box0.67")


def order_points(points: Iterable[tuple[float, float]], center: tuple[float, float], order: str):
    """Sortiert Punkte von der Mitte nach aussen, damit ein kompakter Block entsteht.

    euclid  rundlicher Block
    boxA    rechteckiger Block mit Seitenverhaeltnis A (Breite / Hoehe)
    """
    cx, cy = center
    if order == "euclid":
        key = lambda p: (math.hypot(p[0] - cx, p[1] - cy), p[1], p[0])
    else:
        a = float(order[3:])
        key = lambda p: (max(abs(p[0] - cx) / a, abs(p[1] - cy)), math.hypot(p[0] - cx, p[1] - cy), p[1], p[0])
    return sorted(points, key=key)
