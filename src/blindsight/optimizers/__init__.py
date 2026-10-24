"""Optimierungsstrategien.

Die Strategien registrieren sich beim Import ihres Moduls (``registry.register``). Eine neue
Strategie braucht ein eigenes Modul mit ``@register`` Klasse, einen Import hier und einen
Eintrag in den Optionen von ``search.optimizer`` (config.FIELD_META).
"""

from __future__ import annotations

from typing import Optional

from ..layout import Counter
from . import anneal_free, exhaustive_small, pattern_greedy  # noqa: F401  (registrieren sich)
from .anneal_free import AnnealFreeOptimizer
from .base import OptimizationResult, Optimizer, ProgressCallback, ProgressInfo, Solution, StopToken
from .exhaustive_small import ExhaustiveSmallOptimizer
from .parallel import run_parallel
from .pattern_greedy import PatternGreedyOptimizer
from .registry import OPTIMIZERS, get_optimizer, register

__all__ = [
    "OPTIMIZERS", "get_optimizer", "register", "Optimizer", "OptimizationResult", "ProgressInfo", "Solution",
    "StopToken", "PatternGreedyOptimizer", "AnnealFreeOptimizer", "ExhaustiveSmallOptimizer", "run_optimizer",
]


def run_optimizer(model, progress: Optional[ProgressCallback] = None, stop: Optional[StopToken] = None,
                  counter: Optional[Counter] = None) -> OptimizationResult:
    """Fuehrt den in der Konfiguration gewaehlten Optimierer aus (mit mehreren Prozessen, wenn
    search.workers > 1 und die Strategie das unterstuetzt)."""
    search = model.project.search
    counter = counter or Counter()
    stop = stop or StopToken(search.time_limit_s, search.max_candidates, counter)
    optimizer = get_optimizer(search.optimizer)
    if search.workers > 1 and optimizer.supports_parallel:
        return run_parallel(model, progress, stop, counter)
    return optimizer.run(model, progress, stop, counter)
