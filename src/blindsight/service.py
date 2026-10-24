"""Hintergrundverwaltung von Optimierungslaeufen (ohne UI Abhaengigkeit).

Jeder Lauf laeuft in einem eigenen Thread. Der Status ist jederzeit abfragbar. Alle Zugriffe auf
die Jobliste laufen unter einer Sperre, ein Job selbst wird nur von seinem Thread geschrieben.
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

# Zustaende eines Jobs
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_FINISHED = "finished"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
ACTIVE_STATES = (JOB_QUEUED, JOB_RUNNING)

MAX_KEPT_JOBS = 20  # aeltere, beendete Jobs werden verworfen
JOB_ID_LENGTH = 12
SHUTDOWN_JOIN_S = 5.0


class JobNotFound(KeyError):
    """Unbekannte Job Id (Unterklasse von KeyError fuer bestehende Aufrufer)."""

    def __str__(self) -> str:  # KeyError setzt die Meldung sonst in Anfuehrungszeichen
        return str(self.args[0]) if self.args else "Unbekannter Lauf"


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
        """Beste bisherige Anordnung als Liste von Platzierungs Dictionaries (Live Vorschau)."""
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
        """Arbeitsfunktion des Job Threads."""
        self.state = JOB_RUNNING

        def on_progress(info: ProgressInfo) -> None:
            self.progress = info

        try:
            self.result = run_optimizer(self.model, on_progress, self.stop, counter)
            # Abbruch hat Vorrang, auch wenn vorher schon ein anderer Grund (z.B. Zeitlimit) gesetzt war
            self.state = JOB_CANCELLED if self.stop is not None and self.stop.cancelled else JOB_FINISHED
        except Exception:  # Schutz gegen Thread Absturz, der Fehler erscheint im Status
            self.error = traceback.format_exc()
            self.state = JOB_FAILED


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    @property
    def jobs(self) -> dict[str, Job]:
        """Momentaufnahme der Jobs (Kopie, sicher zum Iterieren)."""
        with self._lock:
            return dict(self._jobs)

    def start(self, project: Project) -> Job:
        """Startet einen Lauf. Wirft ConfigError bei ungueltiger Konfiguration."""
        model = Model(project)
        counter = Counter()
        stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
        job = Job(uuid.uuid4().hex[:JOB_ID_LENGTH], project, model, stop=stop)
        job.thread = threading.Thread(target=job.run, args=(counter,), daemon=True, name=f"job-{job.id}")
        with self._lock:
            self._jobs[job.id] = job
            self._evict_old()
        job.thread.start()
        return job

    def _evict_old(self) -> None:
        """Haelt hoechstens MAX_KEPT_JOBS, laufende Jobs bleiben immer (Aufruf unter der Sperre)."""
        for old in sorted(self._jobs.values(), key=lambda j: j.started)[:-MAX_KEPT_JOBS]:
            if not old.active:
                self._jobs.pop(old.id, None)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"Unbekannter Lauf {job_id}")
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
        """Bricht alle Laeufe ab und wartet (begrenzt) auf ihre Threads."""
        self.cancel_all()
        deadline = time.monotonic() + timeout
        for job in self.jobs.values():
            if job.thread is not None and job.thread.is_alive():
                job.thread.join(max(0.0, deadline - time.monotonic()))


__all__ = ["JobManager", "Job", "JobNotFound", "ConfigError"]
