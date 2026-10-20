"""Mehrere unabhaengige Laeufe mit verschiedenen Seeds in getrennten Prozessen."""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing

from ..config import Project
from ..layout import Placement
from ..model import Model
from ..scoring import evaluate
from .base import OptimizationResult, ProgressInfo, Solution, describe_result


def _worker(project_dict: dict, optimizer: str) -> dict:
    from . import get_optimizer

    proj = Project.from_dict(project_dict)
    return get_optimizer(optimizer).run(Model(proj)).as_dict()


def run_parallel(model: Model, progress, stop, counter) -> OptimizationResult:
    proj = model.project
    se = proj.search
    base = proj.to_dict()
    jobs = []
    for i in range(se.workers):
        d = dict(base)
        d["search"] = dict(base["search"], seed=se.seed + i, workers=1, time_limit_s=se.time_limit_s)
        jobs.append(d)
    results: list[dict] = []
    # spawn statt fork. Der Aufruf kommt aus einem Thread des Servers, fork waere dort unsicher
    with cf.ProcessPoolExecutor(max_workers=se.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futs = [pool.submit(_worker, d, se.optimizer) for d in jobs]
        pending = set(futs)
        while pending:
            done, pending = cf.wait(pending, timeout=0.3)
            for f in done:
                try:
                    results.append(f.result())
                except Exception as exc:  # Prozessfehler. Andere Laeufe zaehlen weiter
                    results.append({"error": str(exc)})
            if progress:
                progress(ProgressInfo("Parallele Laeufe", sum(r.get("candidates", 0) for r in results), stop.elapsed,
                                      0, 0.0, f"{len(results)} von {len(futs)} Laeufen fertig",
                                      min(1.0, stop.elapsed / se.time_limit_s)))
            if stop.cancelled or stop.elapsed > se.time_limit_s + 30.0:  # Abbruch oder haengender Prozess
                for f in pending:
                    f.cancel()
                for p in list(getattr(pool, "_processes", {}).values()):
                    p.terminate()
                break
    out = OptimizationResult(target=proj.target_count, optimizer=f"{se.optimizer} x{se.workers}")
    sols: dict[tuple, Solution] = {}
    for r in results:
        if "error" in r:
            out.messages.append(f"Ein Lauf ist fehlgeschlagen. {r['error']}")
            continue
        out.upper_bound = r["upper_bound"]
        out.candidates += r["candidates"]
        if r["status"] == "infeasible" and not r["solutions"]:
            out.messages.extend(r["messages"])
        for s in r["solutions"]:
            pls = [Placement(**p) for p in s["placements"]]
            sig = tuple(sorted((round(p.x, 2), round(p.y, 2), p.plane, round(p.angle, 2)) for p in pls))
            sols[sig] = Solution(pls, evaluate(model, pls, se.weights, proj.target_count))
    ranked = sorted(sols.values(), key=lambda s: -s.score.total)
    from ..layout import layout_from_placements

    out.solutions = [s for s in ranked if layout_from_placements(model, s.placements).is_valid()][: se.top_k]
    out.elapsed = stop.elapsed
    stop.should_stop()
    out.status = stop.reason or "completed"
    if not out.upper_bound:
        from ..scoring import upper_bound_count

        out.upper_bound = upper_bound_count(model)
    describe_result(out)
    if len(results) < len(jobs):
        out.messages.append(f"Nur {len(results)} von {len(jobs)} Laeufen wurden beendet.")
    return out
