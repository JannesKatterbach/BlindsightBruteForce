"""Optimierer. Musterbasierte Kandidaten, gierige Zuordnung, lokale Verfeinerung.

Ablauf
  1. Kandidatengenerierung. Quadrat und Hexagonalraster mit abnehmender Teilung.
  2. Gierige Zuordnung. Je Rasterpunkt wird eine Kombination aus Motorebene und
     Motorwinkel gesucht, die alle Kollisionsbedingungen erfuellt. Ungueltige
     Teilkonfigurationen werden sofort verworfen (kein Aufbau voller Kombinationen).
  3. Teilungs-Bisektion. Nahe der kleinsten erfolgreichen Teilung wird verfeinert.
  4. Lokale Suche (Simulated Annealing Variante). Verschiebt Stangen zur Mitte,
     wechselt Winkel und Ebenen und fuegt fehlende Einheiten ein.
  5. Bewertung mit scoring.evaluate, die besten Loesungen bleiben als Top K erhalten.

Das Verfahren ist heuristisch. Es beweist keine Optimalitaet der Flaeche.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional

from ..diagnose import single_unit_report
from ..layout import Counter, Layout, Placement, layout_from_placements
from ..model import Model
from ..patterns import ORDERS, order_points, pattern_points
from ..scoring import Score, evaluate, upper_bound_count
from .base import (
    OptimizationResult,
    Optimizer,
    ProgressCallback,
    ProgressInfo,
    Solution,
    StopToken,
)

Halt = Callable[[], bool]


class PatternGreedyOptimizer(Optimizer):
    name = "pattern_greedy"

    def run(
        self,
        model: Model,
        progress: Optional[ProgressCallback] = None,
        stop: Optional[StopToken] = None,
        counter: Optional[Counter] = None,
    ) -> OptimizationResult:
        proj = model.project
        se = proj.search
        counter = counter or Counter()
        stop = stop or StopToken(se.time_limit_s, se.max_candidates, counter)
        rng = random.Random(se.seed)
        target = proj.target_count
        res = OptimizationResult(target=target, upper_bound=upper_bound_count(model), optimizer=self.name)

        diag = single_unit_report(model)
        if diag:
            res.status = "infeasible"
            res.messages = diag
            res.optimality_note = "Keine gueltige Loesung. Bereits eine einzelne Einheit ist nicht platzierbar."
            res.candidates = counter.checks
            res.elapsed = stop.elapsed
            return res

        state = _Search(model, counter, stop, rng, progress)
        sweep_budget = se.time_limit_s * (1.0 - se.refine_fraction)
        state.sweep(lambda: stop.should_stop() or stop.elapsed > sweep_budget)
        if state.solutions:
            state.refine(lambda: stop.should_stop())

        sols = state.finalize()
        res.solutions = sols
        res.candidates = counter.checks
        res.elapsed = stop.elapsed
        res.status = stop.reason or "completed"
        if stop.reason == "":
            # Zeit oder Kandidatenlimit wurden nicht erreicht, die Suche lief durch
            res.status = "completed"
        _describe(res, model)
        return res


def _describe(res: OptimizationResult, model: Model) -> None:
    target = res.target
    best = res.best
    n = len(best.placements) if best else 0
    if n == 0:
        res.status = "infeasible" if res.status == "completed" else res.status
        res.messages.append(
            "Es wurde keine gueltige Anordnung gefunden. Moegliche Ursachen. Bauraum zu klein, Sicherheitsabstand zu gross, "
            "Motoren zu hoch oder zu breit fuer die Ebenenabstaende, zu wenige erlaubte Winkel oder Ebenen."
        )
        res.optimality_note = "Keine Loesung gefunden. Das beweist nicht, dass keine existiert."
        return
    if n >= target:
        res.proven_optimal = False
        res.optimality_note = (
            f"Zielanzahl {target} erreicht, die Anzahl kann nicht weiter steigen. Grundflaeche, Gleichmaessigkeit und "
            "Regelmaessigkeit sind beste gefundene Werte und nicht als optimal bewiesen."
        )
    else:
        if n >= res.upper_bound:
            res.proven_optimal = True
            res.optimality_note = f"{n} Stangen erreichen die theoretische Obergrenze des Bauraums."
        else:
            res.optimality_note = (
                f"Nur {n} von {target} Stangen platzierbar. Beste gefundene Loesung, nicht als optimal bewiesen "
                f"(einfache Flaechenschranke {res.upper_bound})."
            )
            res.messages.append(
                f"Nur {n} von {target} Einheiten konnten kollisionsfrei platziert werden. "
                "Hilfreich waeren ein groesserer Bauraum, mehr Motorebenen, kleinerer Sicherheitsabstand, "
                "kleinere Motoren oder mehr erlaubte Winkel. Oder mehr Rechenzeit."
            )
    if res.status == "time_limit":
        res.messages.append("Das Zeitlimit wurde erreicht. Mehr Rechenzeit kann bessere Ergebnisse liefern.")
    if res.status == "candidate_limit":
        res.messages.append("Das Kandidatenlimit wurde erreicht.")


class _Search:
    def __init__(self, model: Model, counter: Counter, stop: StopToken, rng: random.Random, progress):
        self.model = model
        self.counter = counter
        self.stop = stop
        self.rng = rng
        self.progress = progress
        self.proj = model.project
        self.se = model.project.search
        self.target = self.proj.target_count
        self.usable = model.usable_planes()
        self.angles = model.angles
        b = self.proj.bounds
        m = b.edge_margin + model.rod_r
        self.region = (b.xmin + m, b.ymin + m, b.xmax - m, b.ymax - m)
        self.center = ((b.xmin + b.xmax) / 2.0, (b.ymin + b.ymax) / 2.0)
        self.solutions: dict[tuple, Solution] = {}
        self.best_total = -1.0
        self.best_count = 0
        self.phase = "start"

    # -- Verwaltung der besten Loesungen ----------------------------------------
    def consider(self, placements: list[Placement]) -> Optional[Score]:
        if not placements:
            return None
        sig = tuple(sorted((round(p.x, 2), round(p.y, 2), p.plane, round(p.angle, 2)) for p in placements))
        if sig in self.solutions:
            return self.solutions[sig].score
        sc = evaluate(self.model, placements, self.se.weights, self.target)
        self.solutions[sig] = Solution(list(placements), sc)
        if len(self.solutions) > max(self.se.top_k * 4, 20):
            worst = min(self.solutions.items(), key=lambda kv: kv[1].score.total)[0]
            del self.solutions[worst]
        if sc.total > self.best_total:
            self.best_total = sc.total
            self.best_count = len(placements)
        return sc

    def report(self, message: str = "") -> None:
        if self.progress:
            el = self.stop.elapsed
            self.progress(
                ProgressInfo(
                    self.phase,
                    self.counter.checks,
                    el,
                    self.best_count,
                    max(self.best_total, 0.0),
                    message,
                    min(1.0, el / self.se.time_limit_s),
                )
            )

    def finalize(self) -> list[Solution]:
        ranked = sorted(self.solutions.values(), key=lambda s: -s.score.total)
        out: list[Solution] = []
        for s in ranked:
            lay = layout_from_placements(self.model, s.placements)
            if lay.is_valid():  # Sicherheitsnetz, die Pruefung ist unabhaengig vom Aufbau
                out.append(s)
            if len(out) >= self.se.top_k:
                break
        return out

    # -- Zuordnung -------------------------------------------------------------
    def assign(self, points: list[tuple[float, float]], heuristic: str, halt: Halt) -> Layout:
        lay = Layout(self.model, self.counter)
        angles = self.angles
        na = len(angles)
        usable = self.usable
        prev = 0
        for x, y in points:
            if len(lay) >= self.target or halt():
                break
            k = len(lay)
            start = k % len(usable)
            planes = usable[start:] + usable[:start]
            best: Optional[tuple[float, Placement, int]] = None
            for da in range(na):
                ai = (prev + da) % na
                for plane in planes:
                    pl = Placement(x, y, plane, angles[ai])
                    r = lay.check(pl)
                    if not r.ok:
                        continue
                    if heuristic == "first" or math.isinf(r.min_gap):
                        best = (r.min_gap, pl, ai)
                        break
                    if best is None or r.min_gap > best[0] + 1e-9:
                        best = (r.min_gap, pl, ai)
                if best is not None and (heuristic == "first" or math.isinf(best[0])):
                    break
            if best is not None:
                lay.add(best[1])
                prev = best[2]
        return lay

    # -- Teilungs Suche ----------------------------------------------------------
    def _try_pitch(self, kind: str, pitch: float, halt: Halt, full: bool) -> int:
        points = pattern_points(kind, pitch, self.region)
        if not points:
            return 0
        best_n = 0
        orders = ORDERS if full else ORDERS[:2]
        heurs = ("first", "gap")
        for order in orders:
            ordered = order_points(points, self.center, order)
            for h in heurs:
                if halt():
                    return best_n
                lay = self.assign(ordered, h, halt)
                n = len(lay)
                if n:
                    self.consider(lay.placements())
                best_n = max(best_n, n)
        return best_n

    def sweep(self, halt: Halt) -> None:
        """Pro Muster. Bisektion der Teilung, falls die Zielanzahl erreichbar ist, sonst Abstieg."""
        self.phase = "Muster"
        model = self.model
        p_lo = self.proj.rod.diameter + model.gap
        p_hi = 2.0 * model.unit_radius + model.gap + 1.0
        kinds = list(self.se.patterns)
        sweep_start = self.stop.elapsed
        # Gesamte Sweep Zeit wird gleichmaessig auf die Muster verteilt
        total = None
        for idx, kind in enumerate(kinds):
            now = self.stop.elapsed
            # verbleibende Zeit bis zum Ende des Sweeps entspricht dem Abstand zu halt() Grenze, daher
            # begrenzen wir ueber einen relativen Anteil der bisher gemessenen Gesamtzeit
            if total is None:
                total = max(1e-3, self.se.time_limit_s * (1.0 - self.se.refine_fraction) - now)
            slot_end = now + total / (len(kinds) - idx) if idx == 0 else now + max(
                1e-3, (sweep_start + total - now) / (len(kinds) - idx)
            )
            sub = lambda e=slot_end: halt() or self.stop.elapsed > e
            if halt():
                return
            if self._try_pitch(kind, p_hi, sub, full=False) >= self.target:
                self._bisect(kind, p_lo, p_hi, sub)
            else:
                self._descend(kind, p_lo, p_hi, sub)

    def _bisect(self, kind: str, p_lo: float, p_hi: float, halt: Halt) -> None:
        self.phase = "Teilungs-Bisektion"
        ok, fail = p_hi, None
        if self._try_pitch(kind, p_lo, halt, full=False) >= self.target:
            ok = p_lo
        else:
            fail = p_lo
            for _ in range(9):
                if halt():
                    break
                mid = (ok + fail) / 2.0
                n = self._try_pitch(kind, mid, halt, full=False)
                if n >= self.target:
                    ok = mid
                else:
                    fail = mid
                self.report(f"Muster {kind}, Teilung {mid:.3f} mm, platziert {n}")
        # ausfuehrlich bei der besten Teilung und etwas lockereren Teilungen
        for f in (1.0, 1.03, 1.07, 1.15):
            if halt():
                return
            self._try_pitch(kind, ok * f, halt, full=True)
            self.report(f"Muster {kind}, Teilung {ok * f:.3f} mm")

    def _descend(self, kind: str, p_lo: float, p_hi: float, halt: Halt) -> None:
        """Zielanzahl nicht erreichbar. Teilung schrittweise senken und die Anzahl maximieren."""
        self.phase = "Anzahl maximieren"
        p = p_hi
        best = 0
        weak = 0
        while p >= p_lo - 1e-9:
            if halt():
                return
            n = self._try_pitch(kind, p, halt, full=True)
            self.report(f"Muster {kind}, Teilung {p:.2f} mm, platziert {n}")
            if n > best:
                best, weak = n, 0
            else:
                weak += 1
            if weak >= 5:
                return
            if n >= self.target:
                self._bisect(kind, p_lo, p, halt)
                return
            p *= 0.95

    # -- Lokale Suche ----------------------------------------------------------------
    def refine(self, halt: Halt) -> None:
        self.phase = "Lokale Suche"
        starts = sorted(self.solutions.values(), key=lambda s: -s.score.total)[:2]
        for i, s in enumerate(starts):
            if halt():
                return
            slice_end = self.stop.elapsed + max(0.2, (self.se.time_limit_s - self.stop.elapsed) / (len(starts) - i))
            self._local_search(s.placements, lambda t=slice_end: halt() or self.stop.elapsed > t)

    def _local_search(self, start: list[Placement], halt: Halt) -> None:
        model = self.model
        rng = self.rng
        lay = layout_from_placements(model, start, self.counter)
        bb: dict[int, tuple[float, float, float, float]] = {}

        def unit_bbox(pl: Placement):
            x0 = y0 = math.inf
            x1 = y1 = -math.inf
            for p in model.unit_parts(0, pl.x, pl.y, pl.plane, pl.angle):
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
            x0 = min(b[0] for b in bb.values())
            y0 = min(b[1] for b in bb.values())
            x1 = max(b[2] for b in bb.values())
            y1 = max(b[3] for b in bb.values())
            xs = [lay.units[u].x for u in bb]
            ys = [lay.units[u].y for u in bb]
            mx, my = sum(xs) / n, sum(ys) / n
            spread = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / n
            return (x1 - x0) * (y1 - y0) + spread

        e_cur = energy()
        pitch_ref = self.proj.rod.diameter + model.gap
        t_start = self.stop.elapsed
        t_total = max(1e-3, self.se.time_limit_s - t_start)
        it = 0
        best_sc = self.consider(lay.placements())
        best_total = best_sc.total if best_sc else -1.0
        angles = self.angles
        x0r, y0r, x1r, y1r = self.region
        while not halt():
            it += 1
            n = len(lay)
            frac = min(1.0, (self.stop.elapsed - t_start) / t_total)
            temp = max(1e-6, e_cur * 0.004 * (1.0 - frac))
            if n < self.target and rng.random() < 0.5:
                x, y = rng.uniform(x0r, x1r), rng.uniform(y0r, y1r)
                for _ in range(6):
                    pl = Placement(x, y, rng.choice(self.usable), rng.choice(angles))
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
                new = Placement(old.x, old.y, old.plane, rng.choice(angles))
            elif r < 0.35 and len(self.usable) > 1:
                new = Placement(old.x, old.y, rng.choice(self.usable), old.angle)
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
                    old.angle if rng.random() < 0.8 else rng.choice(angles),
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
                sc = self.consider(lay.placements())
                if sc and sc.total > best_total:
                    best_total = sc.total
                self.report("Lokale Suche")
        self.consider(lay.placements())
        self.report("Lokale Suche beendet")
