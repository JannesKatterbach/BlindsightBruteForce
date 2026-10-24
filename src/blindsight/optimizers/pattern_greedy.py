"""Optimierer. Musterbasierte Kandidaten, gierige Zuordnung, lokale Verfeinerung.

Ablauf
  1. Kandidatengenerierung. Quadrat und Hexagonalraster (patterns.PATTERNS), Teilung wird gesucht.
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
from ..patterns import ORDERS, estimated_point_count, order_points, pattern_points
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import Halt, SearchBase
from .registry import register

MAX_PATTERN_POINTS = 200_000  # Schutz bei dichten Rastern in riesigem Bauraum
FAST_ORDERS = ORDERS[:2]  # Reihenfolgen fuer die schnelle Teilungssuche
HEURISTICS = ("first", "gap")
COMPACT_WINDOW_FACTOR, COMPACT_WINDOW_MARGIN = 1.5, 3.0  # Fenster um die Mitte (in Teilungen)
PITCH_SHRINK = 0.96  # Faktor je Schritt der groben Teilungssuche
MAX_WEAK_STEPS = 5  # compact. so viele Schritte ohne Verbesserung beenden die Suche
COMPACT_BISECTIONS, SPREAD_BISECTIONS = 9, 8
COMPACT_FINAL_FACTORS = (1.0, 1.03, 1.07, 1.15)  # Teilungen um das Optimum, voll ausgewertet
SPREAD_FINAL_FACTORS = (1.0, 0.97, 0.94)
REFINE_STARTS = 2  # so viele beste Anordnungen werden lokal verfeinert
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
        """Rasterpunkte. spread nutzt den ganzen Bereich, compact nur ein Fenster um die Mitte
        (mehr Punkte als noetig verschwenden Zeit, bei sehr grossem Bauraum sonst Millionen).

        Wuerden es zu viele Punkte, wird der Bereich vor dem Erzeugen um die Mitte verkleinert."""
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
        if len(points) > MAX_PATTERN_POINTS:  # Schaetzung zu knapp. Die mittleren Punkte behalten
            points = order_points(points, self.center, "euclid")[:MAX_PATTERN_POINTS]
        return points

    def try_pitch(self, kind: str, pitch: float, halt: Halt, full: bool) -> int:
        """Probiert eine Teilung mit allen (full) oder den schnellen Reihenfolgen. Rueckgabe groesste Anzahl."""
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

    # -- Teilungssuche ----------------------------------------------------------
    def pitch_range(self) -> tuple[float, float]:
        """Kleinste (Stangen beruehren sich mit Abstand) und groesste sinnvolle Teilung."""
        model = self.model
        p_lo = self.proj.rod.diameter + model.gap
        if self.spread:
            bounds = self.proj.bounds
            p_hi = max(bounds.width, bounds.height)
        else:
            p_hi = 2.0 * model.unit_radius + model.gap + 1.0  # Einheiten koennen sich nicht mehr beruehren
        return p_lo, max(p_hi, p_lo * 1.01)

    def sweep(self, halt: Halt) -> None:
        """Jedes Muster bekommt einen gleich grossen Anteil der Sweep Zeit."""
        self.phase = "Muster"
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
                self.report(f"Muster {kind}, feste Teilung {self.se.fixed_pitch:.2f} mm")
                continue
            p_lo, p_hi = self.pitch_range()
            self.search_pitch(kind, p_lo, p_hi, in_slot)

    def search_pitch(self, kind: str, p_lo: float, p_hi: float, halt: Halt) -> None:
        """Von grob nach fein absteigen, bis die Zielanzahl passt, dann bis zur Grenze verfeinern."""
        self.phase = "Teilung suchen"
        pitch = p_hi
        best = 0
        weak = 0
        prev_pitch: Optional[float] = None
        while pitch >= p_lo - 1e-9:
            if halt():
                return
            n = self.try_pitch(kind, pitch, halt, full=False)
            self.report(f"Muster {kind}, Teilung {pitch:.2f} mm, platziert {n}")
            if n >= self.target:
                self.phase = "Teilung verfeinern"
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
                return  # dichteres Raster bringt nur noch weniger
            prev_pitch, pitch = pitch, pitch * PITCH_SHRINK
        # Zielanzahl nie erreicht. Bestes Teilergebnis mit voller Auswertung am dichtesten Raster
        self.try_pitch(kind, p_lo, halt, full=True)

    def _refine_compact(self, kind: str, p_lo: float, ok: float, halt: Halt) -> None:
        """Kleinste Teilung finden, bei der die Zielanzahl noch passt (Bisektion zwischen p_lo und ok)."""
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
                self.report(f"Muster {kind}, Teilung {mid:.3f} mm, platziert {n}")
        self._final_pitches(kind, ok, COMPACT_FINAL_FACTORS, halt)

    def _refine_spread(self, kind: str, ok: float, fail: float, halt: Halt) -> None:
        """Groesste Teilung finden, bei der die Zielanzahl noch passt (fail ist die letzte groebere)."""
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
            self.report(f"Muster {kind}, Teilung {pitch * factor:.3f} mm")

    # -- Lokale Suche -------------------------------------------------------------
    def refine(self, halt: Halt) -> None:
        """Verfeinert die besten Anordnungen, die Restzeit wird gleichmaessig aufgeteilt."""
        self.phase = "Lokale Suche"
        starts = sorted(self.solutions.values(), key=lambda s: -s.score.total)[:REFINE_STARTS]
        for i, solution in enumerate(starts):
            if halt():
                return
            duration = max(MIN_REFINE_SLICE_S, (self.se.time_limit_s - self.stop.elapsed) / (len(starts) - i))
            slice_end = self.stop.elapsed + duration

            def in_slice(end: float = slice_end) -> bool:
                return halt() or self.stop.elapsed > end

            self.local_search(solution.placements, in_slice, spread=self.spread, duration=duration)
