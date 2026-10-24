"""Optimizer. Pattern based candidates, greedy assignment, local refinement.

Steps
  1. Candidate generation. Square and hexagonal grid (patterns.PATTERNS), the pitch is searched.
  2. Greedy assignment. For every grid point a combination of motor layer, motor angle and centre
     distance is searched that satisfies all collision conditions. Invalid partial configurations are
     discarded at once.
  3. Pitch search. compact searches the densest pitch at which the target number fits, spread the
     largest (evenly distributed over the build area).
  4. Local search (simulated annealing) refines the best arrangements.
  5. Scoring with scoring.evaluate, the best solutions are kept as top K.

The method is heuristic. It does not prove optimality of the area.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from ..i18n import tr
from ..layout import Counter
from ..model import Model
from ..patterns import ORDERS, estimated_point_count, order_points, pattern_points
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import Halt, SearchBase
from .registry import register

MAX_PATTERN_POINTS = 200_000  # protection for dense grids in a huge build area
FAST_ORDERS = ORDERS[:2]  # orders for the fast pitch search
HEURISTICS = ("first", "gap")
COMPACT_WINDOW_FACTOR, COMPACT_WINDOW_MARGIN = 1.5, 3.0  # window around the centre (in pitches)
PITCH_SHRINK = 0.96  # factor per step of the coarse pitch search
MAX_WEAK_STEPS = 5  # compact. this many steps without improvement end the search
COMPACT_BISECTIONS, SPREAD_BISECTIONS = 9, 8
COMPACT_FINAL_FACTORS = (1.0, 1.03, 1.07, 1.15)  # pitches around the optimum, fully evaluated
SPREAD_FINAL_FACTORS = (1.0, 0.97, 0.94)
REFINE_STARTS = 2  # this many best arrangements are refined locally
MIN_REFINE_SLICE_S = 0.2


@register
class PatternGreedyOptimizer(Optimizer):
    name = "pattern_greedy"

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        search = PatternSearch(model, counter, stop, random.Random(se.seed), progress)
        sweep_budget = se.time_limit_s * (1.0 - se.refine_fraction)
        search.sweep(lambda: search.halted() or stop.elapsed > sweep_budget)
        if search.solutions and not stop.reason:
            search.refine(search.halted)
        return finish(res, search, stop, counter)


class PatternSearch(SearchBase):
    @property
    def spread(self) -> bool:
        return self.se.layout_goal == "spread"

    def _points(self, kind: str, pitch: float) -> list[tuple[float, float]]:
        """Grid points. spread uses the whole region, compact only a window around the centre (more points
        than needed waste time, with a very large build area there would be millions).

        If there would be too many points, the region is shrunk around the centre before generating."""
        x0, y0, x1, y1 = self.region
        cx, cy = self.center
        if not self.spread:
            half = pitch * (math.sqrt(self.target) * COMPACT_WINDOW_FACTOR + COMPACT_WINDOW_MARGIN)
            x0, x1 = max(x0, cx - half), min(x1, cx + half)
            y0, y1 = max(y0, cy - half), min(y1, cy + half)
        estimate = estimated_point_count(kind, pitch, (x0, y0, x1, y1))
        if estimate > MAX_PATTERN_POINTS:
            scale = math.sqrt(MAX_PATTERN_POINTS / estimate)
            hw, hh = (x1 - x0) * scale / 2.0, (y1 - y0) * scale / 2.0
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            x0, x1, y0, y1 = mx - hw, mx + hw, my - hh, my + hh
        points = pattern_points(kind, pitch, (x0, y0, x1, y1))
        if len(points) > MAX_PATTERN_POINTS:  # estimate too low. Keep the central points
            points = order_points(points, self.center, "euclid")[:MAX_PATTERN_POINTS]
        return points

    def try_pitch(self, kind: str, pitch: float, halt: Halt, full: bool) -> int:
        """Try a pitch with all (full) or the fast orders. Returns the largest count."""
        points = self._points(kind, pitch)
        if not points:
            return 0
        best_n = 0
        for order in ORDERS if full else FAST_ORDERS:
            ordered = order_points(points, self.center, order)
            for heuristic in HEURISTICS:
                if halt():
                    return best_n
                layout = self.assign(ordered, heuristic, halt)
                if len(layout):
                    self.consider(layout.placements())
                best_n = max(best_n, len(layout))
        return best_n

    # -- Pitch search ----------------------------------------------------------
    def pitch_range(self) -> tuple[float, float]:
        """Smallest (rods touch with clearance) and largest sensible pitch."""
        model = self.model
        p_lo = self.proj.rod.diameter + model.gap
        if self.spread:
            bounds = self.proj.bounds
            p_hi = max(bounds.width, bounds.height)
        else:
            p_hi = 2.0 * model.unit_radius + model.gap + 1.0  # units can no longer touch
        return p_lo, max(p_hi, p_lo * 1.01)

    def sweep(self, halt: Halt) -> None:
        """Every pattern gets an equal share of the sweep time."""
        self.phase = tr("phase.patterns")
        kinds = list(self.se.patterns)
        start = self.stop.elapsed
        total = max(1e-3, self.se.time_limit_s * (1.0 - self.se.refine_fraction) - start)
        for idx, kind in enumerate(kinds):
            if halt():
                return
            slot_end = start + total * (idx + 1) / len(kinds)

            def in_slot(end: float = slot_end) -> bool:
                return halt() or self.stop.elapsed > end

            if self.se.fixed_pitch is not None:
                self.try_pitch(kind, self.se.fixed_pitch, in_slot, full=True)
                self.report(tr("progress.fixed_pitch", pattern=kind, pitch=self.se.fixed_pitch))
                continue
            p_lo, p_hi = self.pitch_range()
            self.search_pitch(kind, p_lo, p_hi, in_slot)

    def search_pitch(self, kind: str, p_lo: float, p_hi: float, halt: Halt) -> None:
        """Descend from coarse to fine until the target number fits, then refine up to the limit."""
        self.phase = tr("phase.pitch_search")
        pitch = p_hi
        best = 0
        weak = 0
        prev_pitch: Optional[float] = None
        while pitch >= p_lo - 1e-9:
            if halt():
                return
            n = self.try_pitch(kind, pitch, halt, full=False)
            self.report(tr("progress.pitch_placed", pattern=kind, pitch=pitch, n=n))
            if n >= self.target:
                self.phase = tr("phase.pitch_refine")
                if self.spread:
                    self._refine_spread(kind, pitch, prev_pitch or pitch, halt)
                else:
                    self._refine_compact(kind, p_lo, pitch, halt)
                return
            if n > best:
                best, weak = n, 0
            else:
                weak += 1
            if not self.spread and weak >= MAX_WEAK_STEPS and best > 0:
                return  # a denser grid only gives fewer
            prev_pitch, pitch = pitch, pitch * PITCH_SHRINK
        # Target number never reached. Best partial result with full evaluation at the densest grid
        self.try_pitch(kind, p_lo, halt, full=True)

    def _refine_compact(self, kind: str, p_lo: float, ok: float, halt: Halt) -> None:
        """Find the smallest pitch at which the target number still fits (bisection between p_lo and ok)."""
        if self.try_pitch(kind, p_lo, halt, full=False) >= self.target:
            ok = p_lo
        else:
            fail = p_lo
            for _ in range(COMPACT_BISECTIONS):
                if halt():
                    break
                mid = (ok + fail) / 2.0
                n = self.try_pitch(kind, mid, halt, full=False)
                if n >= self.target:
                    ok = mid
                else:
                    fail = mid
                self.report(tr("progress.pitch_placed_fine", pattern=kind, pitch=mid, n=n))
        self._final_pitches(kind, ok, COMPACT_FINAL_FACTORS, halt)

    def _refine_spread(self, kind: str, ok: float, fail: float, halt: Halt) -> None:
        """Find the largest pitch at which the target number still fits (fail is the last coarser one)."""
        if fail > ok:
            for _ in range(SPREAD_BISECTIONS):
                if halt():
                    break
                mid = (ok + fail) / 2.0
                if self.try_pitch(kind, mid, halt, full=False) >= self.target:
                    ok = mid
                else:
                    fail = mid
        self._final_pitches(kind, ok, SPREAD_FINAL_FACTORS, halt)

    def _final_pitches(self, kind: str, pitch: float, factors: tuple[float, ...], halt: Halt) -> None:
        for factor in factors:
            if halt():
                return
            self.try_pitch(kind, pitch * factor, halt, full=True)
            self.report(tr("progress.pitch_final", pattern=kind, pitch=pitch * factor))

    # -- Local search -------------------------------------------------------------
    def refine(self, halt: Halt) -> None:
        """Refine the best arrangements, the remaining time is split evenly."""
        self.phase = tr("phase.local_search")
        starts = sorted(self.solutions.values(), key=lambda s: -s.score.total)[:REFINE_STARTS]
        for i, solution in enumerate(starts):
            if halt():
                return
            duration = max(MIN_REFINE_SLICE_S, (self.se.time_limit_s - self.stop.elapsed) / (len(starts) - i))
            slice_end = self.stop.elapsed + duration

            def in_slice(end: float = slice_end) -> bool:
                return halt() or self.stop.elapsed > end

            self.local_search(solution.placements, in_slice, spread=self.spread, duration=duration)
