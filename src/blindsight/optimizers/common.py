"""Gemeinsame Bausteine der Optimierer.

SearchBase haelt Zustand (beste Loesungen, Fortschritt, Stagnation) und bietet
  assign        Zuordnung von Ebene, Winkel und Achsabstand zu gegebenen Stangenpositionen
  local_search  Simulated Annealing Verfeinerung einer vorhandenen Anordnung
  grow_random   zufaelliges Auffuellen eines Layouts

Die konkreten Strategien (Muster, freie Verteilung, exakt auf Raster) liegen daneben.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional

from ..layout import Counter, Layout, Placement, layout_from_placements
from ..model import Model
from .base import ProgressInfo, Solution, StopToken
from ..scoring import Score, evaluate

Halt = Callable[[], bool]


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
        b = self.proj.bounds
        m = b.edge_margin + model.rod_r
        self.region = (b.xmin + m, b.ymin + m, b.xmax - m, b.ymax - m)
        self.center = ((b.xmin + b.xmax) / 2.0, (b.ymin + b.ymax) / 2.0)
        self.solutions: dict[tuple, Solution] = {}
        self.best_total = -1.0
        self.best_count = 0
        self.best_placements: list[Placement] = []
        self.phase = "start"
        self._last_improve = time.monotonic()
        nominal = self.proj.motor.center_distance
        self.cds: list[Optional[float]] = [None] + [
            c for c in sorted(model.center_distances, key=lambda c: abs(c - nominal)) if abs(c - nominal) > 1e-9
        ]

    # -- Stopp ---------------------------------------------------------------
    def stagnated(self) -> bool:
        lim = self.se.stagnation_s
        if lim is None or self.best_count < self.target:
            return False
        if time.monotonic() - self._last_improve >= lim:
            self.stop.reason = self.stop.reason or "stagnation"
            return True
        return False

    def halted(self) -> bool:
        return self.stop.should_stop() or self.stagnated()

    # -- Verwaltung der besten Loesungen ----------------------------------------
    def consider(self, placements: list[Placement]) -> Optional[Score]:
        if not placements:
            return None
        sig = tuple(sorted((round(p.x, 2), round(p.y, 2), p.plane, round(p.angle, 2), round(p.cd or 0.0, 2)) for p in placements))
        if sig in self.solutions:
            return self.solutions[sig].score
        sc = evaluate(self.model, placements, self.se.weights, self.target)
        self.solutions[sig] = Solution(list(placements), sc)
        if len(self.solutions) > max(self.se.top_k * 4, 20):
            worst = min(self.solutions.items(), key=lambda kv: kv[1].score.total)[0]
            del self.solutions[worst]
        if sc.total > self.best_total + 1e-9 or len(placements) > self.best_count:
            self._last_improve = time.monotonic()
        if sc.total > self.best_total:
            self.best_total = sc.total
            self.best_count = len(placements)
            self.best_placements = list(placements)
        return sc

    def report(self, message: str = "") -> None:
        if self.progress:
            el = self.stop.elapsed
            self.progress(
                ProgressInfo(
                    self.phase, self.counter.checks, el, self.best_count, max(self.best_total, 0.0), message,
                    min(1.0, el / self.se.time_limit_s), [p.as_dict() for p in self.best_placements],
                )
            )

    def finalize(self) -> list[Solution]:
        ranked = sorted(self.solutions.values(), key=lambda s: -s.score.total)
        out: list[Solution] = []
        for s in ranked:
            lay = layout_from_placements(self.model, s.placements)
            if lay.is_valid():  # Sicherheitsnetz, unabhaengig vom Aufbau der Loesung
                out.append(s)
            if len(out) >= self.se.top_k:
                break
        return out

    # -- Zuordnung -------------------------------------------------------------
    def options_for(self, plane: int, prev_angle_index: int = 0):
        """Winkel und Achsabstaende einer Ebene, beginnend beim Winkel des Vorgaengers."""
        angs = self.model.angles_for(plane)
        n = len(angs)
        for da in range(n):
            a = angs[(prev_angle_index + da) % n]
            for cd in self.cds:
                yield a, cd

    def assign(self, points: list[tuple[float, float]], heuristic: str, halt: Halt) -> Layout:
        """Weist jedem Punkt der Reihe nach die erste (oder beste) gueltige Kombination zu."""
        lay = Layout(self.model, self.counter)
        usable = self.usable
        prev = 0
        for x, y in points:
            if len(lay) >= self.target or halt():
                break
            k = len(lay)
            start = k % len(usable)
            planes = usable[start:] + usable[:start]
            best: Optional[tuple[float, Placement, int]] = None
            for plane in planes:
                angs = self.model.angles_for(plane)
                pi = prev % len(angs)
                for a, cd in self.options_for(plane, pi):
                    pl = Placement(x, y, plane, a, cd)
                    r = lay.check(pl)
                    if not r.ok:
                        continue
                    if best is None or r.min_gap > best[0] + 1e-9:
                        best = (r.min_gap, pl, angs.index(a))
                    if heuristic == "first" or math.isinf(r.min_gap):
                        break
                if best is not None and (heuristic == "first" or math.isinf(best[0])):
                    break
            if best is not None:
                lay.add(best[1])
                prev = best[2]
        return lay

    def grow_random(self, lay: Layout, tries: int, halt: Halt, region=None) -> None:
        """Fuellt ein Layout mit zufaelligen gueltigen Platzierungen bis zur Zielanzahl."""
        x0, y0, x1, y1 = region or self.region
        rng = self.rng
        for _ in range(tries):
            if len(lay) >= self.target or halt():
                return
            plane = rng.choice(self.usable)
            pl = Placement(
                rng.uniform(x0, x1), rng.uniform(y0, y1), plane, rng.choice(self.model.angles_for(plane)), rng.choice(self.cds)
            )
            lay.try_add(pl)

    # -- Lokale Suche ----------------------------------------------------------------
    def local_search(self, start: list[Placement], halt: Halt, spread: bool = False) -> None:
        """Simulated Annealing. Zieht Stangen zur Mitte (kompakt) oder gleicht Abstaende aus (spread)."""
        model = self.model
        rng = self.rng
        lay = layout_from_placements(model, start, self.counter)
        bb: dict[int, tuple[float, float, float, float]] = {}

        def unit_bbox(pl: Placement):
            x0 = y0 = math.inf
            x1 = y1 = -math.inf
            for p in model.unit_parts(0, pl.x, pl.y, pl.plane, pl.angle, pl.cd):
                if p.kind == "rod":
                    b = p.prism.fp.bbox
                    x0, y0, x1, y1 = min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])
                else:
                    for x, y in p.prism.fp.pts:
                        x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            return (x0, y0, x1, y1)

        for uid, pl in lay.units.items():
            bb[uid] = unit_bbox(pl)

        def energy() -> float:
            n = len(bb)
            if n == 0:
                return 0.0
            ids = list(bb)
            xs = [lay.units[u].x for u in ids]
            ys = [lay.units[u].y for u in ids]
            if spread:
                if n < 2:
                    return 0.0
                nn = []
                for i in range(n):
                    nn.append(min(math.hypot(xs[i] - xs[j], ys[i] - ys[j]) for j in range(n) if j != i))
                mean = sum(nn) / n
                var = sum((d - mean) ** 2 for d in nn) / n
                return var - 0.5 * min(nn) * mean * 0.01 + 0.0
            x0 = min(b[0] for b in bb.values())
            y0 = min(b[1] for b in bb.values())
            x1 = max(b[2] for b in bb.values())
            y1 = max(b[3] for b in bb.values())
            mx, my = sum(xs) / n, sum(ys) / n
            spread_e = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / n
            return (x1 - x0) * (y1 - y0) + spread_e

        e_cur = energy()
        pitch_ref = self.proj.rod.diameter + model.gap
        t_start = self.stop.elapsed
        t_total = max(1e-3, self.se.time_limit_s - t_start)
        it = 0
        x0r, y0r, x1r, y1r = self.region
        while not halt():
            it += 1
            n = len(lay)
            frac = min(1.0, (self.stop.elapsed - t_start) / t_total)
            temp = max(1e-9, abs(e_cur) * 0.004 * (1.0 - frac) + 1e-9)
            if n < self.target and rng.random() < 0.5:
                x, y = rng.uniform(x0r, x1r), rng.uniform(y0r, y1r)
                for _ in range(6):
                    plane = rng.choice(self.usable)
                    pl = Placement(x, y, plane, rng.choice(model.angles_for(plane)), rng.choice(self.cds))
                    uid = lay.try_add(pl)
                    if uid is not None:
                        bb[uid] = unit_bbox(pl)
                        e_cur = energy()
                        break
                continue
            if n == 0:
                break
            uid = rng.choice(list(lay.units))
            old = lay.units[uid]
            r = rng.random()
            if r < 0.25:
                new = Placement(old.x, old.y, old.plane, rng.choice(model.angles_for(old.plane)), old.cd)
            elif r < 0.33 and len(self.usable) > 1:
                plane = rng.choice(self.usable)
                new = Placement(old.x, old.y, plane, rng.choice(model.angles_for(plane)), old.cd)
            elif r < 0.40 and len(self.cds) > 1:
                new = Placement(old.x, old.y, old.plane, old.angle, rng.choice(self.cds))
            else:
                if spread:
                    dx, dy = rng.gauss(0, 1), rng.gauss(0, 1)
                else:
                    mx = sum(p.x for p in lay.units.values()) / n
                    my = sum(p.y for p in lay.units.values()) / n
                    dx, dy = mx - old.x, my - old.y
                dist = math.hypot(dx, dy) or 1.0
                step = rng.uniform(0.02, 0.5) * pitch_ref
                new = Placement(
                    old.x + dx / dist * step + rng.gauss(0, 0.05 * pitch_ref),
                    old.y + dy / dist * step + rng.gauss(0, 0.05 * pitch_ref),
                    old.plane,
                    old.angle if rng.random() < 0.8 else rng.choice(model.angles_for(old.plane)),
                    old.cd,
                )
            if new == old:
                continue
            res = lay.check(new, ignore=uid)
            if not res.ok:
                continue
            saved_bb = bb.pop(uid)
            lay.remove(uid)
            nid = lay.add(new)
            bb[nid] = unit_bbox(new)
            e_new = energy()
            if e_new <= e_cur or rng.random() < math.exp(-(e_new - e_cur) / temp):
                e_cur = e_new
            else:
                lay.remove(nid)
                bb.pop(nid)
                rid = lay.add(old)
                bb[rid] = saved_bb
            if it % 400 == 0:
                self.consider(lay.placements())
                self.report("Lokale Suche")
        self.consider(lay.placements())
        self.report("Lokale Suche beendet")
