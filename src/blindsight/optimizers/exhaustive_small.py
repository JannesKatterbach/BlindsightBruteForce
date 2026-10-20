"""Exakte Suche auf einem diskreten Raster fuer kleine Aufgaben (Backtracking mit frueher Verwerfung).

Vorgehen. Fenster der Stangenmittelpunkte (Raster mal Raster) werden nach Flaeche aufsteigend untersucht.
Je Fenster sucht ein Backtracking alle Kombinationen aus Position, Ebene, Winkel und Achsabstand. Ungueltige
Teilkonfigurationen werden sofort verworfen. Das erste Fenster mit gueltiger Loesung hat die kleinste Flaeche
dieses Rasters, sofern alle kleineren Fenster vollstaendig widerlegt wurden.

Aussage. Optimalitaet gilt nur bezogen auf das Raster (nicht im stetigen Raum) und nur, wenn kein Knotenlimit
erreicht wurde. Sonst wird ehrlich gemeldet, dass die Widerlegung unvollstaendig ist.
"""

from __future__ import annotations

import random
from typing import Optional

from ..layout import Counter, Layout
from ..model import Model
from .base import Optimizer, OptimizationResult, ProgressCallback, StopToken, begin, finish
from .common import SearchBase

MAX_TARGET = 14


class _Budget(Exception):
    pass


class ExhaustiveSmallOptimizer(Optimizer):
    name = "exhaustive_small"

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
        if model.project.target_count > MAX_TARGET:
            res.status = "infeasible"
            res.messages.append(
                f"Der exakte Modus ist nur fuer bis zu {MAX_TARGET} Stangen gedacht (Zielanzahl {model.project.target_count}). "
                "Bitte 'pattern_greedy' oder 'anneal_free' verwenden."
            )
            res.optimality_note = "Nicht ausgefuehrt."
            res.elapsed = stop.elapsed
            return res
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = "Exakte Suche"
        step = se.fixed_pitch or (model.project.rod.diameter + model.gap)
        x0, y0, x1, y1 = search.region
        nx = int((x1 - x0) / step) + 1
        ny = int((y1 - y0) / step) + 1
        windows = sorted(((w * h, w, h) for w in range(1, nx + 1) for h in range(1, ny + 1) if w * h >= search.target))
        complete = True  # alle bisher untersuchten kleineren Fenster vollstaendig widerlegt
        node_limit = 30000
        found = False
        for _, w, h in windows:
            if search.halted():
                complete = False
                break
            pts = [(x0 + i * step, y0 + j * step) for j in range(h) for i in range(w)]
            if not self._window_dfs(search, pts, node_limit):
                if search.halted():
                    complete = False
                    break
                if search.last_budget_hit:
                    complete = False
                search.report(f"Fenster {w} x {h} widerlegt" + (" (unvollstaendig)" if search.last_budget_hit else ""))
                continue
            found = True
            break
        out = finish(res, search, stop, counter, grid_exact=True)
        if found and complete and out.best:
            out.proven_optimal = True
            out.optimality_note = (
                f"Kleinstes Fenster der Stangenmittelpunkte auf dem Raster {step:.2f} mm bewiesen (alle kleineren Fenster vollstaendig "
                "widerlegt, Fenster in der Ecke des Bauraums). Im stetigen Raum oder an anderer Stelle kann eine kleinere Anordnung existieren."
            )
        elif found:
            out.optimality_note = (
                "Loesung gefunden, aber kleinere Fenster wurden nicht vollstaendig widerlegt (Knotenlimit oder Abbruch). "
                "Nicht als optimal bewiesen."
            )
        return out

    def _window_dfs(self, search: SearchBase, pts, node_limit: int) -> bool:
        model = search.model
        target = search.target
        lay = Layout(model, search.counter)
        nodes = [0]
        search.last_budget_hit = False
        n = len(pts)

        def rec(start: int) -> bool:
            if len(lay) == target:
                search.consider(lay.placements())
                return True
            if n - start < target - len(lay):
                return False
            for i in range(start, n):
                if n - i < target - len(lay):
                    return False
                x, y = pts[i]
                for plane in search.usable:
                    for a, cd in search.options_for(plane):
                        nodes[0] += 1
                        if nodes[0] > node_limit:
                            search.last_budget_hit = True
                            raise _Budget
                        if search.halted():
                            raise _Budget
                        from ..layout import Placement

                        pl = Placement(x, y, plane, a, cd)
                        if lay.check(pl).ok:
                            uid = lay.add(pl)
                            if rec(i + 1):
                                return True
                            lay.remove(uid)
            return False

        try:
            return rec(0)
        except _Budget:
            return False
