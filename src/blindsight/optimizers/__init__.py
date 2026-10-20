"""Registry der Optimierungsstrategien. Neue Strategien hier eintragen."""

from __future__ import annotations

from .base import OptimizationResult, Optimizer, ProgressInfo, Solution, StopToken
from .anneal_free import AnnealFreeOptimizer
from .exhaustive_small import ExhaustiveSmallOptimizer
from .pattern_greedy import PatternGreedyOptimizer

OPTIMIZERS: dict[str, type[Optimizer]] = {
    c.name: c for c in (PatternGreedyOptimizer, AnnealFreeOptimizer, ExhaustiveSmallOptimizer)
}


def get_optimizer(name: str = "pattern_greedy") -> Optimizer:
    try:
        return OPTIMIZERS[name]()
    except KeyError:
        raise ValueError(f"Unbekannter Optimierer '{name}'. Verfuegbar. {sorted(OPTIMIZERS)}") from None


__all__ = [
    "OPTIMIZERS", "get_optimizer", "Optimizer", "OptimizationResult", "ProgressInfo", "Solution", "StopToken",
    "PatternGreedyOptimizer", "AnnealFreeOptimizer", "ExhaustiveSmallOptimizer", "run_optimizer",
]


def run_optimizer(model, progress=None, stop=None, counter=None) -> OptimizationResult:
    """Fuehrt den in der Konfiguration gewaehlten Optimierer aus (optional mit mehreren Prozessen)."""
    from ..layout import Counter
    from .parallel import run_parallel

    se = model.project.search
    counter = counter or Counter()
    stop = stop or StopToken(se.time_limit_s, se.max_candidates, counter)
    if se.workers > 1 and se.optimizer != "exhaustive_small":
        return run_parallel(model, progress, stop, counter)
    return get_optimizer(se.optimizer).run(model, progress, stop, counter)
