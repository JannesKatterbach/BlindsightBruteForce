"""Hintergrundverwaltung von Optimierungslaeufen (ohne UI Abhaengigkeit).

Jeder Lauf laeuft in einem eigenen Thread. Der Status ist jederzeit abfragbar.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .config import ConfigError, Project
from .layout import Counter
from .model import Model
from .optimizers import run_optimizer
from .optimizers.base import OptimizationResult, ProgressInfo, StopToken


@dataclass
class Job:
    id: str
    project: Project
    model: Model
    state: str = "queued"  # queued | running | finished | failed | cancelled
    progress: Optional[ProgressInfo] = None
    result: Optional[OptimizationResult] = None
    error: str = ""
    stop: Optional[StopToken] = None
    thread: Optional[threading.Thread] = None
    started: float = field(default_factory=time.time)

    def best_so_far(self) -> list:
        return list(self.progress.best_placements) if self.progress else []

    def status_dict(self) -> dict:
        prog = self.progress.as_dict(with_best=False) if self.progress else None
        if self.state == "running" and self.stop is not None and prog is not None:
            prog["elapsed"] = self.stop.elapsed
            prog["fraction"] = min(1.0, self.stop.elapsed / self.project.search.time_limit_s)
        return {
            "id": self.id,
            "state": self.state,
            "progress": prog,
            "error": self.error,
            "has_result": self.result is not None,
            "time_limit": self.project.search.time_limit_s,
            "max_candidates": self.project.search.max_candidates,
            "candidates": (self.stop.counter.checks if self.stop else 0),
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, project: Project) -> Job:
        model = Model(project)  # wirft ConfigError bei ungueltigen Daten
        counter = Counter()
        stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
        job = Job(uuid.uuid4().hex[:12], project, model, stop=stop)

        def on_progress(info: ProgressInfo) -> None:
            job.progress = info

        def work() -> None:
            job.state = "running"
            try:
                job.result = run_optimizer(model, on_progress, stop, counter)
                job.state = "cancelled" if stop.reason == "cancelled" else "finished"
            except Exception:  # pragma: no cover - Schutz gegen Thread Absturz
                job.error = traceback.format_exc()
                job.state = "failed"

        job.thread = threading.Thread(target=work, daemon=True, name=f"job-{job.id}")
        with self._lock:
            self.jobs[job.id] = job
            # alte Jobs begrenzen
            for old in sorted(self.jobs.values(), key=lambda j: j.started)[:-20]:
                if old.state != "running":
                    self.jobs.pop(old.id, None)
        job.thread.start()
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError(f"Unbekannter Lauf {job_id}") from None

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.stop:
            job.stop.cancel()


__all__ = ["JobManager", "Job", "ConfigError"]
