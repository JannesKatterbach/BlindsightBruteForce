"""Optimization strategies.

The strategies register themselves when their module is imported (``registry.register``). A new
strategy needs its own module with a ``@register`` class, an import here and an entry in the options
of ``search.optimizer`` (config.FIELD_META).
"""

from __future__ import annotations

from typing import Optional

from ..layout import Counter
from . import anneal_free, exhaustive_small, fixed_holes, pattern_greedy, periodic_tile  # noqa: F401  (register themselves)
from .anneal_free import AnnealFreeOptimizer
from .base import OptimizationResult, Optimizer, ProgressCallback, ProgressInfo, Solution, StopToken
from .exhaustive_small import ExhaustiveSmallOptimizer
from .fixed_holes import FixedHolesOptimizer
from .parallel import run_parallel
from .pattern_greedy import PatternGreedyOptimizer
from .periodic_tile import PeriodicTileOptimizer
from .registry import OPTIMIZERS, get_optimizer, register

__all__ = [
    "OPTIMIZERS", "get_optimizer", "register", "Optimizer", "OptimizationResult", "ProgressInfo", "Solution",
    "StopToken", "PatternGreedyOptimizer", "AnnealFreeOptimizer", "ExhaustiveSmallOptimizer", "PeriodicTileOptimizer",
    "FixedHolesOptimizer", "run_optimizer",
]


def run_optimizer(model, progress: Optional[ProgressCallback] = None, stop: Optional[StopToken] = None,
                  counter: Optional[Counter] = None) -> OptimizationResult:
    """Run the optimizer chosen in the configuration (with several processes if search.workers > 1 and
    the strategy supports it)."""
    search = model.project.search
    counter = counter or Counter()
    stop = stop or StopToken(search.time_limit_s, search.max_candidates, counter)
    optimizer = get_optimizer(search.optimizer)
    if search.workers > 1 and optimizer.supports_parallel:
        return run_parallel(model, progress, stop, counter)
    return optimizer.run(model, progress, stop, counter)
