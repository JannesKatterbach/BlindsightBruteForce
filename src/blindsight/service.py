"""Background management of optimization runs (without UI dependency).

Every run has its own thread. The status can be queried at any time. All accesses to the job list
happen under a lock, a job itself is only written by its own thread. The thread runs in a copy of the
caller's context, so it keeps the language of the request that started it.
"""

from __future__ import annotations

import contextvars
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .config import ConfigError, Project
from .i18n import tr
from .layout import Counter
from .model import Model
from .optimizers import run_optimizer
from .optimizers.base import OptimizationResult, ProgressInfo, StopToken

# States of a job
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_FINISHED = "finished"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
ACTIVE_STATES = (JOB_QUEUED, JOB_RUNNING)

MAX_KEPT_JOBS = 20  # older, finished jobs are discarded
JOB_ID_LENGTH = 12
SHUTDOWN_JOIN_S = 5.0


class JobNotFound(KeyError):
    """Unknown job id (subclass of KeyError for existing callers)."""

    def __str__(self) -> str:  # KeyError would otherwise put the message in quotes
        return str(self.args[0]) if self.args else tr("job.unknown")

    @property
    def message(self):
        """The message as given (a LocalText that can be rendered in another language)."""
        return self.args[0] if self.args else tr("job.unknown")


@dataclass
class Job:
    id: str
    project: Project
    model: Model
    state: str = JOB_QUEUED
    progress: Optional[ProgressInfo] = None
    result: Optional[OptimizationResult] = None
    error: str = ""
    stop: Optional[StopToken] = None
    thread: Optional[threading.Thread] = None
    started: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def best_so_far(self) -> list:
        """Best arrangement so far as a list of placement dictionaries (live preview)."""
        progress = self.progress
        return list(progress.best_placements) if progress else []

    def status_dict(self) -> dict:
        progress = self.progress
        prog = progress.as_dict(with_best=False) if progress else None
        if self.state == JOB_RUNNING and self.stop is not None and prog is not None:
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

    def run(self, counter: Counter) -> None:
        """Work function of the job thread."""
        self.state = JOB_RUNNING

        def on_progress(info: ProgressInfo) -> None:
            self.progress = info

        try:
            self.result = run_optimizer(self.model, on_progress, self.stop, counter)
            # Cancellation takes precedence, even if another reason (e.g. time limit) was set before
            self.state = JOB_CANCELLED if self.stop is not None and self.stop.cancelled else JOB_FINISHED
        except Exception:  # protection against a thread crash, the error appears in the status
            self.error = traceback.format_exc()
            self.state = JOB_FAILED


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    @property
    def jobs(self) -> dict[str, Job]:
        """Snapshot of the jobs (copy, safe to iterate)."""
        with self._lock:
            return dict(self._jobs)

    def start(self, project: Project) -> Job:
        """Start a run. Raises ConfigError for an invalid configuration."""
        model = Model(project)
        counter = Counter()
        stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
        job = Job(uuid.uuid4().hex[:JOB_ID_LENGTH], project, model, stop=stop)
        job.thread = threading.Thread(target=contextvars.copy_context().run, args=(job.run, counter), daemon=True,
                                      name=f"job-{job.id}")
        with self._lock:
            self._jobs[job.id] = job
            self._evict_old()
        job.thread.start()
        return job

    def _evict_old(self) -> None:
        """Keep at most MAX_KEPT_JOBS, running jobs always stay (called under the lock)."""
        for old in sorted(self._jobs.values(), key=lambda j: j.started)[:-MAX_KEPT_JOBS]:
            if not old.active:
                self._jobs.pop(old.id, None)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(tr("job.unknown_id", id=job_id))
        return job

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.stop:
            job.stop.cancel()

    def cancel_all(self) -> None:
        for job in self.jobs.values():
            if job.stop:
                job.stop.cancel()

    def shutdown(self, timeout: float = SHUTDOWN_JOIN_S) -> None:
        """Cancel all runs and wait (bounded) for their threads."""
        self.cancel_all()
        deadline = time.monotonic() + timeout
        for job in self.jobs.values():
            if job.thread is not None and job.thread.is_alive():
                job.thread.join(max(0.0, deadline - time.monotonic()))


__all__ = ["JobManager", "Job", "JobNotFound", "ConfigError"]
