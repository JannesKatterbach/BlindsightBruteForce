"""Interface for optimizers, progress, cancellation and results.

An optimizer is a subclass of ``Optimizer`` and implements ``search``. The template method ``run``
handles the shared frame (counter, cancellation, feasibility check of a single unit). New strategies
register themselves with ``registry.register``.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from ..config import MODE_FREE
from ..diagnose import single_unit_report
from ..i18n import tr
from ..layout import Counter, Placement
from ..scoring import Score, upper_bound_count

# Status of a run (OptimizationResult.status and StopToken.reason)
STATUS_COMPLETED = "completed"
STATUS_TIME_LIMIT = "time_limit"
STATUS_CANDIDATE_LIMIT = "candidate_limit"
STATUS_CANCELLED = "cancelled"
STATUS_STAGNATION = "stagnation"
STATUS_INFEASIBLE = "infeasible"


@dataclass
class Solution:
    placements: list[Placement]
    score: Score
    tile: Optional[dict] = None  # repeating tile the layout is built from (periodic_tile only)

    def as_dict(self) -> dict:
        out = {"placements": [p.as_dict() for p in self.placements], "score": self.score.as_dict()}
        if self.tile is not None:
            out["tile"] = self.tile
        return out


@dataclass
class ProgressInfo:
    phase: str
    candidates: int
    elapsed: float
    best_count: int = 0  # count of the best rated arrangement so far
    best_score: float = 0.0
    message: str = ""
    fraction: float = 0.0  # rough progress 0..1 (time based)
    best_placements: list = field(default_factory=list)  # best arrangement so far (live preview)

    def as_dict(self, with_best: bool = True) -> dict:
        out = asdict(self)
        if not with_best:
            out.pop("best_placements")
        return out


class StopToken:
    """Stop by time limit, candidate limit, stagnation or manual cancel.

    reason is empty as long as the run may continue, otherwise one of the STATUS_* values. The first
    reason set is kept."""

    def __init__(self, time_limit_s: float, max_candidates: int, counter: Counter):
        self.start = time.monotonic()
        self.time_limit = time_limit_s
        self.max_candidates = max_candidates
        self.counter = counter
        self._cancel = threading.Event()
        self.reason = ""

    def cancel(self) -> None:
        self._cancel.set()

    def set_reason(self, reason: str) -> None:
        """Set the stop reason if none is set yet."""
        self.reason = self.reason or reason

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def should_stop(self) -> bool:
        if self._cancel.is_set():
            self.set_reason(STATUS_CANCELLED)
        elif self.elapsed >= self.time_limit:
            self.set_reason(STATUS_TIME_LIMIT)
        elif self.counter.checks >= self.max_candidates:
            self.set_reason(STATUS_CANDIDATE_LIMIT)
        return bool(self.reason)


ProgressCallback = Callable[[ProgressInfo], None]


@dataclass
class OptimizationResult:
    solutions: list[Solution] = field(default_factory=list)
    status: str = STATUS_COMPLETED
    candidates: int = 0
    elapsed: float = 0.0
    target: int = 0
    upper_bound: int = 0
    proven_optimal: bool = False
    optimality_note: str = ""
    messages: list[str] = field(default_factory=list)  # understandable hints and diagnosis
    optimizer: str = ""

    @property
    def best(self) -> Optional[Solution]:
        return self.solutions[0] if self.solutions else None

    @property
    def max_count(self) -> int:
        """Largest unit count among all solutions (the best rated one may have fewer)."""
        return max((len(s.placements) for s in self.solutions), default=0)

    def as_dict(self) -> dict:
        return {
            "solutions": [s.as_dict() for s in self.solutions],
            "status": self.status,
            "candidates": self.candidates,
            "elapsed": self.elapsed,
            "target": self.target,
            "upper_bound": self.upper_bound,
            "proven_optimal": self.proven_optimal,
            "optimality_note": self.optimality_note,
            "messages": self.messages,
            "optimizer": self.optimizer,
        }


class Optimizer(ABC):
    """Base class of all strategies."""

    name = "base"
    supports_parallel = True  # several independent runs with different seeds make sense

    def run(
        self,
        model,
        progress: Optional[ProgressCallback] = None,
        stop: Optional[StopToken] = None,
        counter: Optional[Counter] = None,
    ) -> OptimizationResult:
        """Compute solutions for the compiled model."""
        search = model.project.search
        counter = counter or Counter()
        stop = stop or StopToken(search.time_limit_s, search.max_candidates, counter)
        res, infeasible = begin(model, stop, counter, self.name)
        if infeasible:
            return res
        return self.search(model, res, progress, stop, counter)

    @abstractmethod
    def search(
        self, model, res: OptimizationResult, progress: Optional[ProgressCallback], stop: StopToken, counter: Counter
    ) -> OptimizationResult:
        """The actual search. res is prepared (target, upper bound), call ``finish`` at the end."""


# ---------------------------------------------------------------------------
# Shared frame
# ---------------------------------------------------------------------------
# Statuses with an explanatory hint (catalog key status.<status>)
STATUS_WITH_MESSAGE = (STATUS_TIME_LIMIT, STATUS_CANDIDATE_LIMIT, STATUS_STAGNATION)


def describe_result(res: OptimizationResult, grid_exact: bool = False, free_mode: bool = True) -> None:
    """Set the hints and the honest statement about optimality.

    grid_exact. The search was complete on a discrete grid (only then is optimality with respect to
    this grid meaningful).
    """
    target = res.target
    found = res.max_count
    if found == 0:
        if res.status in (STATUS_COMPLETED, STATUS_STAGNATION):
            res.status = STATUS_INFEASIBLE
        res.messages.append(tr("result.no_solution"))
        res.optimality_note = tr("result.none_found")
        return
    if found >= target:
        res.proven_optimal = False
        key = "result.target_grid" if grid_exact else "result.target_reached" if free_mode else "result.target_reached_goals"
        res.optimality_note = tr(key, target=target)
    elif found >= res.upper_bound:
        res.proven_optimal = True
        res.optimality_note = tr("result.upper_bound", found=found)
    else:
        res.optimality_note = tr("result.partial_note", found=found, target=target, bound=res.upper_bound)
        res.messages.append(tr("result.partial_hint", found=found, target=target))
    best_count = len(res.best.placements) if res.best else 0
    if best_count < found:
        res.messages.append(tr("result.best_fewer", best=best_count, found=found))
    if res.status in STATUS_WITH_MESSAGE:
        res.messages.append(tr(f"status.{res.status}"))


def begin(model, stop: StopToken, counter: Counter, optimizer_name: str) -> tuple[OptimizationResult, bool]:
    """Shared start. Creates the result and checks whether a single unit fits at all.

    Returns (result, infeasible). If the task is infeasible, the result already holds status and
    diagnosis and can be returned directly."""
    res = OptimizationResult(
        target=model.project.target_count, upper_bound=upper_bound_count(model), optimizer=optimizer_name
    )
    diagnosis = single_unit_report(model)
    if diagnosis:
        res.status = STATUS_INFEASIBLE
        res.messages = diagnosis
        res.optimality_note = tr("result.single_infeasible")
        res.candidates = counter.checks
        res.elapsed = stop.elapsed
        return res, True
    return res, False


def finish(res: OptimizationResult, search, stop: StopToken, counter: Counter, grid_exact: bool = False) -> OptimizationResult:
    """Shared end. Takes over the best solutions, counter, time, status and hints."""
    res.solutions = search.finalize()
    res.candidates = counter.checks
    res.elapsed = stop.elapsed
    res.status = stop.reason or STATUS_COMPLETED
    describe_result(res, grid_exact, search.model.project.mode == MODE_FREE)
    return res
