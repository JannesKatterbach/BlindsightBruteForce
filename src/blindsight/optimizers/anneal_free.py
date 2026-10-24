"""Optimizer with free distribution (no grid given).

Multi start. Every run begins with a random valid partial layout and is compacted (compact) or evened
out (spread) with simulated annealing. Gives irregular but often space saving arrangements and serves
as a cross check of the grid patterns. Heuristic, no statement about optimality.
"""

from __future__ import annotations

import random
from typing import Optional

from ..i18n import tr
from ..layout import Counter, Layout
from ..model import Model
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import SearchBase
from .registry import register

RESTARTS = 4
MIN_SLICE_S = 0.3
START_TRIES = 4000  # random attempts for the start layout in the centre
FALLBACK_TRIES = 20000  # random attempts in the whole region if the centre gives nothing
MIN_START_SPAN = 10.0  # mm, half edge length of the start region around the centre


@register
class AnnealFreeOptimizer(Optimizer):
    name = "anneal_free"

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = tr("phase.free")
        spread = se.layout_goal == "spread"
        for i in range(RESTARTS):
            if search.halted():
                break
            duration = max(MIN_SLICE_S, (se.time_limit_s - stop.elapsed) / (RESTARTS - i))
            end = stop.elapsed + duration
            layout = Layout(model, counter)
            # compact starts in a small region around the centre so that the block starts compact
            region = None
            if not spread:
                cx, cy = search.center
                span = max(model.unit_radius * 2, MIN_START_SPAN)
                region = (cx - span, cy - span, cx + span, cy + span)
            search.grow_random(layout, START_TRIES, search.halted, region)
            if len(layout) == 0:
                search.grow_random(layout, FALLBACK_TRIES, search.halted)
            search.consider(layout.placements())
            search.report(tr("progress.restart", i=i + 1, n=RESTARTS, count=len(layout)))
            search.local_search(layout.placements(), lambda e=end: search.halted() or stop.elapsed > e,
                                spread=spread, duration=duration)
        return finish(res, search, stop, counter)
