"""Exakte Suche auf einem diskreten Raster fuer kleine Aufgaben (Backtracking mit frueher Verwerfung).

Vorgehen. Fenster der Stangenmittelpunkte (w mal h Rasterpunkte) werden nach der Anzahl ihrer
Rasterpunkte aufsteigend untersucht. Je Fenster sucht ein Backtracking alle Kombinationen aus
Position, Ebene, Winkel und Achsabstand. Ungueltige Teilkonfigurationen werden sofort verworfen.
Das erste Fenster mit gueltiger Loesung ist das Fenster mit den wenigsten Rasterpunkten, sofern
alle kleineren Fenster vollstaendig widerlegt wurden.

Aussage. Optimalitaet gilt nur bezogen auf das Raster (nicht im stetigen Raum) und nur, wenn kein Knotenlimit
erreicht wurde. Sonst wird ehrlich gemeldet, dass die Widerlegung unvollstaendig ist.
"""

from __future__ import annotations

import math
import random
from typing import Iterator, Optional

from ..layout import Counter, Layout, Placement
from ..model import Model
from .base import STATUS_INFEASIBLE, OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import SearchBase
from .registry import register

MAX_TARGET = 14  # groessere Aufgaben sind fuer das Backtracking zu teuer
NODE_LIMIT = 30000  # Knoten je Fenster, danach gilt die Widerlegung als unvollstaendig


class _Abort(Exception):
    """Knotenlimit oder Abbruch der Suche."""


def windows_by_size(nx: int, ny: int, min_points: int) -> Iterator[tuple[int, int, int]]:
    """Fenster (Punkte, w, h) mit w <= nx, h <= ny und w * h >= min_points, aufsteigend nach (w * h, w).

    Die Fenster werden erst bei Bedarf erzeugt. Je Punktzahl a werden nur die Teiler bis sqrt(a)
    durchsucht, so bleibt auch ein riesiges Raster ohne Speicherproblem."""
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
    supports_parallel = False  # das Ergebnis ist deterministisch, weitere Seeds bringen nichts

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        target = model.project.target_count
        if target > MAX_TARGET:
            res.status = STATUS_INFEASIBLE
            res.messages.append(
                f"Der exakte Modus ist nur für bis zu {MAX_TARGET} Stangen gedacht (Zielanzahl {target}). "
                "Bitte 'pattern_greedy' oder 'anneal_free' verwenden."
            )
            res.optimality_note = "Nicht ausgeführt."
            res.elapsed = stop.elapsed
            return res
        search = SearchBase(model, counter, stop, random.Random(se.seed), progress)
        search.phase = "Exakte Suche"
        step = se.fixed_pitch or (model.project.rod.diameter + model.gap)
        x0, y0, x1, y1 = search.region
        nx = int((x1 - x0) / step) + 1
        ny = int((y1 - y0) / step) + 1
        complete = True  # alle bisher untersuchten kleineren Fenster vollstaendig widerlegt
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
            search.report(f"Fenster {w} x {h} widerlegt" + (" (unvollständig)" if budget_hit else ""))
        out = finish(res, search, stop, counter, grid_exact=True)
        if found and complete and out.best:
            out.proven_optimal = True
            out.optimality_note = (
                f"Fenster mit den wenigsten Rasterpunkten auf dem Raster {step:.2f} mm bewiesen (alle kleineren Fenster "
                "vollständig widerlegt, Fenster in der Ecke des Bauraums). Im stetigen Raum oder an anderer Stelle "
                "kann eine kleinere Anordnung existieren."
            )
        elif found:
            out.optimality_note = (
                "Lösung gefunden, aber kleinere Fenster wurden nicht vollständig widerlegt (Knotenlimit oder Abbruch). "
                "Nicht als optimal bewiesen."
            )
        return out

    def _window_dfs(self, search: SearchBase, points: list[tuple[float, float]]) -> tuple[bool, bool]:
        """Backtracking ueber die Punkte eines Fensters. Rueckgabe (Loesung gefunden, Knotenlimit erreicht)."""
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
                    return False  # es bleiben zu wenige Punkte
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
