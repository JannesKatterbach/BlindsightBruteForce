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
  4. Goals. The served holes keep their units, but the choice of layer, angle and centre distance is
     improved for the goals of the mode (few layers, small edge, clean alignment). First the same option
     for all holes is tried where possible, then single holes move to better options (HoleGoals).

HoleSearch also serves the pattern mode with individually turned motors (pattern_holes.py), there the
holes come from the lattice instead of project.holes.
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
from ..scoring import GOALS_BY_MODE, alignment_value, lattice_pairs, normalized_weights, unit_edge_reach
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
        search.improve(search.halted)
        out = finish(res, search, stop, counter)
        out.messages[:0] = search.notes(complete)
        return out


class HoleGoals:
    """Fast rating of the goals for one set of served holes (same definitions as scoring.OBJECTIVES).
    The lattice pairs and the reach of every option into the edge strip are computed once."""

    def __init__(self, search: "HoleSearch", served: list[int]):
        proj = search.model.project
        self.search = search
        self.weights = normalized_weights(proj.search.weights, GOALS_BY_MODE[proj.mode])
        self.layer_count = proj.stack.n_motor_planes
        self.border_width = proj.bounds.border_width if proj.bounds.border else 0.0
        self.served = served
        self.pairs = lattice_pairs([search.holes[i] for i in served])
        self._reach: dict[tuple[int, Option], float] = {}

    def reach(self, i: int, option: Option) -> float:
        key = (i, option)
        if key not in self._reach:
            self._reach[key] = unit_edge_reach(self.search.model, self.search.placement(i, option))
        return self._reach[key]

    def value(self, assignment: dict[int, Option]) -> float:
        w = self.weights
        deepest = max(o[0] for o in assignment.values())
        layers = 1.0 - (deepest - 1) / (self.layer_count - 1) if self.layer_count > 1 else 1.0
        border = 1.0
        if self.border_width > 0 and w["border"] > 0:
            border = max(0.0, 1.0 - max(self.reach(i, o) for i, o in assignment.items()) / self.border_width)
        keys = [(assignment[i][0], round(assignment[i][1], 3), assignment[i][2]) for i in self.served]
        return w["layers"] * layers + w["border"] * border + w["alignment"] * alignment_value(self.pairs, keys)


class HoleSearch(SearchBase):
    def __init__(self, *args, holes: Optional[list] = None, **kwargs):
        super().__init__(*args, **kwargs)
        source = holes if holes is not None else self.proj.holes or []
        self.holes = [(float(x), float(y)) for x, y in source]
        self.target = len(self.holes)
        self.assignment: Optional[dict[int, Option]] = None  # complete solution or largest partial one
        self.dropped = 0  # lattice holes left out by the pattern mode (no room for a motor)
        self.phase = tr("phase.fixed_holes")
        empty = Layout(self.model, self.counter)
        self.reach = empty.reach
        self.options: list[list[Option]] = []
        for i, (x, y) in enumerate(self.holes):
            planes = self.plane_order(i)
            self.options.append([(plane, angle, cd) for plane in planes for angle, cd in self.options_for(plane)
                                 if empty.check(Placement(x, y, plane, angle, cd)).ok])
        self._compat: dict[tuple, bool] = {}
        self.capacity = self.model.capacity
        self._link()

    def _link(self) -> None:
        self.neighbors = [[j for j, (u, v) in enumerate(self.holes) if j != i and math.hypot(u - x, v - y) <= self.reach]
                          for i, (x, y) in enumerate(self.holes)]

    def select(self, indices: list[int]) -> None:
        """Keep only these holes (in this order). Used by the pattern mode to drop lattice holes."""
        self.holes = [self.holes[i] for i in indices]
        self.options = [self.options[i] for i in indices]
        self.target = len(self.holes)
        self._compat = {}
        self._link()

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
                self.assignment = dict(chosen)
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
            if len(served) == most and most:  # only the largest sets count, the rest would just dilute the ranking
                self.consider([self.placement(i, served[i]) for i in sorted(served)])
                if self.assignment is None:
                    self.assignment = served

    # -- Goals --------------------------------------------------------------------------
    def improve(self, halt) -> None:
        """Better options for the served holes (goals of the mode). Every improvement is kept."""
        served = dict(self.assignment or {})
        if len(served) < 1:
            return
        self.phase = tr("phase.goals")
        goals = HoleGoals(self, sorted(served))
        best = goals.value(served)

        def keep(candidate: dict[int, Option]) -> None:
            nonlocal served, best
            value = goals.value(candidate)
            if value > best + EPS:
                served, best = dict(candidate), value
                self.consider([self.placement(i, served[i]) for i in sorted(served)])

        # The same option for all holes where it fits (clean alignment, often also few layers)
        first = min(served)
        for option in self.options[first]:
            if halt():
                break
            uniform: dict[int, Option] = {}
            for i in sorted(served):
                choice = option if option in self.options[i] and self._fits(i, option, uniform) else self._free_option(i, uniform)
                if choice is None:
                    break
                uniform[i] = choice
            if len(uniform) == len(served):
                keep(uniform)
        # Single holes to better options until nothing improves
        improved = True
        while improved and not halt():
            improved = False
            order = sorted(served)
            self.rng.shuffle(order)
            for i in order:
                for option in self.options[i]:
                    if halt():
                        return
                    if option == served[i] or not self._fits(i, option, served, skip=i):
                        continue
                    before = best
                    keep({**served, i: option})
                    improved = improved or best > before
            self.report(tr("progress.goals", value=best))

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
