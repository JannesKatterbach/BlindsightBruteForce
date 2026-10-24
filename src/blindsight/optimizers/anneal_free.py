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
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import SearchBase
from .registry import register

RESTARTS = 4
MIN_SLICE_S = 0.3
START_TRIES = 4000  # Zufallsversuche fuer das Startlayout in der Mitte
FALLBACK_TRIES = 20000  # Zufallsversuche im ganzen Bereich, wenn die Mitte nichts ergibt
MIN_START_SPAN = 10.0  # mm, halbe Kantenlaenge des Startbereichs um die Mitte


@register
class AnnealFreeOptimizer(Optimizer):
    name = "anneal_free"

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = "Freie Verteilung"
        spread = se.layout_goal == "spread"
        for i in range(RESTARTS):
            if search.halted():
                break
            duration = max(MIN_SLICE_S, (se.time_limit_s - stop.elapsed) / (RESTARTS - i))
            end = stop.elapsed + duration
            layout = Layout(model, counter)
            # compact beginnt in einer kleinen Region um die Mitte, damit der Block kompakt startet
            region = None
            if not spread:
                cx, cy = search.center
                span = max(model.unit_radius * 2, MIN_START_SPAN)
                region = (cx - span, cy - span, cx + span, cy + span)
            search.grow_random(layout, START_TRIES, search.halted, region)
            if len(layout) == 0:
                search.grow_random(layout, FALLBACK_TRIES, search.halted)
            search.consider(layout.placements())
            search.report(f"Start {i + 1} von {RESTARTS}, {len(layout)} Einheiten")
            search.local_search(layout.placements(), lambda e=end: search.halted() or stop.elapsed > e,
                                spread=spread, duration=duration)
        return finish(res, search, stop, counter)
