"""Optimizer for fixed G0 holes (project.holes, from a hole pattern file).

The rod positions are given. For every hole the search chooses motor layer, motor angle and centre
distance so that no parts collide.

Search
  1. Options. Every combination of layer, angle and centre distance that satisfies the rules of a single
     unit at the hole (layer, build area, obstacles, mounting zones) is an option of the hole.
  2. Exact backtracking. The hole with the fewest remaining options is assigned first. After every
     assignment the options of the neighbours within reach that would collide are removed (forward
     checking), an empty option list means backtracking. Capacities per layer are counted along.
     If the search ends without a solution and without hitting the time or node limit, it is proven that
     not all holes can be served at the same time.
  3. Partial result. Without a complete solution, greedy assignments in several orders give the largest
     set of served holes found. The remaining holes are listed with the most frequent reason.
"""

from __future__ import annotations

import math
import random
from collections import Counter as Tally
from typing import Optional

from ..geometry import prism_distance
from ..i18n import tr
from ..layout import Counter, Layout, Placement
from ..model import Model
from ..units import EPS
from .base import OptimizationResult, Optimizer, ProgressCallback, StopToken, finish
from .common import SearchBase
from .registry import register

NODE_LIMIT = 200_000  # assignments of the exact search, after that the partial search takes over
EXACT_SHARE = 0.6  # share of the time limit for the exact search
GREEDY_ORDERS = 24  # greedy runs (input order, fewest options first, random orders)
REPORT_EVERY = 500

Option = tuple[int, float, Optional[float]]  # plane, angle, centre distance


@register
class FixedHolesOptimizer(Optimizer):
    name = "fixed_holes"
    supports_parallel = False  # the exact search is deterministic

    def search(self, model: Model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken,
               counter: Counter) -> OptimizationResult:
        se = model.project.search
        search = HoleSearch(model, counter, stop, random.Random(se.seed), progress)
        res.target = search.target
        res.upper_bound = search.target
        complete = search.exact(lambda: search.halted() or stop.elapsed > se.time_limit_s * EXACT_SHARE)
        if not search.solutions:
            search.partial(search.halted)
        out = finish(res, search, stop, counter)
        out.messages[:0] = search.notes(complete)
        return out


class HoleSearch(SearchBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.holes = [(float(x), float(y)) for x, y in self.proj.holes or []]
        self.target = len(self.holes)
        self.phase = tr("phase.fixed_holes")
        empty = Layout(self.model, self.counter)
        self.reach = empty.reach
        self.options: list[list[Option]] = []
        for i, (x, y) in enumerate(self.holes):
            start = i % len(self.usable)
            planes = self.usable[start:] + self.usable[:start]
            self.options.append([(plane, angle, cd) for plane in planes for angle, cd in self.options_for(plane)
                                 if empty.check(Placement(x, y, plane, angle, cd)).ok])
        self.neighbors = [[j for j, (u, v) in enumerate(self.holes) if j != i and math.hypot(u - x, v - y) <= self.reach]
                          for i, (x, y) in enumerate(self.holes)]
        self._compat: dict[tuple, bool] = {}
        self.capacity = self.model.capacity

    # -- Pair check ------------------------------------------------------------------
    def placement(self, i: int, option: Option) -> Placement:
        x, y = self.holes[i]
        return Placement(x, y, *option)

    def compatible(self, i: int, a: Option, j: int, b: Option) -> bool:
        """True if the units at hole i (option a) and hole j (option b) keep the safety distance."""
        key = (i, a, j, b) if i < j else (j, b, i, a)
        cached = self._compat.get(key)
        if cached is None:
            self.counter.checks += 1
            pa, pb = self.placement(i, a), self.placement(j, b)
            gap = self.model.gap
            parts_a = self.model.unit_parts(-1, pa.x, pa.y, pa.plane, pa.angle, pa.cd)
            parts_b = self.model.unit_parts(-2, pb.x, pb.y, pb.plane, pb.angle, pb.cd)
            cached = all(prism_distance(p.prism, q.prism, gap) >= gap - EPS for p in parts_a for q in parts_b)
            self._compat[key] = cached
        return cached

    # -- Exact search ------------------------------------------------------------------
    def exact(self, halt) -> bool:
        """Backtracking with forward checking. Returns True if the search space was exhausted."""
        n = self.target
        if any(not options for options in self.options):
            return True  # a hole without any option, not all holes can be served
        domains = [list(options) for options in self.options]
        chosen: dict[int, Option] = {}
        load: Tally[int] = Tally()
        state = {"nodes": 0, "complete": True}

        def fits_capacity(option: Option) -> bool:
            cap = self.capacity.get(option[0])
            return cap is None or load[option[0]] < cap

        def solve(domains: list[list[Option]]) -> bool:
            if len(chosen) == n:
                self.consider([self.placement(i, chosen[i]) for i in range(n)])
                return True
            i = min((k for k in range(n) if k not in chosen), key=lambda k: len(domains[k]))
            for option in domains[i]:
                state["nodes"] += 1
                if state["nodes"] > NODE_LIMIT or halt():
                    state["complete"] = False
                    return False
                if not fits_capacity(option):
                    continue
                reduced = list(domains)
                dead = False
                for j in self.neighbors[i]:
                    if j in chosen:
                        continue
                    reduced[j] = [b for b in domains[j] if self.compatible(i, option, j, b)]
                    if not reduced[j]:
                        dead = True
                        break
                if dead:
                    continue
                chosen[i] = option
                load[option[0]] += 1
                if state["nodes"] % REPORT_EVERY == 0:
                    self.report(tr("progress.fixed_holes", done=len(chosen), total=n))
                if solve(reduced):
                    return True
                del chosen[i]
                load[option[0]] -= 1
                if not state["complete"]:
                    return False
            return False

        found = solve(domains)
        return not found and state["complete"]

    # -- Partial result -----------------------------------------------------------------
    def partial(self, halt) -> None:
        """Largest set of served holes found by greedy assignments in several orders plus repair moves."""
        n = self.target
        orders = [list(range(n)), sorted(range(n), key=lambda k: len(self.options[k]))]
        for _ in range(GREEDY_ORDERS - len(orders)):
            order = list(range(n))
            self.rng.shuffle(order)
            orders.append(order)
        results: list[dict[int, Option]] = []
        for order in orders:
            if halt():
                break
            served: dict[int, Option] = {}
            for i in order:
                option = self._free_option(i, served)
                if option is not None:
                    served[i] = option
            self._repair(served, halt)
            results.append(served)
            self.report(tr("progress.fixed_holes", done=len(served), total=n))
        most = max((len(r) for r in results), default=0)
        for served in results:
            if len(served) == most:  # only the largest sets count, the rest would just dilute the ranking
                self.consider([self.placement(i, served[i]) for i in sorted(served)])

    def _fits(self, i: int, option: Option, served: dict[int, Option], skip: int = -1) -> bool:
        cap = self.capacity.get(option[0])
        if cap is not None and sum(1 for k, o in served.items() if k != skip and o[0] == option[0]) >= cap:
            return False
        return all(self.compatible(i, option, j, served[j]) for j in self.neighbors[i] if j in served and j != skip)

    def _free_option(self, i: int, served: dict[int, Option], skip: int = -1) -> Optional[Option]:
        return next((o for o in self.options[i] if self._fits(i, o, served, skip)), None)

    def _repair(self, served: dict[int, Option], halt) -> None:
        """Serve one more hole by moving a single blocking neighbour to another option, as long as it helps."""
        improved = True
        while improved and not halt():
            improved = False
            for i in range(self.target):
                if i in served or halt():
                    continue
                for option in self.options[i]:
                    blockers = [j for j in self.neighbors[i] if j in served and not self.compatible(i, option, j, served[j])]
                    if len(blockers) != 1:
                        continue
                    j = blockers[0]
                    trial = dict(served)
                    trial[i] = option
                    other = self._free_option(j, trial, skip=j)
                    if other is not None and self._fits(i, option, {**trial, j: other}, skip=i):
                        served[i], served[j] = option, other
                        improved = True
                        break

    # -- Notes --------------------------------------------------------------------------
    def notes(self, complete: bool) -> list:
        n = self.target
        best = max(self.solutions.values(), key=lambda s: (len(s.placements), s.score.total), default=None)
        served: dict[int, Option] = {}
        index = {hole: i for i, hole in enumerate(self.holes)}
        for q in best.placements if best else []:
            served[index[(q.x, q.y)]] = (q.plane, q.angle, q.cd)
        out = [tr("fixed.note")]
        if len(served) == n:
            out.append(tr("fixed.all_served", n=n))
            return out
        if complete:
            out.append(tr("fixed.proven_impossible", n=n))
        out.append(tr("fixed.partial", served=len(served), n=n))
        for i, (x, y) in enumerate(self.holes):
            if i not in served:
                out.append(tr("fixed.unserved", n=i + 1, x=x, y=y, reason=self.reason(i, served)))
        return out

    def reason(self, i: int, served: dict[int, Option]):
        """Why hole i cannot be served next to the served holes (hole numbers count from 1)."""
        if not self.options[i]:
            x, y = self.holes[i]
            empty = Layout(self.model, self.counter)
            reasons: Tally = Tally()
            for plane in self.usable:
                for angle, cd in self.options_for(plane):
                    result = empty.check(Placement(x, y, plane, angle, cd))
                    if not result.ok:
                        reasons[result.reason] += 1
            return reasons.most_common(1)[0][0] if reasons else tr("fixed.no_option")
        blockers: Tally = Tally()
        for option in self.options[i]:
            for j in self.neighbors[i]:
                if j in served and not self.compatible(i, option, j, served[j]):
                    blockers[j] += 1
        if not blockers:
            return tr("fixed.capacity")
        return tr("fixed.blocked", holes=sorted(j + 1 for j, _ in blockers.most_common(3)))
