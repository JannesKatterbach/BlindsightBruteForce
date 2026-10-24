"""Optimizer with a repeating pattern (tile).

A tile is a rectangle of width x height mm holding ``search.tile_rods`` rods. The rods sit on a regular
sub grid inside the tile (rows x columns, optionally every second row shifted by half a spacing), so the
rods are distributed evenly. Plane, motor angle and centre distance of every rod are searched by brute
force (backtracking) and repeat with the tile. Copies of the tile are placed edge to edge.

Search
  1. Validity. The units of one tile are checked against all copies of the tile within reach, in an
     unbounded helper model without obstacles. If one tile is valid, the whole infinite lattice is valid.
  2. Tile size. A missing width or height is searched on the ``search.tile_step`` raster. For every sub
     grid shape (and aspect ratio, when both are missing) a binary search finds the smallest spacing with
     a valid assignment. The result is the smallest tile found, it is not proven to be the smallest.
  3. Placement. Only whole tiles are placed. Every unit of a tile must satisfy all rules of the real
     build area (edge, obstacles, mounting zones, capacity), otherwise the whole tile is skipped.
     compact takes the tiles closest to the centre, spread distributes tiles evenly over the area.
     The number of rods is the target count rounded down to whole tiles.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..i18n import tr
from ..layout import Counter, Layout, Placement
from ..model import Model
from ..patterns import ORDERS, order_points
from .base import STATUS_INFEASIBLE, OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import Halt, SearchBase
from .registry import register

HELPER_AREA = 1e5  # mm, build area of the unbounded helper model
ASPECTS = (1.0, 0.8, 1.25, 0.65, 1.55, 0.5, 2.0)  # spacing_y / spacing_x tried when both sizes are free
NODE_LIMIT = 2500  # assignment nodes per evaluated tile size
SEARCH_SHARE = 0.7  # share of the time limit for the tile search, the rest places tiles
PHASES = 3  # lattice shifts per direction tried when placing tiles
TILES_TO_PLACE = 3  # best tiles that are placed into the build area
SIZE_DIGITS = 6


@dataclass(frozen=True)
class TileShape:
    """Arrangement of the rods inside a tile."""

    rows: int
    cols: int
    offset: bool  # every second row shifted by half a column spacing

    @property
    def rods(self) -> int:
        return self.rows * self.cols

    def positions(self, spacing_x: float, spacing_y: float) -> list[tuple[float, float]]:
        """Rod positions inside the tile (origin at the bottom left corner of the tile)."""
        out = []
        for row in range(self.rows):
            shift = spacing_x / 2.0 if self.offset and row % 2 else 0.0
            out.extend((col * spacing_x + shift, row * spacing_y) for col in range(self.cols))
        return out


@dataclass(frozen=True)
class TileUnit:
    u: float  # position inside the tile (mm)
    v: float
    plane: int
    angle: float
    cd: Optional[float] = None


@dataclass
class Tile:
    shape: TileShape
    width: float
    height: float
    units: list[TileUnit]
    min_gap: float = math.inf

    @property
    def area_per_rod(self) -> float:
        return self.width * self.height / len(self.units)

    def placements(self, x: float, y: float) -> list[Placement]:
        """Units of the tile with its bottom left corner at (x, y)."""
        return [Placement(x + t.u, y + t.v, t.plane, t.angle, t.cd) for t in self.units]

    def resized(self, width: float, height: float, stretch: bool) -> "Tile":
        """Same assignment in a larger period. stretch scales the rod positions, otherwise they keep their place."""
        fx, fy = (width / self.width, height / self.height) if stretch else (1.0, 1.0)
        units = [TileUnit(t.u * fx, t.v * fy, t.plane, t.angle, t.cd) for t in self.units]
        return Tile(self.shape, width, height, units, self.min_gap)

    def as_dict(self, origins: list[tuple[float, float]]) -> dict:
        return {
            "width": self.width, "height": self.height, "rods": len(self.units),
            "rows": self.shape.rows, "cols": self.shape.cols, "offset": self.shape.offset,
            "units": [{"x": t.u, "y": t.v, "plane": t.plane, "angle": t.angle, **({"cd": t.cd} if t.cd is not None else {})}
                      for t in self.units],
            "origins": [[x, y] for x, y in origins],
        }


def tile_shapes(rods: int) -> list[TileShape]:
    """All sub grids with rows x cols = rods, nearly square ones first."""
    shapes = []
    for rows in range(1, rods + 1):
        if rods % rows:
            continue
        cols = rods // rows
        shapes.append(TileShape(rows, cols, False))
        if rows >= 2:
            shapes.append(TileShape(rows, cols, True))
    return sorted(shapes, key=lambda s: (abs(s.rows - s.cols), s.offset))


class PeriodicChecker:
    """Checks tiles against their own copies in an unbounded model (no edge, obstacles or zones)."""

    def __init__(self, model: Model, counter: Counter):
        project = copy.deepcopy(model.project)
        project.bounds.width = project.bounds.height = HELPER_AREA
        project.bounds.edge_margin = 0.0
        project.obstacles = []
        project.stack.mount_zones = {}
        project.stack.max_per_plane = {}
        self.model = Model(project)
        self.counter = counter
        self.center = HELPER_AREA / 2.0
        self.reach = Layout(self.model).reach
        self.rod_pitch = model.project.rod.diameter + model.gap

    def _offsets(self, width: float, height: float) -> list[tuple[float, float]]:
        """Lattice translations (without 0, 0) at which a copy can still touch the tile."""
        radius = self.reach + math.hypot(width, height)
        ni, nj = math.ceil(radius / width), math.ceil(radius / height)
        return [(i * width, j * height) for i in range(-ni, ni + 1) for j in range(-nj, nj + 1)
                if (i or j) and math.hypot(i * width, j * height) <= radius]

    def rods_fit(self, positions: list[tuple[float, float]], width: float, height: float) -> bool:
        """Quick test with the rods only. Rods of all units overlap in height, so they need the full pitch."""
        offsets = [(0.0, 0.0)] + self._offsets(width, height)
        for i, (x1, y1) in enumerate(positions):
            for j, (x2, y2) in enumerate(positions):
                for dx, dy in offsets:
                    if (i, dx, dy) == (j, 0.0, 0.0):
                        continue
                    if math.hypot(x2 + dx - x1, y2 + dy - y1) < self.rod_pitch - 1e-9:
                        return False
        return True

    def assign(self, positions: list[tuple[float, float]], width: float, height: float,
               options: list[list[tuple[int, float, Optional[float]]]], halt: Halt,
               node_limit: int = NODE_LIMIT) -> tuple[Optional[list[TileUnit]], float, bool]:
        """Backtracking over the options of every rod. Returns (units or None, smallest gap, search complete)."""
        if not self.rods_fit(positions, width, height):
            return None, 0.0, True
        layout = Layout(self.model, self.counter)
        offsets = self._offsets(width, height)
        c = self.center
        chosen: list[TileUnit] = []
        gaps: list[float] = []
        state = {"nodes": 0, "complete": True}

        def place(index: int) -> bool:
            if index == len(positions):
                return True
            u, v = positions[index]
            for plane, angle, cd in options[index]:
                state["nodes"] += 1
                if state["nodes"] > node_limit or halt():
                    state["complete"] = False
                    return False
                center = Placement(c + u, c + v, plane, angle, cd)
                if not layout.check(center).ok:  # against earlier rods and their copies
                    continue
                copies = [layout.add(Placement(c + u + dx, c + v + dy, plane, angle, cd)) for dx, dy in offsets]
                result = layout.check(center)  # now also against its own copies
                if result.ok:
                    uid = layout.add(center)
                    chosen.append(TileUnit(u, v, plane, angle, cd))
                    gaps.append(result.min_gap)
                    if place(index + 1):
                        return True
                    chosen.pop()
                    gaps.pop()
                    layout.remove(uid)
                for copy_id in copies:
                    layout.remove(copy_id)
                if not state["complete"]:
                    return False
            return False

        found = place(0)
        return (list(chosen) if found else None), (min(gaps) if gaps else math.inf), state["complete"]

    def verify(self, tile: Tile, halt: Halt) -> bool:
        """True, if the fixed assignment of the tile is valid with the tile's period."""
        positions = [(t.u, t.v) for t in tile.units]
        options = [[(t.plane, t.angle, t.cd)] for t in tile.units]
        units, _, _ = self.assign(positions, tile.width, tile.height, options, halt)
        return units is not None


@register
class PeriodicTileOptimizer(Optimizer):
    name = "periodic_tile"
    supports_parallel = False  # deterministic, further seeds do not help

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        rods = se.tile_rods
        target = model.project.target_count
        if target < rods:
            res.status = STATUS_INFEASIBLE
            res.messages.append(tr("tile.target_too_small", target=target, rods=rods))
            res.optimality_note = tr("exhaustive.not_run")
            res.elapsed = stop.elapsed
            return res
        search = TileSearch(model, counter, stop, random.Random(se.seed), progress)
        tiles = search.find_tiles(lambda: search.halted() or stop.elapsed > se.time_limit_s * SEARCH_SHARE)
        for tile in tiles[:TILES_TO_PLACE]:
            if search.halted():
                break
            search.place(tile)
        out = finish(res, search, stop, counter)
        out.messages[:0] = search.notes(tiles)
        return out


class TileSearch(SearchBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checker = PeriodicChecker(self.model, self.counter)
        self.step = self.se.tile_step
        self.rods = self.se.tile_rods
        self._cache: dict[tuple, Optional[Tile]] = {}
        self.incomplete = False

    # -- Tile search ----------------------------------------------------------------
    def _options(self, index: int) -> list[tuple[int, float, Optional[float]]]:
        """Plane, angle and centre distance options of rod index (planes start rotated for balance)."""
        start = index % len(self.usable)
        planes = self.usable[start:] + self.usable[:start]
        return [(plane, angle, cd) for plane in planes for angle, cd in self.options_for(plane)]

    def evaluate(self, shape: TileShape, spacing_x: float, spacing_y: float, halt: Halt) -> Optional[Tile]:
        """Valid tile with this sub grid and spacing, or None."""
        key = (shape, round(spacing_x, SIZE_DIGITS), round(spacing_y, SIZE_DIGITS))
        if key in self._cache:
            return self._cache[key]
        width, height = shape.cols * spacing_x, shape.rows * spacing_y
        positions = shape.positions(spacing_x, spacing_y)
        options = [self._options(i) for i in range(len(positions))]
        units, gap, complete = self.checker.assign(positions, width, height, options, halt)
        self.incomplete = self.incomplete or not complete
        tile = Tile(shape, width, height, units, gap) if units else None
        if complete or tile:
            self._cache[key] = tile
        self.report(tr("progress.tile_valid" if tile else "progress.tile_invalid", rows=shape.rows, cols=shape.cols,
                       width=width, height=height))
        return tile

    def _snap(self, value: float) -> float:
        return round(max(self.step, math.ceil(value / self.step - 1e-9) * self.step), SIZE_DIGITS)

    def _smallest(self, feasible, lo: float, hi: float, halt: Halt) -> Optional[tuple[float, Tile]]:
        """Binary search for the smallest raster value in [lo, hi] for which feasible(value) returns a tile."""
        lo, hi = self._snap(lo), self._snap(hi)
        best_tile = feasible(hi)
        if best_tile is None:
            return None
        best = hi
        lo_i, hi_i = round(lo / self.step), round(hi / self.step)
        while lo_i < hi_i and not halt():
            mid_i = (lo_i + hi_i) // 2
            tile = feasible(round(mid_i * self.step, SIZE_DIGITS))
            if tile is not None:
                hi_i, best, best_tile = mid_i, round(mid_i * self.step, SIZE_DIGITS), tile
            else:
                lo_i = mid_i + 1
        return best, best_tile

    def _upper_spacing(self) -> float:
        """At this spacing units can no longer collide, so any valid single unit assignment works."""
        return self.checker.reach + self.step

    def smallest_tile(self, shape: TileShape, halt: Halt) -> Optional[Tile]:
        width, height = self.se.tile_width, self.se.tile_height
        if width is not None and height is not None:
            return self.evaluate(shape, width / shape.cols, height / shape.rows, halt)
        lo, hi = self.checker.rod_pitch / 2.0, self._upper_spacing()
        if width is not None:
            sx = width / shape.cols
            found = self._smallest(lambda sy: self.evaluate(shape, sx, sy, halt), lo, hi, halt)
            return found[1] if found else None
        if height is not None:
            sy = height / shape.rows
            found = self._smallest(lambda sx: self.evaluate(shape, sx, sy, halt), lo, hi, halt)
            return found[1] if found else None
        best: Optional[Tile] = None
        for aspect in ASPECTS:
            if halt():
                break
            found = self._smallest(lambda sx: self.evaluate(shape, sx, self._snap(sx * aspect), halt), lo, hi, halt)
            if found and (best is None or found[1].area_per_rod < best.area_per_rod - 1e-9):
                best = found[1]
        return best

    def find_tiles(self, halt: Halt) -> list[Tile]:
        """Smallest tile per sub grid shape, sorted by area per rod (then largest gap)."""
        self.phase = tr("phase.tile_search")
        tiles = []
        for shape in tile_shapes(self.rods):
            if halt():
                break
            tile = self.smallest_tile(shape, halt)
            if tile is not None:
                tiles.append(tile)
        return sorted(tiles, key=lambda t: (round(t.area_per_rod, 3), -t.min_gap))

    # -- Placement --------------------------------------------------------------------
    def _try_tile(self, layout: Layout, tile: Tile, x: float, y: float) -> bool:
        """Adds all units of the tile at (x, y) or none of them."""
        added = []
        for placement in tile.placements(x, y):
            if not layout.check(placement).ok:
                for uid in added:
                    layout.remove(uid)
                return False
            added.append(layout.add(placement))
        return True

    def _origins(self, tile: Tile, phase_x: float, phase_y: float) -> list[tuple[float, float]]:
        """Tile corners of the lattice whose rods can lie in the allowed region."""
        x0, y0, x1, y1 = self.region
        start_x = x0 + phase_x - tile.width
        start_y = y0 + phase_y - tile.height
        nx = int((x1 - start_x) / tile.width) + 1
        ny = int((y1 - start_y) / tile.height) + 1
        return [(start_x + i * tile.width, start_y + j * tile.height) for j in range(ny + 1) for i in range(nx + 1)]

    def _build(self, tile: Tile, origins: list[tuple[float, float]], tiles_needed: int) -> tuple[list[Placement], list]:
        layout = Layout(self.model, self.counter)
        used = []
        for x, y in origins:
            if len(used) >= tiles_needed or self.halted():
                break
            if self._try_tile(layout, tile, x, y):
                used.append((x, y))
        return layout.placements(), used

    def place(self, tile: Tile) -> None:
        """Puts whole tiles into the build area and keeps the resulting layouts."""
        self.phase = tr("phase.tile_place")
        tiles_needed = self.target // self.rods
        if self.se.layout_goal == "spread":
            self._place_spread(tile, tiles_needed)
            return
        cx, cy = self.center
        for i in range(PHASES):
            for j in range(PHASES):
                origins = self._origins(tile, tile.width * i / PHASES, tile.height * j / PHASES)
                centers = {(x + tile.width / 2.0, y + tile.height / 2.0): (x, y) for x, y in origins}
                for order in ORDERS:
                    if self.halted():
                        return
                    ordered = [centers[c] for c in order_points(list(centers), (cx, cy), order)]
                    placements, used = self._build(tile, ordered, tiles_needed)
                    self.consider(placements, tile.as_dict(used))
            self.report(tr("progress.tiles_placed", i=i + 1, n=PHASES))

    def _grid_counts(self, tiles_needed: int, width: float, height: float) -> tuple[int, int]:
        """Columns and rows of tiles for an even spread (as close to the area's aspect as possible)."""
        best = None
        for cols in range(1, tiles_needed + 1):
            rows = math.ceil(tiles_needed / cols)
            waste = cols * rows - tiles_needed
            skew = abs(math.log((width / cols) / (height / rows))) if width > 0 and height > 0 else 0.0
            key = (waste > 0, skew + 0.5 * waste)
            if best is None or key < best[0]:
                best = (key, cols, rows)
        return best[1], best[2]

    def _place_spread(self, tile: Tile, tiles_needed: int) -> None:
        x0, y0, x1, y1 = self.region
        cols, rows = self._grid_counts(tiles_needed, x1 - x0, y1 - y0)
        pitch_x = max(tile.width, (x1 - x0) / cols)
        pitch_y = max(tile.height, (y1 - y0) / rows)
        for stretch in (True, False):
            candidate = tile.resized(pitch_x, pitch_y, stretch)
            if not self.checker.verify(candidate, self.halted):
                continue
            # Centre the tile grid in the region (rods of a tile sit in its lower left part when not stretched)
            used_w = (cols - 1) * pitch_x + max(t.u for t in candidate.units)
            used_h = (rows - 1) * pitch_y + max(t.v for t in candidate.units)
            sx, sy = x0 + max(0.0, (x1 - x0 - used_w) / 2.0), y0 + max(0.0, (y1 - y0 - used_h) / 2.0)
            origins = [(sx + i * pitch_x, sy + j * pitch_y) for j in range(rows) for i in range(cols)]
            placements, used = self._build(candidate, origins, tiles_needed)
            self.consider(placements, candidate.as_dict(used))
        self.place_compact_fallback(tile, tiles_needed)

    def place_compact_fallback(self, tile: Tile, tiles_needed: int) -> None:
        """Smallest tile edge to edge from the centre (always available as a comparison)."""
        origins = self._origins(tile, 0.0, 0.0)
        cx, cy = self.center
        centers = {(x + tile.width / 2.0, y + tile.height / 2.0): (x, y) for x, y in origins}
        ordered = [centers[c] for c in order_points(list(centers), (cx, cy), "euclid")]
        placements, used = self._build(tile, ordered, tiles_needed)
        self.consider(placements, tile.as_dict(used))

    # -- Notes --------------------------------------------------------------------------
    def notes(self, tiles: list[Tile]) -> list[str]:
        out = []
        if not tiles:
            out.append(tr("tile.none_found"))
            return out
        best = tiles[0]
        out.append(tr("tile.summary_offset" if best.shape.offset else "tile.summary", rods=len(best.units),
                      rows=best.shape.rows, cols=best.shape.cols, width=best.width, height=best.height))
        if self.se.tile_width is None or self.se.tile_height is None:
            out.append(tr("tile.not_proven"))
        remainder = self.target % self.rods
        if remainder:
            lower = self.target - remainder
            out.append(tr("tile.not_multiple", target=self.target, rods=self.rods, lower=lower, next=lower + self.rods))
        return out
