"""Gemeinsame Bausteine der Optimierer.

SearchBase haelt den Zustand einer Suche (beste Loesungen, Fortschritt, Stagnation) und bietet
  assign        Zuordnung von Ebene, Winkel und Achsabstand zu gegebenen Stangenpositionen
  grow_random   zufaelliges Auffuellen eines Layouts
  local_search  Simulated Annealing Verfeinerung einer vorhandenen Anordnung (LocalSearch)

Die konkreten Strategien (Muster, freie Verteilung, exakt auf Raster) liegen daneben.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Iterator, Optional

from ..geometry import BBox
from ..layout import Counter, Layout, Placement, layout_from_placements, layout_signature
from ..model import Model
from ..scoring import Score, evaluate
from .base import STATUS_STAGNATION, ProgressInfo, Solution, StopToken

Halt = Callable[[], bool]

KEEP_FACTOR = 4  # so viele Loesungen je top_k werden waehrend der Suche gehalten
KEEP_MIN = 20
IMPROVE_EPS = 1e-9


class SearchBase:
    def __init__(self, model: Model, counter: Counter, stop: StopToken, rng: random.Random, progress=None):
        self.model = model
        self.counter = counter
        self.stop = stop
        self.rng = rng
        self.progress = progress
        self.proj = model.project
        self.se = model.project.search
        self.target = self.proj.target_count
        self.usable = model.usable_planes()
        bounds = self.proj.bounds
        margin = bounds.edge_margin + model.rod_r
        # Zulaessiger Bereich der Stangenachsen und Mitte des Bauraums
        self.region = (bounds.xmin + margin, bounds.ymin + margin, bounds.xmax - margin, bounds.ymax - margin)
        self.center = ((bounds.xmin + bounds.xmax) / 2.0, (bounds.ymin + bounds.ymax) / 2.0)
        self.solutions: dict[tuple, Solution] = {}
        self.best_total = -1.0
        self.best_count = 0  # Anzahl der bestbewerteten Loesung (Anzeige und Stagnation)
        self.max_count = 0  # groesste gefundene Anzahl (eine neue Hoechstzahl gilt als Fortschritt)
        self.best_placements: list[Placement] = []
        self.phase = "start"
        self._last_improve = time.monotonic()
        # Achsabstaende, None (nominal) zuerst, dann nach Naehe zum Nominalwert
        nominal = self.proj.motor.center_distance
        self.cds: list[Optional[float]] = [None] + [
            c for c in sorted(model.center_distances, key=lambda c: abs(c - nominal)) if abs(c - nominal) > IMPROVE_EPS
        ]

    # -- Stopp ---------------------------------------------------------------
    def stagnated(self) -> bool:
        """True, wenn die bestbewertete Loesung die Zielanzahl erreicht und sich stagnation_s lang nichts
        verbessert hat. Eine schlecht bewertete Anordnung mit voller Anzahl beendet die Suche nicht."""
        limit = self.se.stagnation_s
        if limit is None or self.best_count < self.target:
            return False
        if time.monotonic() - self._last_improve >= limit:
            self.stop.set_reason(STATUS_STAGNATION)
            return True
        return False

    def halted(self) -> bool:
        return self.stop.should_stop() or self.stagnated()

    # -- Verwaltung der besten Loesungen ----------------------------------------
    def consider(self, placements: list[Placement], tile: Optional[dict] = None) -> Optional[Score]:
        """Score a layout and keep it if it is among the best. tile describes a repeating pattern, if any."""
        if not placements:
            return None
        key = layout_signature(placements)
        if key in self.solutions:
            return self.solutions[key].score
        score = evaluate(self.model, placements, self.se.weights, self.target)
        self.solutions[key] = Solution(list(placements), score, tile)
        if len(self.solutions) > max(self.se.top_k * KEEP_FACTOR, KEEP_MIN):
            worst = min(self.solutions.items(), key=lambda kv: kv[1].score.total)[0]
            del self.solutions[worst]
        if score.total > self.best_total + IMPROVE_EPS or len(placements) > self.max_count:
            self._last_improve = time.monotonic()
        self.max_count = max(self.max_count, len(placements))
        if score.total > self.best_total:
            self.best_total = score.total
            self.best_count = len(placements)
            self.best_placements = list(placements)
        return score

    def report(self, message: str = "") -> None:
        if self.progress:
            elapsed = self.stop.elapsed
            self.progress(
                ProgressInfo(
                    self.phase, self.counter.checks, elapsed, self.best_count, max(self.best_total, 0.0), message,
                    min(1.0, elapsed / self.se.time_limit_s), [p.as_dict() for p in self.best_placements],
                )
            )

    def finalize(self) -> list[Solution]:
        """Die top_k besten Loesungen, jede noch einmal vollstaendig auf Kollisionen geprueft."""
        ranked = sorted(self.solutions.values(), key=lambda s: -s.score.total)
        out: list[Solution] = []
        for solution in ranked:
            if layout_from_placements(self.model, solution.placements).is_valid():  # Sicherheitsnetz
                out.append(solution)
            if len(out) >= self.se.top_k:
                break
        return out

    # -- Zuordnung -------------------------------------------------------------
    def options_for(self, plane: int, first_angle_index: int = 0) -> Iterator[tuple[float, Optional[float]]]:
        """(Winkel, Achsabstand) einer Ebene, beginnend beim Winkel mit Index first_angle_index."""
        angles = self.model.angles_for(plane)
        n = len(angles)
        for offset in range(n):
            angle = angles[(first_angle_index + offset) % n]
            for cd in self.cds:
                yield angle, cd

    def assign(self, points: list[tuple[float, float]], heuristic: str, halt: Halt) -> Layout:
        """Weist jedem Punkt der Reihe nach eine gueltige Kombination aus Ebene, Winkel und Achsabstand zu.

        heuristic "first" nimmt die erste gueltige, "gap" die mit dem groessten Abstand zu den
        Nachbarn. Ebenen werden reihum begonnen, Winkel beim Winkel des Vorgaengers."""
        layout = Layout(self.model, self.counter)
        usable = self.usable
        prev_angle_index = 0
        for x, y in points:
            if len(layout) >= self.target or halt():
                break
            start = len(layout) % len(usable)
            best = self._best_option(layout, x, y, usable[start:] + usable[:start], prev_angle_index, heuristic)
            if best is not None:
                layout.add(best[1])
                prev_angle_index = best[2]
        return layout

    def _best_option(self, layout: Layout, x: float, y: float, planes: list[int], prev_angle_index: int,
                     heuristic: str) -> Optional[tuple[float, Placement, int]]:
        """(Abstand, Platzierung, Winkelindex) der gewaehlten Option oder None."""
        best: Optional[tuple[float, Placement, int]] = None
        for plane in planes:
            angles = self.model.angles_for(plane)
            for angle, cd in self.options_for(plane, prev_angle_index % len(angles)):
                placement = Placement(x, y, plane, angle, cd)
                result = layout.check(placement)
                if not result.ok:
                    continue
                if best is None or result.min_gap > best[0] + IMPROVE_EPS:
                    best = (result.min_gap, placement, angles.index(angle))
                # Ohne Nachbarn (inf) kann keine Option besser werden
                if heuristic == "first" or math.isinf(result.min_gap):
                    break
            if best is not None and (heuristic == "first" or math.isinf(best[0])):
                break
        return best

    def random_placement(self, region: Optional[tuple[float, float, float, float]] = None) -> Placement:
        """Zufaellige Position in region (Standard. ganzer Bereich) mit zufaelliger Ebene, Winkel, Achsabstand."""
        x0, y0, x1, y1 = region or self.region
        return self.random_option_at(self.rng.uniform(x0, x1), self.rng.uniform(y0, y1))

    def random_option_at(self, x: float, y: float) -> Placement:
        """Zufaellige Ebene, Winkel und Achsabstand fuer eine feste Stangenposition."""
        rng = self.rng
        plane = rng.choice(self.usable)
        return Placement(x, y, plane, rng.choice(self.model.angles_for(plane)), rng.choice(self.cds))

    def grow_random(self, layout: Layout, tries: int, halt: Halt, region=None) -> None:
        """Fuellt ein Layout mit zufaelligen gueltigen Platzierungen bis zur Zielanzahl."""
        for _ in range(tries):
            if len(layout) >= self.target or halt():
                return
            layout.try_add(self.random_placement(region))

    def local_search(self, start: list[Placement], halt: Halt, spread: bool = False,
                     duration: Optional[float] = None) -> None:
        """Simulated Annealing ab start. duration ist die Laenge der Zeitscheibe (fuer die Abkuehlung),
        ohne Angabe die Restzeit des Laufs."""
        LocalSearch(self, start, spread, duration).run(halt)


# ---------------------------------------------------------------------------
# Lokale Suche
# ---------------------------------------------------------------------------
REPORT_EVERY = 400  # Iterationen zwischen Zwischenstaenden
ADD_PROBABILITY = 0.5  # Anteil der Zuege, die eine fehlende Einheit hinzufuegen wollen
ADD_TRIES = 6  # Ebenen und Winkel, die fuer eine neue Position probiert werden
TEMPERATURE_FACTOR = 0.004  # Starttemperatur relativ zur Energie
SPREAD_MIN_BONUS = 0.005  # Gewicht des kleinsten Nachbarabstands in der spread Energie
# Wahrscheinlichkeiten der Zugarten (kumulativ), der Rest sind Verschiebungen
MOVE_ROTATE, MOVE_PLANE, MOVE_CD = 0.25, 0.33, 0.40
KEEP_ANGLE_ON_SHIFT = 0.8
SHIFT_MIN, SHIFT_MAX = 0.02, 0.5  # Schrittweite relativ zur Mindestteilung
SHIFT_NOISE = 0.05


class LocalSearch:
    """Simulated Annealing. Zieht Stangen zur Mitte (compact) oder gleicht Abstaende aus (spread).

    Energie compact. Flaeche der Bounding Box plus mittlere quadratische Entfernung zur Mitte.
    Energie spread. Varianz der Nachbarabstaende minus kleiner Bonus fuer grosse Abstaende.
    Zuege. Einheit hinzufuegen (solange die Zielanzahl fehlt), drehen, Ebene oder Achsabstand
    wechseln, verschieben. Ungueltige Zuege werden sofort verworfen."""

    def __init__(self, search: SearchBase, start: list[Placement], spread: bool, duration: Optional[float]):
        self.search = search
        self.model = search.model
        self.rng = search.rng
        self.spread = spread
        self.layout = layout_from_placements(self.model, start, search.counter)
        self.boxes: dict[int, BBox] = {uid: self._bbox(pl) for uid, pl in self.layout.units.items()}
        self.pitch = search.proj.rod.diameter + self.model.gap
        self.t_start = search.stop.elapsed
        remaining = search.se.time_limit_s - self.t_start
        self.duration = max(1e-3, duration if duration is not None else remaining)

    def _bbox(self, pl: Placement) -> BBox:
        return self.model.unit_bbox(pl.x, pl.y, pl.plane, pl.angle, pl.cd)

    # -- Energie -----------------------------------------------------------------
    def energy(self) -> float:
        units = self.layout.units
        if not units:
            return 0.0
        xs = [units[u].x for u in self.boxes]
        ys = [units[u].y for u in self.boxes]
        return self._spread_energy(xs, ys) if self.spread else self._compact_energy(xs, ys)

    @staticmethod
    def _spread_energy(xs: list[float], ys: list[float]) -> float:
        n = len(xs)
        if n < 2:
            return 0.0
        nn = [min(math.hypot(xs[i] - xs[j], ys[i] - ys[j]) for j in range(n) if j != i) for i in range(n)]
        mean = sum(nn) / n
        var = sum((d - mean) ** 2 for d in nn) / n
        return var - SPREAD_MIN_BONUS * min(nn) * mean

    def _compact_energy(self, xs: list[float], ys: list[float]) -> float:
        boxes = self.boxes.values()
        width = max(b[2] for b in boxes) - min(b[0] for b in boxes)
        height = max(b[3] for b in boxes) - min(b[1] for b in boxes)
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        scatter = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / n
        return width * height + scatter

    def temperature(self, energy: float) -> float:
        """Faellt linear ueber die eigene Zeitscheibe auf 0."""
        progress = min(1.0, (self.search.stop.elapsed - self.t_start) / self.duration)
        return max(1e-9, abs(energy) * TEMPERATURE_FACTOR * (1.0 - progress) + 1e-9)

    # -- Zuege -------------------------------------------------------------------
    def _try_add_unit(self) -> bool:
        x0, y0, x1, y1 = self.search.region
        x, y = self.rng.uniform(x0, x1), self.rng.uniform(y0, y1)
        for _ in range(ADD_TRIES):
            pl = self.search.random_option_at(x, y)
            uid = self.layout.try_add(pl)
            if uid is not None:
                self.boxes[uid] = self._bbox(pl)
                return True
        return False

    def _propose(self, old: Placement) -> Placement:
        rng, model, search = self.rng, self.model, self.search
        r = rng.random()
        if r < MOVE_ROTATE:
            return Placement(old.x, old.y, old.plane, rng.choice(model.angles_for(old.plane)), old.cd)
        if r < MOVE_PLANE and len(search.usable) > 1:
            plane = rng.choice(search.usable)
            return Placement(old.x, old.y, plane, rng.choice(model.angles_for(plane)), old.cd)
        if r < MOVE_CD and len(search.cds) > 1:
            return Placement(old.x, old.y, old.plane, old.angle, rng.choice(search.cds))
        return self._shift(old)

    def _shift(self, old: Placement) -> Placement:
        """Verschiebung. compact zieht zum Schwerpunkt, spread geht in eine zufaellige Richtung."""
        rng = self.rng
        if self.spread:
            dx, dy = rng.gauss(0, 1), rng.gauss(0, 1)
        else:
            units = self.layout.units.values()
            n = len(self.layout)
            dx = sum(p.x for p in units) / n - old.x
            dy = sum(p.y for p in units) / n - old.y
        dist = math.hypot(dx, dy) or 1.0
        step = rng.uniform(SHIFT_MIN, SHIFT_MAX) * self.pitch
        angle = old.angle if rng.random() < KEEP_ANGLE_ON_SHIFT else rng.choice(self.model.angles_for(old.plane))
        return Placement(
            old.x + dx / dist * step + rng.gauss(0, SHIFT_NOISE * self.pitch),
            old.y + dy / dist * step + rng.gauss(0, SHIFT_NOISE * self.pitch),
            old.plane, angle, old.cd,
        )

    def _apply(self, uid: int, new: Placement) -> int:
        self.boxes.pop(uid)
        self.layout.remove(uid)
        nid = self.layout.add(new)
        self.boxes[nid] = self._bbox(new)
        return nid

    # -- Ablauf ------------------------------------------------------------------
    def run(self, halt: Halt) -> None:
        search = self.search
        energy = self.energy()
        iteration = 0
        while not halt():
            iteration += 1
            if iteration % REPORT_EVERY == 0:
                search.consider(self.layout.placements())
                search.report("Lokale Suche")
            n = len(self.layout)
            if n < search.target and self.rng.random() < ADD_PROBABILITY:
                if self._try_add_unit():
                    energy = self.energy()
                continue
            if n == 0:
                continue
            energy = self._step(energy)
        search.consider(self.layout.placements())
        search.report("Lokale Suche beendet")

    def _step(self, energy: float) -> float:
        """Ein Zug mit Metropolis Annahme. Rueckgabe der neuen Energie."""
        uid = self.rng.choice(list(self.layout.units))
        old = self.layout.units[uid]
        new = self._propose(old)
        if new == old or not self.layout.check(new, ignore=uid).ok:
            return energy
        saved_box = self.boxes[uid]
        nid = self._apply(uid, new)
        new_energy = self.energy()
        temp = self.temperature(energy)
        if new_energy <= energy or self.rng.random() < math.exp(-(new_energy - energy) / temp):
            return new_energy
        # Zug zuruecknehmen
        self.layout.remove(nid)
        self.boxes.pop(nid)
        rid = self.layout.add(old)
        self.boxes[rid] = saved_box
        return energy
