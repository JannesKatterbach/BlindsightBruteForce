"""Optimizer with a repeating hole pattern (UI name "Repeating pattern").

The holes of G0 lie on a regular lattice that is easy to drill. A lattice is a rectangular cell with one
or more holes that repeats edge to edge (``search.pattern``)
  square           cell a x a, 1 hole
  centered_square  "dice five", square with a centre hole, cell a·√2, 2 holes (all neighbours at a)
  hex              cell a x a·√3, 2 holes (six neighbours at a), hex_rotated is the same turned by 90 degrees
  staggered        rows with distance a, every second row shifted by a/2, row distance b (default dense
                   like circles, b = a·√3/2)
  rectangle        cell a x b, 1 hole
  custom           own tile from the hole pattern generator (search.custom_tile), fixed or scalable
  free             tile_rods rods on a sub grid inside a tile (rows x columns, optionally offset rows), the
                   spacings in x and y are searched independently (earlier behaviour)
a is ``search.pattern_pitch`` (distance to the nearest hole), b is ``search.pattern_pitch_y``. A missing
distance is searched on the ``search.tile_step`` raster.

Plane, motor angle and centre distance of every hole are searched by brute force (backtracking) for a
block of m x n cells and repeat with the block. Blocks are tried by ascending number of holes up to
``search.max_block_holes``, so the motor arrangement repeats as early as possible.

Search
  1. Validity. The units of one block are checked against all copies of the block within reach, in an
     unbounded helper model without obstacles. If one block is valid, the whole infinite lattice is valid,
     and so is every subset of it (removing units never creates a collision).
  2. Distance. For every block a binary search finds the smallest distance with a valid assignment. The
     result is the smallest distance found on the raster, it is not proven to be the smallest.
  3. Placement. Holes of the lattice are placed one by one, each must satisfy all rules of the real build
     area (edge, obstacles, mounting zones, capacity). The task (search.pattern_task) decides
       dense  holes closest to the centre at the smallest distance, target_count of them or as many as
              fit with search.pattern_fill
       count  the largest distance at which the target count fits, the lattice centred
       pitch  the given distance search.pattern_pitch, as many holes as fit
     The goals of the mode (few layers, small edge) choose among equally full placements.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from typing import Callable, Optional

from ..i18n import tr
from ..layout import Counter, Layout, Placement
from ..model import Model
from ..patterns import ORDERS, order_points
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import Halt, SearchBase
from .registry import register

HELPER_AREA = 1e5  # mm, build area of the unbounded helper model
ASPECTS = (1.0, 0.8, 1.25, 0.65, 1.55, 0.5, 2.0)  # spacing_y / spacing_x tried for the pattern free
NODE_LIMIT = 2500  # assignment nodes per evaluated block and distance, per hole of the block
SEARCH_SHARE = 0.7  # share of the time limit for the lattice search, the rest places holes
PHASES = 3  # lattice shifts per direction tried when placing compact
TILES_TO_PLACE = 3  # best blocks that are placed into the build area
FILL_TARGET = 10 ** 6  # target while filling the board, replaced by the largest count afterwards
SPREAD_TRIES = 8  # larger distances tried for the goal spread
SIZE_DIGITS = 6
SQRT2, SQRT3 = math.sqrt(2.0), math.sqrt(3.0)
Point = tuple[float, float]


@dataclass(frozen=True)
class Cell:
    """Rectangular lattice cell with its holes (mm, origin at the bottom left corner of the cell)."""

    width: float
    height: float
    holes: tuple[Point, ...]

    def nearest_distance(self) -> float:
        """Smallest distance between two holes of the infinite lattice."""
        best = math.inf
        for i, (x1, y1) in enumerate(self.holes):
            for j, (x2, y2) in enumerate(self.holes):
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        if i == j and not di and not dj:
                            continue
                        best = min(best, math.hypot(x2 + di * self.width - x1, y2 + dj * self.height - y1))
        return best


@dataclass(frozen=True)
class TileShape:
    """Pattern free. Arrangement of the rods inside a tile."""

    rows: int
    cols: int
    offset: bool  # every second row shifted by half a column spacing

    @property
    def rods(self) -> int:
        return self.rows * self.cols

    def positions(self, spacing_x: float, spacing_y: float) -> list[Point]:
        """Rod positions inside the tile (origin at the bottom left corner of the tile)."""
        out = []
        for row in range(self.rows):
            shift = spacing_x / 2.0 if self.offset and row % 2 else 0.0
            out.extend((col * spacing_x + shift, row * spacing_y) for col in range(self.cols))
        return out


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


@dataclass(frozen=True)
class Family:
    """A lattice whose size depends on one parameter (searched on the raster unless fixed)."""

    key: tuple
    make: Callable[[float], Cell]
    fixed: Optional[float] = None
    blocks: Optional[tuple[tuple[int, int], ...]] = None  # None = all blocks up to max_block_holes


def pattern_cell(pattern: str, a: float, b: Optional[float], custom=None) -> Cell:
    """Cell of a named pattern for the distance a (and the second distance b)."""
    if pattern == "square":
        return Cell(a, a, ((0.0, 0.0),))
    if pattern == "centered_square":
        s = a * SQRT2
        return Cell(s, s, ((0.0, 0.0), (s / 2.0, s / 2.0)))
    if pattern == "hex":
        return Cell(a, a * SQRT3, ((0.0, 0.0), (a / 2.0, a * SQRT3 / 2.0)))
    if pattern == "hex_rotated":
        return Cell(a * SQRT3, a, ((0.0, 0.0), (a * SQRT3 / 2.0, a / 2.0)))
    if pattern == "staggered":
        row = b if b is not None else a * SQRT3 / 2.0
        return Cell(a, 2.0 * row, ((0.0, 0.0), (a / 2.0, row)))
    if pattern == "rectangle":
        return Cell(a, b if b is not None else a, ((0.0, 0.0),))
    if pattern == "custom":
        f = a / custom.width  # a is the tile width
        return Cell(custom.width * f, custom.height * f, tuple((x * f, y * f) for x, y in custom.holes))
    raise ValueError(pattern)


@dataclass(frozen=True)
class TileUnit:
    u: float  # position inside the block (mm)
    v: float
    plane: int
    angle: float
    cd: Optional[float] = None


@dataclass
class Tile:
    """A block of cells with a valid motor assignment, it repeats over the build area."""

    family: Family
    param: float  # lattice parameter (distance a, tile width or spacing)
    cell: Cell
    cols: int  # block size in cells
    rows: int
    units: list[TileUnit]
    min_gap: float = math.inf

    @property
    def width(self) -> float:
        return self.cols * self.cell.width

    @property
    def height(self) -> float:
        return self.rows * self.cell.height

    @property
    def area_per_rod(self) -> float:
        return self.width * self.height / len(self.units)

    def placements(self, x: float, y: float) -> list[Placement]:
        """Units of the block with its bottom left corner at (x, y)."""
        return [Placement(x + t.u, y + t.v, t.plane, t.angle, t.cd) for t in self.units]

    def scaled(self, param: float) -> "Tile":
        """Same assignment on the lattice of another parameter."""
        cell = self.family.make(param)
        positions = block_positions(cell, self.cols, self.rows)
        units = [TileUnit(u, v, t.plane, t.angle, t.cd) for (u, v), t in zip(positions, self.units)]
        return Tile(self.family, param, cell, self.cols, self.rows, units, self.min_gap)

    def as_dict(self, origins: list[Point], pattern: str) -> dict:
        return {
            "pattern": pattern, "pitch": self.cell.nearest_distance(), "cell": [self.cell.width, self.cell.height],
            "width": self.width, "height": self.height, "rods": len(self.units), "rows": self.rows, "cols": self.cols,
            "units": [{"x": t.u, "y": t.v, "plane": t.plane, "angle": t.angle, **({"cd": t.cd} if t.cd is not None else {})}
                      for t in self.units],
            "origins": [[x, y] for x, y in origins],
        }


def block_positions(cell: Cell, cols: int, rows: int) -> list[Point]:
    return [(i * cell.width + u, j * cell.height + v) for j in range(rows) for i in range(cols) for u, v in cell.holes]


def blocks_up_to(holes_per_cell: int, max_holes: int) -> list[tuple[int, int]]:
    """Blocks (cols, rows) with at most max_holes holes, by ascending hole count, nearly square first."""
    out = [(m, n) for m in range(1, max_holes + 1) for n in range(1, max_holes + 1) if m * n * holes_per_cell <= max_holes]
    return sorted(out or [(1, 1)], key=lambda b: (b[0] * b[1], abs(b[0] - b[1]), -b[0]))


class PeriodicChecker:
    """Checks blocks against their own copies in an unbounded model (no edge, obstacles or zones)."""

    def __init__(self, model: Model, counter: Counter):
        project = copy.deepcopy(model.project)
        project.bounds.width = project.bounds.height = HELPER_AREA
        project.bounds.edge_margin = 0.0
        project.bounds.border = False
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

    def verify(self, tile: "Tile", halt: Halt) -> bool:
        """True, if the fixed assignment of the block is valid with the block's period."""
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
        search = TileSearch(model, counter, stop, random.Random(se.seed), progress)
        tiles = search.find_tiles(lambda: search.halted() or stop.elapsed > se.time_limit_s * SEARCH_SHARE)
        for tile in tiles[:TILES_TO_PLACE]:
            if search.halted():
                break
            search.place(tile)
        if search.fill:
            search.retarget(search.max_count)
            res.target = res.upper_bound = search.max_count
        out = finish(res, search, stop, counter)
        out.messages[:0] = search.notes(tiles)
        return out


class TileSearch(SearchBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checker = PeriodicChecker(self.model, self.counter)
        self.step = self.se.tile_step
        self.pattern = self.se.pattern
        self.task = self.se.pattern_task
        self.fill = self.task == "pitch" or (self.task == "dense" and self.se.pattern_fill)
        if self.fill:
            self.target = FILL_TARGET
        self._cache: dict[tuple, Optional[Tile]] = {}
        self.incomplete = False

    # -- Lattice families ----------------------------------------------------------------
    def families(self) -> list[Family]:
        se = self.se
        if self.pattern == "free":
            return self._free_families()
        b = se.pattern_pitch_y
        pitch = se.pattern_pitch if self.task == "pitch" else None  # the other tasks search the distance
        if self.pattern == "custom":
            tile = se.custom_tile
            fixed = pitch if pitch is not None else (None if tile.scalable else tile.width)
            return [Family(("custom",), lambda a: pattern_cell("custom", a, None, tile), fixed)]
        return [Family((self.pattern, b), lambda a: pattern_cell(self.pattern, a, b), pitch)]

    def _free_families(self) -> list[Family]:
        """Pattern free. One family per sub grid shape (and aspect when both tile sizes are searched)."""
        se = self.se
        width, height = se.tile_width, se.tile_height
        out = []
        for shape in tile_shapes(se.tile_rods):
            def cell(sx: float, sy: float, shape=shape) -> Cell:
                return Cell(shape.cols * sx, shape.rows * sy, tuple(shape.positions(sx, sy)))
            one = ((1, 1),)
            if width is not None and height is not None:
                out.append(Family((shape, "fixed"), lambda _, c=cell, s=shape: c(width / s.cols, height / s.rows), 0.0, one))
            elif width is not None:
                out.append(Family((shape, "w"), lambda sy, c=cell, s=shape: c(width / s.cols, sy), None, one))
            elif height is not None:
                out.append(Family((shape, "h"), lambda sx, c=cell, s=shape: c(sx, height / s.rows), None, one))
            else:
                for aspect in ASPECTS:
                    out.append(Family((shape, aspect), lambda sx, c=cell, k=aspect: c(sx, self._snap(sx * k)), None, one))
        return out

    # -- Evaluation ----------------------------------------------------------------------
    def _options(self, index: int) -> list[tuple[int, float, Optional[float]]]:
        """Plane, angle and centre distance options of hole index."""
        return [(plane, angle, cd) for plane in self.plane_order(index) for angle, cd in self.options_for(plane)]

    def evaluate(self, family: Family, block: tuple[int, int], param: float, halt: Halt) -> Optional[Tile]:
        """Block with a valid assignment for this lattice parameter, or None."""
        key = (family.key, block, round(param, SIZE_DIGITS))
        if key in self._cache:
            return self._cache[key]
        cell = family.make(param)
        cols, rows = block
        positions = block_positions(cell, cols, rows)
        options = [self._options(i) for i in range(len(positions))]
        units, gap, complete = self.checker.assign(positions, cols * cell.width, rows * cell.height, options, halt,
                                                   NODE_LIMIT * len(positions))
        self.incomplete = self.incomplete or not complete
        tile = Tile(family, param, cell, cols, rows, units, gap) if units else None
        if complete or tile:
            self._cache[key] = tile
        self.report(tr("progress.block_valid" if tile else "progress.block_invalid", cols=cols, rows=rows,
                       pitch=cell.nearest_distance()))
        return tile

    def _snap(self, value: float) -> float:
        return round(max(self.step, math.ceil(value / self.step - 1e-9) * self.step), SIZE_DIGITS)

    def _bounds(self, family: Family) -> tuple[float, float]:
        """Parameter range. Below lo the rods touch, from hi on no two units can collide."""
        def first_with(distance: float) -> float:
            lo, hi = 1e-6, self.step
            while family.make(hi).nearest_distance() < distance and hi < HELPER_AREA:
                lo, hi = hi, hi * 2.0
            for _ in range(60):
                mid = (lo + hi) / 2.0
                lo, hi = (mid, hi) if family.make(mid).nearest_distance() < distance else (lo, mid)
            return hi
        return first_with(self.checker.rod_pitch), first_with(self.checker.reach) + self.step

    def _smallest(self, feasible, lo: float, hi: float, halt: Halt) -> Optional[Tile]:
        """Binary search for the smallest raster value in [lo, hi] for which feasible(value) returns a tile."""
        lo, hi = self._snap(lo), self._snap(hi)
        if hi < lo:
            return None
        best_tile = feasible(hi)
        if best_tile is None:
            return None
        lo_i, hi_i = round(lo / self.step), round(hi / self.step)
        while lo_i < hi_i and not halt():
            mid_i = (lo_i + hi_i) // 2
            tile = feasible(round(mid_i * self.step, SIZE_DIGITS))
            if tile is not None:
                hi_i, best_tile = mid_i, tile
            else:
                lo_i = mid_i + 1
        return best_tile

    def best_of_family(self, family: Family, halt: Halt) -> Optional[Tile]:
        """Smallest lattice parameter with a valid block. Larger blocks only need to beat smaller parameters."""
        holes = len(family.make(1.0).holes)
        blocks = family.blocks or tuple(blocks_up_to(holes, self.se.max_block_holes))
        if family.fixed is not None:
            for block in blocks:
                if halt():
                    break
                tile = self.evaluate(family, block, family.fixed, halt)
                if tile is not None:
                    return tile
            return None
        lo, hi = self._bounds(family)
        best: Optional[Tile] = None
        for block in blocks:
            if halt():
                break
            upper = best.param - self.step if best else hi
            tile = self._smallest(lambda p, b=block: self.evaluate(family, b, p, halt), lo, upper, halt)
            if tile is not None:
                best = tile
        return best

    def find_tiles(self, halt: Halt) -> list[Tile]:
        """Best block per lattice family, sorted by area per hole (then largest gap)."""
        self.phase = tr("phase.pattern_search")
        tiles = []
        for family in self.families():
            if halt():
                break
            tile = self.best_of_family(family, halt)
            if tile is not None:
                tiles.append(tile)
        return sorted(tiles, key=lambda t: (round(t.area_per_rod, 3), -t.min_gap))

    # -- Placement ------------------------------------------------------------------------
    def _lattice(self, tile: Tile, shift_x: float, shift_y: float) -> dict[Point, tuple[Placement, Point]]:
        """All holes of the lattice whose rods can lie in the allowed region -> (placement, block origin)."""
        x0, y0, x1, y1 = self.region
        start_x = x0 + (shift_x % tile.width) - tile.width
        start_y = y0 + (shift_y % tile.height) - tile.height
        nx = int((x1 - start_x) / tile.width) + 1
        ny = int((y1 - start_y) / tile.height) + 1
        out = {}
        for j in range(ny + 1):
            for i in range(nx + 1):
                ox, oy = start_x + i * tile.width, start_y + j * tile.height
                for pl in tile.placements(ox, oy):
                    if x0 - 1e-9 <= pl.x <= x1 + 1e-9 and y0 - 1e-9 <= pl.y <= y1 + 1e-9:
                        out[(pl.x, pl.y)] = (pl, (ox, oy))
        return out

    def _build(self, tile: Tile, lattice: dict, ordered: list[Point]) -> int:
        """Add holes in the given order until the target count is reached and keep the layout. Returns the count."""
        layout = Layout(self.model, self.counter)
        origins: dict[Point, None] = {}
        for point in ordered:
            if len(layout) >= self.target or self.halted():
                break
            placement, origin = lattice[point]
            if layout.check(placement).ok:
                layout.add(placement)
                origins[origin] = None
        self.consider(layout.placements(), tile.as_dict(list(origins), self.pattern))
        return len(layout)

    def place(self, tile: Tile) -> None:
        self.phase = tr("phase.pattern_place")
        if self.task == "count" and tile.family.fixed is None and self._place_spread(tile):
            return
        self._place_compact(tile)

    def _place_compact(self, tile: Tile) -> None:
        """Holes closest to the centre, with several lattice shifts and orders."""
        cx, cy = self.center
        for i in range(PHASES):
            for j in range(PHASES):
                if self.halted():
                    return
                lattice = self._lattice(tile, cx + tile.width * i / PHASES, cy + tile.height * j / PHASES)
                for order in ORDERS:
                    if self.halted():
                        return
                    self._build(tile, lattice, order_points(list(lattice), (cx, cy), order))
            self.report(tr("progress.holes_placed", i=i + 1, n=PHASES))

    def _count_centered(self, tile: Tile) -> tuple[int, dict]:
        """Holes of the lattice in the region when the lattice is centred in it."""
        x0, y0, x1, y1 = self.region
        lattice = self._lattice(tile, 0.0, 0.0)
        if not lattice:
            return 0, lattice
        xs, ys = [p[0] for p in lattice], [p[1] for p in lattice]
        shift_x = (x0 + x1) / 2.0 - (min(xs) + max(xs)) / 2.0
        shift_y = (y0 + y1) / 2.0 - (min(ys) + max(ys)) / 2.0
        lattice = self._lattice(tile, shift_x, shift_y)
        return len(lattice), lattice

    def _place_spread(self, tile: Tile) -> bool:
        """Largest lattice distance at which the target count still fits, lattice centred in the region.
        Returns False if the target count could not be placed (compact placement follows then)."""
        x0, y0, x1, y1 = self.region
        lo_i = round(tile.param / self.step)
        hi_i = max(lo_i, round(max(x1 - x0, y1 - y0, self.step) * 2.0 / self.step))
        while lo_i < hi_i:  # largest parameter whose lattice still holds the target count
            mid_i = (lo_i + hi_i + 1) // 2
            if self._count_centered(tile.scaled(mid_i * self.step))[0] >= self.target:
                lo_i = mid_i
            else:
                hi_i = mid_i - 1
        base_i = round(tile.param / self.step)
        candidates = sorted({round(base_i + (lo_i - base_i) * k / SPREAD_TRIES) for k in range(SPREAD_TRIES, -1, -1)}, reverse=True)
        for param_i in candidates:
            if self.halted():
                return False
            candidate = tile.scaled(round(param_i * self.step, SIZE_DIGITS))
            if param_i != base_i and not self.checker.verify(candidate, self.halted):
                continue
            _, lattice = self._count_centered(candidate)
            cx, cy = self.center
            if self._build(candidate, lattice, order_points(list(lattice), (cx, cy), "euclid")) >= self.target:
                return True
        return False

    # -- Notes ----------------------------------------------------------------------------
    def notes(self, tiles: list[Tile]) -> list[str]:
        pattern_label = tr(f"option.search.pattern.{self.pattern}")
        if not tiles:
            fixed = [f.fixed for f in self.families() if f.fixed]
            if fixed and self.pattern != "free":
                return [tr("pattern.fixed_failed", pitch=self.families()[0].make(fixed[0]).nearest_distance())]
            return [tr("pattern.none_found", pattern=pattern_label)]
        best = tiles[0]
        out = [tr("pattern.summary", pattern=pattern_label, pitch=best.cell.nearest_distance(), cols=best.cols, rows=best.rows,
                  holes=len(best.units), width=best.width, height=best.height)]
        if best.family.fixed is None and self.task == "dense":
            out.append(tr("pattern.not_proven"))
        return out
