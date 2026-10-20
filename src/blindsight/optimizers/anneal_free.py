"""Optimierer mit freier Verteilung (ohne Rastervorgabe).

Mehrfachstart. Jeder Lauf beginnt mit einem zufaelligen gueltigen Teillayout und wird mit Simulated Annealing
verdichtet (compact) oder ausgeglichen (spread). Liefert unregelmaessige, aber oft platzsparende Anordnungen
und dient als Gegenprobe zu den Rastermustern. Heuristisch, keine Optimalitaetsaussage.
"""

from __future__ import annotations

import random
from typing import Optional

from ..layout import Counter, Layout
from ..model import Model
from .base import Optimizer, OptimizationResult, ProgressCallback, StopToken, begin, finish
from .common import SearchBase


class AnnealFreeOptimizer(Optimizer):
    name = "anneal_free"

    def run(
        self,
        model: Model,
        progress: Optional[ProgressCallback] = None,
        stop: Optional[StopToken] = None,
        counter: Optional[Counter] = None,
    ) -> OptimizationResult:
        se = model.project.search
        counter = counter or Counter()
        stop = stop or StopToken(se.time_limit_s, se.max_candidates, counter)
        res, infeasible = begin(model, stop, counter, self.name)
        if infeasible:
            return res
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = "Freie Verteilung"
        restarts = 4
        spread = se.layout_goal == "spread"
        for i in range(restarts):
            if search.halted():
                break
            end = stop.elapsed + max(0.3, (se.time_limit_s - stop.elapsed) / (restarts - i))
            lay = Layout(model, counter)
            # Start in der Mitte einer kleinen Region, damit der Block kompakt beginnt
            cx, cy = search.center
            span = max(model.unit_radius * 2, 10.0)
            region = (cx - span, cy - span, cx + span, cy + span) if not spread else None
            search.grow_random(lay, 4000, search.halted, region)
            if len(lay) == 0:
                search.grow_random(lay, 20000, search.halted)
            search.consider(lay.placements())
            search.report(f"Start {i + 1} von {restarts}, {len(lay)} Einheiten")
            search.local_search(lay.placements(), lambda e=end: search.halted() or stop.elapsed > e, spread=spread)
        return finish(res, search, stop, counter)
