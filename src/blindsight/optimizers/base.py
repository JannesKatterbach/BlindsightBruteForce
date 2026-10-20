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
    best_placements: list = field(default_factory=list)  # beste bisherige Anordnung (Live Vorschau)

    def as_dict(self, with_best: bool = True) -> dict:
        d = dict(self.__dict__)
        if not with_best:
            d.pop("best_placements")
        return d


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

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

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


def describe_result(res: OptimizationResult, grid_exact: bool = False) -> None:
    """Setzt Hinweise und die ehrliche Aussage zur Optimalitaet.

    grid_exact. Die Suche war vollstaendig auf einem diskreten Raster (nur dann ist Optimalitaet
    bezogen auf dieses Raster aussagekraeftig).
    """
    target = res.target
    best = res.best
    n = len(best.placements) if best else 0
    if n == 0:
        if res.status in ("completed", "stagnation"):
            res.status = "infeasible"
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
        if grid_exact:
            res.optimality_note = (
                f"Zielanzahl {target} erreicht. Die kleinste Grundflaeche ist nur bezogen auf das untersuchte Raster "
                "optimal, nicht im stetigen Raum."
            )
    elif n >= res.upper_bound:
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
    if res.status == "stagnation":
        res.messages.append("Beendet, weil sich das Ergebnis nach erreichter Zielanzahl nicht mehr verbesserte (Stagnation).")


def begin(model, stop, counter, optimizer_name: str):
    """Gemeinsamer Start. Liefert (Ergebnisobjekt, Fehlmeldungen einer nicht moeglichen Einzeleinheit)."""
    from ..diagnose import single_unit_report
    from ..scoring import upper_bound_count

    res = OptimizationResult(target=model.project.target_count, upper_bound=upper_bound_count(model), optimizer=optimizer_name)
    diag = single_unit_report(model)
    if diag:
        res.status = "infeasible"
        res.messages = diag
        res.optimality_note = "Keine gueltige Loesung. Bereits eine einzelne Einheit ist nicht platzierbar."
        res.candidates = counter.checks
        res.elapsed = stop.elapsed
        return res, True
    return res, False


def finish(res: OptimizationResult, search, stop, counter, grid_exact: bool = False) -> OptimizationResult:
    res.solutions = search.finalize()
    res.candidates = counter.checks
    res.elapsed = stop.elapsed
    res.status = stop.reason or "completed"
    describe_result(res, grid_exact)
    return res
