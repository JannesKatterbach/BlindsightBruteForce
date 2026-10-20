"""Schnittstelle fuer Optimierer, Fortschritt, Abbruch und Ergebnisse.

Ein Optimierer ist ein Objekt mit run(model, progress, stop) -> OptimizationResult.
Neue Strategien registrieren sich in optimizers/__init__.py.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..layout import Counter, Placement
from ..scoring import Score


@dataclass
class Solution:
    placements: list[Placement]
    score: Score

    def as_dict(self) -> dict:
        return {"placements": [p.as_dict() for p in self.placements], "score": self.score.as_dict()}


@dataclass
class ProgressInfo:
    phase: str
    candidates: int
    elapsed: float
    best_count: int = 0
    best_score: float = 0.0
    message: str = ""
    fraction: float = 0.0  # grober Fortschritt 0..1 (Zeitbasis)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class StopToken:
    """Abbruch ueber Zeitlimit, Kandidatenlimit oder manuelles Cancel."""

    def __init__(self, time_limit_s: float, max_candidates: int, counter: Counter):
        self.start = time.monotonic()
        self.time_limit = time_limit_s
        self.max_candidates = max_candidates
        self.counter = counter
        self._cancel = threading.Event()
        self.reason = ""

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def should_stop(self) -> bool:
        if self._cancel.is_set():
            self.reason = self.reason or "cancelled"
        elif self.elapsed >= self.time_limit:
            self.reason = self.reason or "time_limit"
        elif self.counter.checks >= self.max_candidates:
            self.reason = self.reason or "candidate_limit"
        return bool(self.reason)


ProgressCallback = Callable[[ProgressInfo], None]


@dataclass
class OptimizationResult:
    solutions: list[Solution] = field(default_factory=list)
    status: str = "completed"  # completed | time_limit | candidate_limit | cancelled | infeasible
    candidates: int = 0
    elapsed: float = 0.0
    target: int = 0
    upper_bound: int = 0
    proven_optimal: bool = False
    optimality_note: str = ""
    messages: list[str] = field(default_factory=list)  # verstaendliche Hinweise und Diagnose
    optimizer: str = ""

    @property
    def best(self) -> Optional[Solution]:
        return self.solutions[0] if self.solutions else None

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
    name = "base"

    @abstractmethod
    def run(
        self,
        model,
        progress: Optional[ProgressCallback] = None,
        stop: Optional[StopToken] = None,
        counter: Optional[Counter] = None,
    ) -> OptimizationResult:
        """Berechnet Loesungen fuer das kompilierte Modell."""
