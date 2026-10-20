"""Optimierer. Musterbasierte Kandidaten, gierige Zuordnung, lokale Verfeinerung.

Ablauf
  1. Kandidatengenerierung. Quadrat und Hexagonalraster, Teilung wird gesucht.
  2. Gierige Zuordnung. Je Rasterpunkt wird eine Kombination aus Motorebene, Motorwinkel
     und Achsabstand gesucht, die alle Kollisionsbedingungen erfuellt. Ungueltige
     Teilkonfigurationen werden sofort verworfen.
  3. Teilungssuche. compact sucht die dichteste Teilung, bei der die Zielanzahl passt,
     spread die groesste (gleichmaessig ueber den Bauraum verteilt).
  4. Lokale Suche (Simulated Annealing) verfeinert die besten Anordnungen.
  5. Bewertung mit scoring.evaluate, die besten Loesungen bleiben als Top K erhalten.

Das Verfahren ist heuristisch. Es beweist keine Optimalitaet der Flaeche.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from ..layout import Counter
from ..model import Model
from ..patterns import ORDERS, order_points, pattern_points
from .base import Optimizer, OptimizationResult, ProgressCallback, StopToken, begin, finish
from .common import Halt, SearchBase


class PatternGreedyOptimizer(Optimizer):
    name = "pattern_greedy"

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
        search = PatternSearch(model, counter, stop, random.Random(se.seed), progress)
        sweep_budget = se.time_limit_s * (1.0 - se.refine_fraction)
        search.sweep(lambda: search.halted() or stop.elapsed > sweep_budget)
        if search.solutions and not stop.reason:
            search.refine(search.halted)
        return finish(res, search, stop, counter)


class PatternSearch(SearchBase):
    def _points(self, kind: str, pitch: float):
        """Rasterpunkte. spread nutzt den ganzen Bauraum, compact nur ein Fenster um die Mitte
        (mehr Punkte als noetig verschwenden Zeit, bei sehr grossem Bauraum sonst Millionen)."""
        x0, y0, x1, y1 = self.region
        if self.se.layout_goal == "compact":
            half = pitch * (math.sqrt(self.target) * 1.5 + 3.0)
            cx, cy = self.center
            x0, x1 = max(x0, cx - half), min(x1, cx + half)
            y0, y1 = max(y0, cy - half), min(y1, cy + half)
        pts = pattern_points(kind, pitch, (x0, y0, x1, y1))
        if len(pts) > 200_000:  # Schutz. Dichte Raster mit riesigem Bauraum und Zielanzahl
            pts = order_points(pts, self.center, "euclid")[:200_000]
        return pts

    def try_pitch(self, kind: str, pitch: float, halt: Halt, full: bool) -> int:
        points = self._points(kind, pitch)
        if not points:
            return 0
        best_n = 0
        orders = ORDERS if full else ORDERS[:2]
        for order in orders:
            ordered = order_points(points, self.center, order)
            for h in ("first", "gap"):
                if halt():
                    return best_n
                lay = self.assign(ordered, h, halt)
                n = len(lay)
                if n:
                    self.consider(lay.placements())
                best_n = max(best_n, n)
        return best_n

    # -- Teilungssuche ----------------------------------------------------------
    def pitch_range(self) -> tuple[float, float]:
        model = self.model
        p_lo = self.proj.rod.diameter + model.gap
        if self.se.layout_goal == "spread":
            b = self.proj.bounds
            p_hi = max(b.width, b.height)
        else:
            p_hi = 2.0 * model.unit_radius + model.gap + 1.0
        return p_lo, max(p_hi, p_lo * 1.01)

    def sweep(self, halt: Halt) -> None:
        self.phase = "Muster"
        kinds = list(self.se.patterns)
        # Zeitbudget. Jedes Muster bekommt einen gleich grossen Anteil der Restzeit des Sweeps.
        start = self.stop.elapsed
        total = max(1e-3, self._sweep_budget(halt))
        for idx, kind in enumerate(kinds):
            if halt():
                return
            slot_end = start + total * (idx + 1) / len(kinds)
            sub = lambda e=slot_end: halt() or self.stop.elapsed > e
            if self.se.fixed_pitch is not None:
                self.try_pitch(kind, self.se.fixed_pitch, sub, full=True)
                self.report(f"Muster {kind}, feste Teilung {self.se.fixed_pitch:.2f} mm")
                continue
            p_lo, p_hi = self.pitch_range()
            self.search_pitch(kind, p_lo, p_hi, sub)

    def _sweep_budget(self, halt: Halt) -> float:
        # Das Sweep Fenster endet, sobald halt() wahr wird. Wir schaetzen es ueber das Zeitlimit.
        return max(1e-3, self.se.time_limit_s * (1.0 - self.se.refine_fraction) - self.stop.elapsed)

    def search_pitch(self, kind: str, p_lo: float, p_hi: float, halt: Halt) -> None:
        """Von grob nach fein absteigen, bis die Zielanzahl passt, dann bis zur Grenze verfeinern."""
        self.phase = "Teilung suchen"
        spread = self.se.layout_goal == "spread"
        p = p_hi
        best = 0
        weak = 0
        prev_p: Optional[float] = None
        while p >= p_lo - 1e-9:
            if halt():
                return
            n = self.try_pitch(kind, p, halt, full=False)
            self.report(f"Muster {kind}, Teilung {p:.2f} mm, platziert {n}")
            if n >= self.target:
                self.phase = "Teilung verfeinern"
                if spread:
                    self._refine_spread(kind, p, prev_p or p, halt)
                else:
                    self._refine_compact(kind, p_lo, p, halt)
                return
            if n > best:
                best, weak = n, 0
            else:
                weak += 1
            if not spread and weak >= 5 and best > 0:
                return  # dichteres Raster bringt nur noch weniger
            prev_p, p = p, p * 0.96
        # Zielanzahl nie erreicht. Bestes Teilergebnis mit voller Auswertung am dichtesten Raster
        self.try_pitch(kind, p_lo, halt, full=True)

    def _refine_compact(self, kind: str, p_lo: float, ok: float, halt: Halt) -> None:
        fail: Optional[float] = None
        if self.try_pitch(kind, p_lo, halt, full=False) >= self.target:
            ok = p_lo
        else:
            fail = p_lo
            for _ in range(9):
                if halt():
                    break
                mid = (ok + fail) / 2.0
                n = self.try_pitch(kind, mid, halt, full=False)
                if n >= self.target:
                    ok = mid
                else:
                    fail = mid
                self.report(f"Muster {kind}, Teilung {mid:.3f} mm, platziert {n}")
        for f in (1.0, 1.03, 1.07, 1.15):
            if halt():
                return
            self.try_pitch(kind, ok * f, halt, full=True)
            self.report(f"Muster {kind}, Teilung {ok * f:.3f} mm")

    def _refine_spread(self, kind: str, ok: float, fail: float, halt: Halt) -> None:
        """Groesste Teilung finden, bei der die Zielanzahl noch passt (fail ist die letzte groebere)."""
        if fail > ok:
            for _ in range(8):
                if halt():
                    break
                mid = (ok + fail) / 2.0
                if self.try_pitch(kind, mid, halt, full=False) >= self.target:
                    ok = mid
                else:
                    fail = mid
        for f in (1.0, 0.97, 0.94):
            if halt():
                return
            self.try_pitch(kind, ok * f, halt, full=True)
            self.report(f"Muster {kind}, Teilung {ok * f:.3f} mm")

    # -- Lokale Suche -------------------------------------------------------------
    def refine(self, halt: Halt) -> None:
        self.phase = "Lokale Suche"
        starts = sorted(self.solutions.values(), key=lambda s: -s.score.total)[:2]
        spread = self.se.layout_goal == "spread"
        for i, s in enumerate(starts):
            if halt():
                return
            slice_end = self.stop.elapsed + max(0.2, (self.se.time_limit_s - self.stop.elapsed) / (len(starts) - i))
            self.local_search(s.placements, lambda t=slice_end: halt() or self.stop.elapsed > t, spread=spread)
