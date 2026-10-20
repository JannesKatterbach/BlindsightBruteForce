"""Registry der Optimierungsstrategien. Neue Strategien hier eintragen."""

from __future__ import annotations

from .base import OptimizationResult, Optimizer, ProgressInfo, Solution, StopToken
from .pattern_greedy import PatternGreedyOptimizer

OPTIMIZERS: dict[str, type[Optimizer]] = {PatternGreedyOptimizer.name: PatternGreedyOptimizer}


def get_optimizer(name: str = "pattern_greedy") -> Optimizer:
    try:
        return OPTIMIZERS[name]()
    except KeyError:
        raise ValueError(f"Unbekannter Optimierer '{name}'. Verfuegbar. {sorted(OPTIMIZERS)}") from None


__all__ = [
    "OPTIMIZERS", "get_optimizer", "Optimizer", "OptimizationResult", "ProgressInfo", "Solution", "StopToken",
    "PatternGreedyOptimizer",
]
