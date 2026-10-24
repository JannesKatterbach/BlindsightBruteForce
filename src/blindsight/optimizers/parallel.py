"""Several independent runs with different seeds in separate processes."""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing
from collections import Counter as Tally

from ..config import Project
from ..i18n import tr
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

SEED_MODULUS = 2**31  # seeds stay within the valid range of search.seed
POLL_S = 0.3  # interval of the progress reports
HANG_GRACE_S = 30.0  # how long to wait for hanging processes after the time limit
# Order in which the stop reasons of the single runs decide the overall status
STATUS_PRIORITY = (STATUS_TIME_LIMIT, STATUS_CANDIDATE_LIMIT, STATUS_STAGNATION)


def _worker(project_dict: dict, optimizer: str) -> dict:
    project = Project.from_dict(project_dict)
    return get_optimizer(optimizer).run(Model(project)).as_dict()


def _jobs(project: Project) -> list[dict]:
    """One configuration per run, each with its own seed and without further parallelism."""
    search = project.search
    base = project.to_dict()
    return [
        dict(base, search=dict(base["search"], seed=(search.seed + i) % SEED_MODULUS, workers=1))
        for i in range(search.workers)
    ]


def _terminate(pool: cf.ProcessPoolExecutor) -> None:
    """Terminate all processes of the pool (public interface from Python 3.14 on, otherwise via the pool)."""
    terminate = getattr(pool, "terminate_workers", None)
    if terminate is not None:
        terminate()
        return
    for process in list(getattr(pool, "_processes", {}).values()):
        process.terminate()


def _run_pool(model: Model, jobs: list[dict], progress, stop: StopToken) -> list[dict]:
    search = model.project.search
    results: list[dict] = []
    # spawn instead of fork. The call comes from a server thread, fork would be unsafe there
    with cf.ProcessPoolExecutor(max_workers=search.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(_worker, job, search.optimizer) for job in jobs}
        while pending:
            done, pending = cf.wait(pending, timeout=POLL_S)
            for future in done:
                try:
                    results.append(future.result())
                except Exception as exc:  # process error. Other runs still count
                    results.append({"error": str(exc)})
            if progress:
                progress(ProgressInfo(
                    tr("phase.parallel"), sum(r.get("candidates", 0) for r in results), stop.elapsed, 0, 0.0,
                    tr("progress.runs_done", done=len(results), total=len(jobs)), min(1.0, stop.elapsed / search.time_limit_s),
                ))
            if stop.cancelled or stop.elapsed > search.time_limit_s + HANG_GRACE_S:
                for future in pending:
                    future.cancel()
                _terminate(pool)
                break
    return results


def _combined_status(stop: StopToken, statuses: list[str]) -> str:
    """Own stop reason first, otherwise the most important reason of the single runs."""
    stop.should_stop()
    if stop.reason:
        return stop.reason
    for status in STATUS_PRIORITY:
        if status in statuses:
            return status
    return STATUS_COMPLETED


def run_parallel(model: Model, progress, stop: StopToken, counter: Counter) -> OptimizationResult:
    """Start search.workers runs and merge their solutions (scored and checked again)."""
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
            out.messages.append(tr("parallel.run_failed", error=r["error"]))
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
    out.messages.extend(diagnoses)  # every diagnosis only once, in the first order
    ranked = sorted(solutions.values(), key=lambda s: -s.score.total)
    out.solutions = [s for s in ranked if layout_from_placements(model, s.placements).is_valid()][: search.top_k]
    out.elapsed = stop.elapsed
    out.status = _combined_status(stop, statuses)
    out.upper_bound = out.upper_bound or upper_bound_count(model)
    counter.checks = max(counter.checks, out.candidates)
    describe_result(out)
    if len(results) < len(jobs):
        out.messages.append(tr("parallel.runs_incomplete", done=len(results), total=len(jobs)))
    return out
