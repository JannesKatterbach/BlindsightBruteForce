"""Mehrere unabhaengige Laeufe mit verschiedenen Seeds in getrennten Prozessen."""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing
from collections import Counter as Tally

from ..config import Project
from ..layout import Counter, Placement, layout_from_placements, layout_signature
from ..model import Model
from ..scoring import evaluate, upper_bound_count
from .base import (
    STATUS_CANDIDATE_LIMIT,
    STATUS_COMPLETED,
    STATUS_INFEASIBLE,
    STATUS_STAGNATION,
    STATUS_TIME_LIMIT,
    OptimizationResult,
    ProgressInfo,
    Solution,
    StopToken,
    describe_result,
)
from .registry import get_optimizer

SEED_MODULUS = 2**31  # Seeds bleiben im gueltigen Bereich von search.seed
POLL_S = 0.3  # Abstand der Fortschrittsmeldungen
HANG_GRACE_S = 30.0  # so lange nach dem Zeitlimit wird auf haengende Prozesse gewartet
# Reihenfolge, in der Abbruchgruende der einzelnen Laeufe den Gesamtstatus bestimmen
STATUS_PRIORITY = (STATUS_TIME_LIMIT, STATUS_CANDIDATE_LIMIT, STATUS_STAGNATION)


def _worker(project_dict: dict, optimizer: str) -> dict:
    project = Project.from_dict(project_dict)
    return get_optimizer(optimizer).run(Model(project)).as_dict()


def _jobs(project: Project) -> list[dict]:
    """Eine Konfiguration je Lauf, jeweils mit eigenem Seed und ohne weitere Parallelisierung."""
    search = project.search
    base = project.to_dict()
    return [
        dict(base, search=dict(base["search"], seed=(search.seed + i) % SEED_MODULUS, workers=1))
        for i in range(search.workers)
    ]


def _terminate(pool: cf.ProcessPoolExecutor) -> None:
    """Beendet alle Prozesse des Pools (oeffentliche Schnittstelle ab Python 3.14, sonst ueber den Pool)."""
    terminate = getattr(pool, "terminate_workers", None)
    if terminate is not None:
        terminate()
        return
    for process in list(getattr(pool, "_processes", {}).values()):
        process.terminate()


def _run_pool(model: Model, jobs: list[dict], progress, stop: StopToken) -> list[dict]:
    search = model.project.search
    results: list[dict] = []
    # spawn statt fork. Der Aufruf kommt aus einem Thread des Servers, fork waere dort unsicher
    with cf.ProcessPoolExecutor(max_workers=search.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(_worker, job, search.optimizer) for job in jobs}
        while pending:
            done, pending = cf.wait(pending, timeout=POLL_S)
            for future in done:
                try:
                    results.append(future.result())
                except Exception as exc:  # Prozessfehler. Andere Laeufe zaehlen weiter
                    results.append({"error": str(exc)})
            if progress:
                progress(ProgressInfo(
                    "Parallele Läufe", sum(r.get("candidates", 0) for r in results), stop.elapsed, 0, 0.0,
                    f"{len(results)} von {len(jobs)} Läufen fertig", min(1.0, stop.elapsed / search.time_limit_s),
                ))
            if stop.cancelled or stop.elapsed > search.time_limit_s + HANG_GRACE_S:
                for future in pending:
                    future.cancel()
                _terminate(pool)
                break
    return results


def _combined_status(stop: StopToken, statuses: list[str]) -> str:
    """Eigener Abbruchgrund zuerst, sonst der wichtigste Grund der einzelnen Laeufe."""
    stop.should_stop()
    if stop.reason:
        return stop.reason
    for status in STATUS_PRIORITY:
        if status in statuses:
            return status
    return STATUS_COMPLETED


def run_parallel(model: Model, progress, stop: StopToken, counter: Counter) -> OptimizationResult:
    """Startet search.workers Laeufe und fuehrt deren Loesungen zusammen (neu bewertet und geprueft)."""
    project = model.project
    search = project.search
    jobs = _jobs(project)
    results = _run_pool(model, jobs, progress, stop)

    out = OptimizationResult(target=project.target_count, optimizer=f"{search.optimizer} x{search.workers}")
    solutions: dict[tuple, Solution] = {}
    statuses: list[str] = []
    diagnoses: Tally[str] = Tally()
    for r in results:
        if "error" in r:
            out.messages.append(f"Ein Lauf ist fehlgeschlagen. {r['error']}")
            continue
        out.upper_bound = r["upper_bound"]
        out.candidates += r["candidates"]
        statuses.append(r["status"])
        if r["status"] == STATUS_INFEASIBLE and not r["solutions"]:
            diagnoses.update(m for m in r["messages"] if m not in diagnoses)
        for s in r["solutions"]:
            placements = [Placement(**p) for p in s["placements"]]
            solutions[layout_signature(placements)] = Solution(
                placements, evaluate(model, placements, search.weights, project.target_count)
            )
    out.messages.extend(diagnoses)  # jede Diagnose nur einmal, in der ersten Reihenfolge
    ranked = sorted(solutions.values(), key=lambda s: -s.score.total)
    out.solutions = [s for s in ranked if layout_from_placements(model, s.placements).is_valid()][: search.top_k]
    out.elapsed = stop.elapsed
    out.status = _combined_status(stop, statuses)
    out.upper_bound = out.upper_bound or upper_bound_count(model)
    counter.checks = max(counter.checks, out.candidates)
    describe_result(out)
    if len(results) < len(jobs):
        out.messages.append(f"Nur {len(results)} von {len(jobs)} Läufen wurden beendet.")
    return out
