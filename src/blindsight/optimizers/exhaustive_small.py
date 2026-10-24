"""Exact search on a discrete grid for small tasks (backtracking with early rejection).

Method. Windows of rod centres (w by h grid points) are examined in ascending order of their number
of grid points. Per window a backtracking searches all combinations of position, layer, angle and
centre distance. Invalid partial configurations are discarded at once. The first window with a valid
solution is the window with the fewest grid points, provided all smaller windows were fully refuted.

Statement. Optimality only holds with respect to the grid (not in continuous space) and only if no
node limit was hit. Otherwise it is reported honestly that the refutation is incomplete.
"""

from __future__ import annotations

import math
import random
from typing import Iterator, Optional

from ..i18n import tr
from ..layout import Counter, Layout, Placement
from ..model import Model
from .base import STATUS_INFEASIBLE, OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import SearchBase
from .registry import register

MAX_TARGET = 14  # larger tasks are too expensive for the backtracking
NODE_LIMIT = 30000  # nodes per window, after that the refutation counts as incomplete


class _Abort(Exception):
    """Node limit or cancellation of the search."""


def windows_by_size(nx: int, ny: int, min_points: int) -> Iterator[tuple[int, int, int]]:
    """Windows (points, w, h) with w <= nx, h <= ny and w * h >= min_points, ascending by (w * h, w).

    The windows are generated on demand. Per point count a only the divisors up to sqrt(a) are
    searched, so even a huge grid causes no memory problem."""
    for points in range(max(1, min_points), nx * ny + 1):
        pairs = []
        for w in range(1, math.isqrt(points) + 1):
            if points % w:
                continue
            h = points // w
            for a, b in {(w, h), (h, w)}:
                if a <= nx and b <= ny:
                    pairs.append((a, b))
        for w, h in sorted(pairs):
            yield points, w, h


@register
class ExhaustiveSmallOptimizer(Optimizer):
    name = "exhaustive_small"
    supports_parallel = False  # the result is deterministic, further seeds do not help

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        target = model.project.target_count
        if target > MAX_TARGET:
            res.status = STATUS_INFEASIBLE
            res.messages.append(tr("exhaustive.too_large", max=MAX_TARGET, target=target))
            res.optimality_note = tr("exhaustive.not_run")
            res.elapsed = stop.elapsed
            return res
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = tr("phase.exact")
        step = se.fixed_pitch or (model.project.rod.diameter + model.gap)
        x0, y0, x1, y1 = search.region
        nx = int((x1 - x0) / step) + 1
        ny = int((y1 - y0) / step) + 1
        complete = True  # all smaller windows examined so far fully refuted
        found = False
        for _, w, h in windows_by_size(nx, ny, search.target):
            if search.halted():
                complete = False
                break
            points = [(x0 + i * step, y0 + j * step) for j in range(h) for i in range(w)]
            found, budget_hit = self._window_dfs(search, points)
            if found:
                break
            if search.halted():
                complete = False
                break
            complete = complete and not budget_hit
            search.report(tr("progress.window_refuted_partial" if budget_hit else "progress.window_refuted", w=w, h=h))
        out = finish(res, search, stop, counter, grid_exact=True)
        if found and complete and out.best:
            out.proven_optimal = True
            out.optimality_note = tr("exhaustive.proven", step=step)
        elif found:
            out.optimality_note = tr("exhaustive.not_proven")
        return out

    def _window_dfs(self, search: SearchBase, points: list[tuple[float, float]]) -> tuple[bool, bool]:
        """Backtracking over the points of a window. Returns (solution found, node limit hit)."""
        target = search.target
        layout = Layout(search.model, search.counter)
        n = len(points)
        nodes = 0
        budget_hit = False

        def place_from(start: int) -> bool:
            nonlocal nodes, budget_hit
            if len(layout) == target:
                search.consider(layout.placements())
                return True
            for i in range(start, n):
                if n - i < target - len(layout):
                    return False  # too few points remain
                x, y = points[i]
                for plane in search.usable:
                    for angle, cd in search.options_for(plane):
                        nodes += 1
                        if nodes > NODE_LIMIT:
                            budget_hit = True
                            raise _Abort
                        if search.halted():
                            raise _Abort
                        placement = Placement(x, y, plane, angle, cd)
                        if layout.check(placement).ok:
                            uid = layout.add(placement)
                            if place_from(i + 1):
                                return True
                            layout.remove(uid)
            return False

        try:
            return place_from(0), budget_hit
        except _Abort:
            return False, budget_hit
