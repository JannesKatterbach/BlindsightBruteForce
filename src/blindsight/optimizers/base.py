"""Schnittstelle fuer Optimierer, Fortschritt, Abbruch und Ergebnisse.

Ein Optimierer ist eine Unterklasse von ``Optimizer`` und implementiert ``search``. Die
Template Methode ``run`` erledigt den gemeinsamen Rahmen (Zaehler, Abbruch, Machbarkeitspruefung
einer Einzeleinheit). Neue Strategien registrieren sich mit ``registry.register``.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from ..diagnose import single_unit_report
from ..layout import Counter, Placement
from ..scoring import Score, upper_bound_count

# Status eines Laufs (OptimizationResult.status und StopToken.reason)
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

    def as_dict(self) -> dict:
        return {"placements": [p.as_dict() for p in self.placements], "score": self.score.as_dict()}


@dataclass
class ProgressInfo:
    phase: str
    candidates: int
    elapsed: float
    best_count: int = 0  # Anzahl der bisher bestbewerteten Anordnung
    best_score: float = 0.0
    message: str = ""
    fraction: float = 0.0  # grober Fortschritt 0..1 (Zeitbasis)
    best_placements: list = field(default_factory=list)  # beste bisherige Anordnung (Live Vorschau)

    def as_dict(self, with_best: bool = True) -> dict:
        out = asdict(self)
        if not with_best:
            out.pop("best_placements")
        return out


class StopToken:
    """Abbruch ueber Zeitlimit, Kandidatenlimit, Stagnation oder manuelles Cancel.

    reason ist leer, solange der Lauf weitergehen darf, sonst einer der STATUS_* Werte.
    Der erste gesetzte Grund bleibt erhalten."""

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
        """Setzt den Abbruchgrund, wenn noch keiner gesetzt ist."""
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
    messages: list[str] = field(default_factory=list)  # verstaendliche Hinweise und Diagnose
    optimizer: str = ""

    @property
    def best(self) -> Optional[Solution]:
        return self.solutions[0] if self.solutions else None

    @property
    def max_count(self) -> int:
        """Groesste Einheitenzahl unter allen Loesungen (die bestbewertete kann weniger haben)."""
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
    """Basisklasse aller Strategien."""

    name = "base"
    supports_parallel = True  # mehrere unabhaengige Laeufe mit verschiedenen Seeds sind sinnvoll

    def run(
        self,
        model,
        progress: Optional[ProgressCallback] = None,
        stop: Optional[StopToken] = None,
        counter: Optional[Counter] = None,
    ) -> OptimizationResult:
        """Berechnet Loesungen fuer das kompilierte Modell."""
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
        """Eigentliche Suche. res ist vorbereitet (Ziel, Obergrenze), am Ende ``finish`` aufrufen."""


# ---------------------------------------------------------------------------
# Gemeinsamer Rahmen
# ---------------------------------------------------------------------------
MSG_NO_SOLUTION = (
    "Es wurde keine gültige Anordnung gefunden. Mögliche Ursachen. Bauraum zu klein, Sicherheitsabstand zu groß, "
    "Motoren zu hoch oder zu breit für die Ebenenabstände, zu wenige erlaubte Winkel oder Ebenen."
)
STATUS_MESSAGES = {
    STATUS_TIME_LIMIT: "Das Zeitlimit wurde erreicht. Mehr Rechenzeit kann bessere Ergebnisse liefern.",
    STATUS_CANDIDATE_LIMIT: "Das Kandidatenlimit wurde erreicht.",
    STATUS_STAGNATION: "Beendet, weil sich das Ergebnis nach erreichter Zielanzahl nicht mehr verbesserte (Stagnation).",
}


def describe_result(res: OptimizationResult, grid_exact: bool = False) -> None:
    """Setzt Hinweise und die ehrliche Aussage zur Optimalitaet.

    grid_exact. Die Suche war vollstaendig auf einem diskreten Raster (nur dann ist Optimalitaet
    bezogen auf dieses Raster aussagekraeftig).
    """
    target = res.target
    found = res.max_count
    if found == 0:
        if res.status in (STATUS_COMPLETED, STATUS_STAGNATION):
            res.status = STATUS_INFEASIBLE
        res.messages.append(MSG_NO_SOLUTION)
        res.optimality_note = "Keine Lösung gefunden. Das beweist nicht, dass keine existiert."
        return
    if found >= target:
        res.proven_optimal = False
        if grid_exact:
            res.optimality_note = (
                f"Zielanzahl {target} erreicht. Die kleinste Grundfläche ist nur bezogen auf das untersuchte Raster "
                "optimal, nicht im stetigen Raum."
            )
        else:
            res.optimality_note = (
                f"Zielanzahl {target} erreicht, die Anzahl kann nicht weiter steigen. Grundfläche, Gleichmäßigkeit und "
                "Regelmäßigkeit sind beste gefundene Werte und nicht als optimal bewiesen."
            )
    elif found >= res.upper_bound:
        res.proven_optimal = True
        res.optimality_note = f"{found} Stangen erreichen die theoretische Obergrenze des Bauraums."
    else:
        res.optimality_note = (
            f"Nur {found} von {target} Stangen platzierbar. Beste gefundene Lösung, nicht als optimal bewiesen "
            f"(Obergrenze nach Oler {res.upper_bound})."
        )
        res.messages.append(
            f"Nur {found} von {target} Einheiten konnten kollisionsfrei platziert werden. "
            "Hilfreich wären ein größerer Bauraum, mehr Motorebenen, kleinerer Sicherheitsabstand, "
            "kleinere Motoren oder mehr erlaubte Winkel. Oder mehr Rechenzeit."
        )
    best_count = len(res.best.placements) if res.best else 0
    if best_count < found:
        res.messages.append(
            f"Die bestbewertete Anordnung hat {best_count} Einheiten. Anordnungen mit {found} Einheiten sind unter den "
            "Ergebnissen, liegen nach der Gewichtung der Ziele aber dahinter."
        )
    if res.status in STATUS_MESSAGES:
        res.messages.append(STATUS_MESSAGES[res.status])


def begin(model, stop: StopToken, counter: Counter, optimizer_name: str) -> tuple[OptimizationResult, bool]:
    """Gemeinsamer Start. Legt das Ergebnis an und prueft, ob ueberhaupt eine Einzeleinheit passt.

    Rueckgabe (Ergebnis, nicht machbar). Ist die Aufgabe nicht machbar, enthaelt das Ergebnis
    bereits Status und Diagnose und kann direkt zurueckgegeben werden."""
    res = OptimizationResult(
        target=model.project.target_count, upper_bound=upper_bound_count(model), optimizer=optimizer_name
    )
    diagnosis = single_unit_report(model)
    if diagnosis:
        res.status = STATUS_INFEASIBLE
        res.messages = diagnosis
        res.optimality_note = "Keine gültige Lösung. Bereits eine einzelne Einheit ist nicht platzierbar."
        res.candidates = counter.checks
        res.elapsed = stop.elapsed
        return res, True
    return res, False


def finish(res: OptimizationResult, search, stop: StopToken, counter: Counter, grid_exact: bool = False) -> OptimizationResult:
    """Gemeinsamer Abschluss. Uebernimmt die besten Loesungen, Zaehler, Zeit, Status und Hinweise."""
    res.solutions = search.finalize()
    res.candidates = counter.checks
    res.elapsed = stop.elapsed
    res.status = stop.reason or STATUS_COMPLETED
    describe_result(res, grid_exact)
    return res
