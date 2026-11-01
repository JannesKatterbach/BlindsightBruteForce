"""Tiling of a repeating block (pattern mode 2a, periodic_tile).

A valid block is valid on the infinite lattice (see optimizers/periodic_tile.py), so it can be set side by
side as often as wanted. tile_project puts nx x ny blocks next to each other and fits a new board around
them. Housings and gears keep the keep out edge (bounds.edge_margin), the rods also the edge strip for motors
(bounds.rod_margin). Obstacles and mounting areas belong to the old board and are dropped.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .config import Project
from .errors import ValidationError
from .i18n import tr
from .layout import Placement
from .model import KIND_ROD, Model
from .units import is_finite_number

MAX_TILES = 400  # blocks per direction and in total, protection against huge requests
BOARD_SLACK = 1e-6  # mm, the fitted board is this much larger so that no part touches the edge exactly


class TilingError(ValidationError):
    """Invalid block or block count."""


def _block(tile: Any) -> tuple[float, float, list[dict]]:
    if not isinstance(tile, dict):
        raise TilingError(tr("tiling.bad_tile"))
    width, height, units = tile.get("width"), tile.get("height"), tile.get("units")
    ok = is_finite_number(width) and is_finite_number(height) and width > 0 and height > 0 and isinstance(units, list) and units
    if not ok or not all(isinstance(u, dict) and all(is_finite_number(u.get(k)) for k in ("x", "y", "angle"))
                         and isinstance(u.get("plane"), int) for u in units):
        raise TilingError(tr("tiling.bad_tile"))
    return float(width), float(height), units


def tile_placements(tile: Any, nx: int, ny: int) -> list[Placement]:
    """Units of nx x ny blocks, the first block at the origin."""
    width, height, units = _block(tile)
    if not (isinstance(nx, int) and isinstance(ny, int) and 1 <= nx <= MAX_TILES and 1 <= ny <= MAX_TILES and nx * ny <= MAX_TILES):
        raise TilingError(tr("tiling.bad_count", max=MAX_TILES))
    return [Placement(i * width + u["x"], j * height + u["y"], u["plane"], float(u["angle"]), u.get("cd"))
            for j in range(ny) for i in range(nx) for u in units]


def tile_project(project: Project, tile: Any, nx: int, ny: int, max_units: int = 10_000) -> tuple[Project, list[Placement], list]:
    """Board fitted around nx x ny blocks. Returns (project with the new board, placements on it, notes)."""
    placements = tile_placements(tile, nx, ny)
    if len(placements) > max_units:
        raise TilingError(tr("server.too_many_placements", max=max_units))
    model = Model(project)
    bounds = project.bounds
    rods_only = bounds.parts_in_bounds == "rods"
    parts_box = [math.inf, math.inf, -math.inf, -math.inf]
    rods_box = list(parts_box)
    for pl in placements:
        for part in model.unit_parts(-1, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
            if part.kind != KIND_ROD and rods_only:
                continue
            box = rods_box if part.kind == KIND_ROD else parts_box
            x0, y0, x1, y1 = part.prism.fp.bbox
            box[:] = [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
    edge, rod_edge = bounds.edge_margin + BOARD_SLACK, bounds.rod_margin + BOARD_SLACK
    shift, size = [], []
    for axis in (0, 1):
        lo = [rods_box[axis] - rod_edge] + ([parts_box[axis] - edge] if parts_box[axis] < math.inf else [])
        hi = [rods_box[axis + 2] + rod_edge] + ([parts_box[axis + 2] + edge] if parts_box[axis] < math.inf else [])
        shift.append(-min(lo))
        size.append(max(hi) - min(lo))
    out = copy.deepcopy(project)
    out.bounds.width, out.bounds.height = size
    notes = []
    if out.obstacles or out.stack.mount_zones:
        notes.append(tr("tiling.dropped"))
    out.obstacles = []
    out.stack.mount_zones = {}
    out.holes = None
    out.target_count = len(placements)
    moved = [Placement(p.x + shift[0], p.y + shift[1], p.plane, p.angle, p.cd) for p in placements]
    return out, moved, notes
