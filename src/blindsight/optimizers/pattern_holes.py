"""Pattern with individually turned motors (UI "Pattern, motors individually", mode 2b).

The holes of G0 form a regular lattice (search.pattern, the same lattices as periodic_tile), but unlike
periodic_tile the motors do not have to repeat. Every hole gets its own layer, angle and centre distance
from the search for fixed holes (HoleSearch), including the improvement for the goals of the mode.

Tasks (search.pattern_task)
  dense  smallest lattice distance on the search.tile_step raster at which all holes can be served,
         found by bisection. The holes are the target_count lattice holes closest to the centre of the
         board, or the whole board with search.pattern_fill. Not proven to be the smallest distance.
  count  largest lattice distance at which target_count holes still fit on the board, the lattice is
         centred. Smaller distances are tried if the motors do not fit.
  pitch  the given distance search.pattern_pitch, the lattice fills the board. Holes that cannot be served
         are reported with their reason like fixed holes.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from ..i18n import tr
from ..layout import Counter, Layout
from ..model import Model
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .fixed_holes import HoleSearch
from .periodic_tile import Cell, pattern_cell
from .registry import register

Point = tuple[float, float]
FEASIBLE_SHARE = 0.75  # share of the time limit for the search of the distance, the rest improves the goals
CHECK_SHARE = 0.25  # at most this share of the remaining distance search time for one distance
MAX_HOLES = 2000  # protection against tiny distances on big boards
DIGITS = 6


def lattice_in_area(cell: Cell, area: tuple[float, float, float, float]) -> list[Point]:
    """All lattice holes inside the area, the lattice centred in it (the bounding box of the holes)."""
    def holes(shift_x: float, shift_y: float) -> list[Point]:
        x0, y0, x1, y1 = area
        start_x = x0 + shift_x % cell.width - cell.width
        start_y = y0 + shift_y % cell.height - cell.height
        nx = int((x1 - start_x) / cell.width) + 2
        ny = int((y1 - start_y) / cell.height) + 2
        out = []
        for j in range(ny):
            for i in range(nx):
                for u, v in cell.holes:
                    x, y = start_x + i * cell.width + u, start_y + j * cell.height + v
                    if x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9:
                        out.append((round(x, DIGITS), round(y, DIGITS)))
                    if len(out) > MAX_HOLES:
                        return out
        return out

    first = holes(0.0, 0.0)
    if not first:
        return first
    xs, ys = [p[0] for p in first], [p[1] for p in first]
    shift_x = (area[0] + area[2] - min(xs) - max(xs)) / 2.0
    shift_y = (area[1] + area[3] - min(ys) - max(ys)) / 2.0
    return holes(shift_x, shift_y)


class LatticeSearch:
    """Lattice holes for a distance and the search of the distance for the task."""

    def __init__(self, model: Model, counter: Counter, stop: StopToken, progress: Optional[ProgressCallback]):
        self.model, self.counter, self.stop, self.progress = model, counter, stop, progress
        proj = model.project
        self.se = proj.search
        self.step = self.se.tile_step
        self.target = proj.target_count
        bounds = proj.bounds
        margin = bounds.rod_margin + model.rod_r
        self.area = (bounds.xmin + margin, bounds.ymin + margin, bounds.xmax - margin, bounds.ymax - margin)
        self.center = ((self.area[0] + self.area[2]) / 2.0, (self.area[1] + self.area[3]) / 2.0)
        self.reach = Layout(model).reach
        self.rod_pitch = proj.rod.diameter + model.gap
        self.best: Optional[HoleSearch] = None  # search of the chosen distance
        self.pitch: Optional[float] = None

    # -- Lattice --------------------------------------------------------------------------
    def cell(self, a: float) -> Cell:
        se = self.se
        return pattern_cell(se.pattern, a, se.pattern_pitch_y, se.custom_tile)

    def fixed_param(self) -> Optional[float]:
        """Lattice parameter of the task pitch (the tile width for an own tile that may not scale)."""
        se = self.se
        if se.pattern_pitch is not None:
            if se.pattern == "custom":  # the distance is given, scale the tile accordingly
                base = self.cell(se.custom_tile.width)
                return se.custom_tile.width * se.pattern_pitch / base.nearest_distance()
            return se.pattern_pitch
        if se.pattern == "custom" and not se.custom_tile.scalable:
            return se.custom_tile.width
        return None

    def holes(self, a: float, count: Optional[int]) -> list[Point]:
        """Lattice holes of parameter a, by rows. With count the count holes closest to the centre."""
        points = lattice_in_area(self.cell(a), self.area)
        if count is not None:
            cx, cy = self.center
            points = sorted(points, key=lambda p: ((p[0] - cx) ** 2 + (p[1] - cy) ** 2, p[1], p[0]))[:count]
        return sorted(points, key=lambda p: (p[1], p[0]))

    def _param_for(self, distance: float) -> float:
        """Smallest parameter whose nearest hole distance reaches distance (bisection)."""
        lo, hi = 1e-6, self.step
        while self.cell(hi).nearest_distance() < distance and hi < 1e6:
            lo, hi = hi, hi * 2.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if self.cell(mid).nearest_distance() < distance else (lo, mid)
        return hi

    def _snap(self, value: float, up: bool = True) -> float:
        k = value / self.step
        return round(max(1, math.ceil(k - 1e-9) if up else math.floor(k + 1e-9)) * self.step, DIGITS)

    # -- Feasibility ----------------------------------------------------------------------------
    def prepare(self, a: float, count: Optional[int]) -> Optional[HoleSearch]:
        """Search over the lattice holes of parameter a. Holes where no single motor fits (edge, obstacles,
        zones) are dropped, with count the count usable holes closest to the centre stay. None if too few."""
        holes = self.holes(a, None)
        search = HoleSearch(self.model, self.counter, self.stop, random.Random(self.se.seed), self.progress, holes=holes)
        usable = [i for i in range(len(holes)) if search.options[i]]
        if count is not None:
            cx, cy = self.center
            usable = sorted(usable, key=lambda i: ((holes[i][0] - cx) ** 2 + (holes[i][1] - cy) ** 2, holes[i][1], holes[i][0]))[:count]
            if len(usable) < count:
                return None
        search.dropped = len(holes) - len(usable) if count is None else 0  # no room for a motor (fill)
        search.select(sorted(usable, key=lambda i: (holes[i][1], holes[i][0])))
        search.phase = tr("phase.pitch_search")
        return search if search.target else None

    def check(self, a: float, count: Optional[int], deadline: float) -> Optional[HoleSearch]:
        """The search of parameter a if all its holes could be served, otherwise None."""
        search = self.prepare(a, count)
        if search is None:
            return None
        search.exact(lambda: search.halted() or self.stop.elapsed > deadline)
        return search if search.assignment is not None else None

    def _deadline(self, end: float) -> float:
        return self.stop.elapsed + max(0.05, (end - self.stop.elapsed) * CHECK_SHARE)

    def run(self, end: float) -> None:
        task = self.se.pattern_task
        count = None if task == "pitch" or (task == "dense" and self.se.pattern_fill) else self.target
        if task == "pitch":
            self.pitch = self.fixed_param()
            search = self.prepare(self.pitch, None)
            if search is not None:
                search.exact(lambda: search.halted() or self.stop.elapsed > end)
                if search.assignment is None:  # not all holes can be served, keep the largest served set
                    search.partial(lambda: search.halted() or self.stop.elapsed > end)
            self.best = search
            return
        lo = self._snap(self._param_for(self.rod_pitch))
        hi = self._snap(self._param_for(self.reach))
        if count is not None:  # the lattice must still hold count holes
            hi = min(hi, self._largest_holding(lo, count))
        if task == "count":
            self._first_feasible_downwards(hi, count, end)
        else:
            self._smallest(lo, hi, count, end)

    def _largest_holding(self, lo: float, count: int) -> float:
        """Largest parameter on the raster whose centred lattice still has count holes on the board."""
        lo_i = round(lo / self.step)
        top_i = max(lo_i, round(max(self.area[2] - self.area[0], self.area[3] - self.area[1], self.step) * 2.0 / self.step))
        while lo_i < top_i:
            mid_i = (lo_i + top_i + 1) // 2
            if len(self.holes(round(mid_i * self.step, DIGITS), None)) >= count:
                lo_i = mid_i
            else:
                top_i = mid_i - 1
        return round(lo_i * self.step, DIGITS)

    def _smallest(self, lo: float, hi: float, count: Optional[int], end: float) -> None:
        """Smallest feasible parameter on the raster between lo and hi (bisection). At hi no two motors can
        touch, so it only fails if too few holes are usable."""
        lo_i, best_i = round(lo / self.step), round(hi / self.step)
        best = self.check(hi, count, self._deadline(end))
        if best is None:
            return
        while lo_i < best_i and self.stop.elapsed < end and not self.stop.should_stop():
            mid_i = (lo_i + best_i) // 2
            search = self.check(round(mid_i * self.step, DIGITS), count, self._deadline(end))
            if search is not None:
                best, best_i = search, mid_i
            else:
                lo_i = mid_i + 1
            best.report(tr("progress.pitch", pitch=self.cell(best_i * self.step).nearest_distance()))
        self.best, self.pitch = best, round(best_i * self.step, DIGITS)

    def _first_feasible_downwards(self, hi: float, count: int, end: float) -> None:
        """Task count. The largest parameter (most spread) at which the motors fit, from hi downwards."""
        for k in range(round(hi / self.step), 0, -1):  # every smaller parameter is denser
            if self.stop.elapsed >= end or self.stop.should_stop():
                return
            a = round(k * self.step, DIGITS)
            if self.cell(a).nearest_distance() < self.rod_pitch:
                return
            search = self.check(a, count, self._deadline(end))
            if search is not None:
                self.best, self.pitch = search, a
                return

    def notes(self) -> list:
        pattern_label = tr(f"option.search.pattern.{self.se.pattern}")
        if self.best is None or self.pitch is None:
            return [tr("pattern_holes.none_found", pattern=pattern_label)]
        out = [tr("pattern_holes.summary", pattern=pattern_label, pitch=self.cell(self.pitch).nearest_distance(), n=self.best.target)]
        if self.best.dropped:
            out.append(tr("pattern_holes.dropped", n=self.best.dropped))
        if self.se.pattern_task == "dense":
            out.append(tr("pattern.not_proven"))
        return out


@register
class PatternHolesOptimizer(Optimizer):
    name = "pattern_holes"
    supports_parallel = False  # the search is deterministic

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        lattice = LatticeSearch(model, counter, stop, progress)
        lattice.run(se.time_limit_s * FEASIBLE_SHARE)
        search = lattice.best
        if search is None:
            empty = HoleSearch(model, counter, stop, random.Random(se.seed), progress, holes=[])
            out = finish(res, empty, stop, counter)
            out.messages[:0] = lattice.notes()
            return out
        search.improve(search.halted)
        res.target = search.target
        res.upper_bound = search.target
        out = finish(res, search, stop, counter)
        unserved = search.notes(False)[1:] if len(search.assignment or {}) < search.target else []
        out.messages[:0] = lattice.notes() + unserved
        return out
