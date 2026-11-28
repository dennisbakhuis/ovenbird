"""Replay jobs: one replay at a time in a worker thread, polled for progress and result.

A replay of 30 days takes several seconds, so ``POST replay`` starts a job and returns at
once; ``GET replay/{id}`` reports its phase and progress and, when done, the result. A new
replay cancels the one still running (one at a time, the newest wins). The newest
finished job is kept until the next one starts, at most :data:`KEEP_S` seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.replay.engine import ReplayCancelledError, ReplayRequest, run_replay

LOGGER = logging.getLogger(__name__)
KEEP_S: Final = 3600.0


class JobState(StrEnum):
    """Where a replay job is."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ReplayJob:
    """One replay job.

    Parameters
    ----------
    id
        Random identifier.
    request
        What it replays.
    started
        Wall-clock unix seconds of the start.
    """

    id: str
    request: ReplayRequest
    started: float
    state: JobState = JobState.RUNNING
    phase: str = "queued"
    progress: float = 0.0
    finished: float | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def report(self, phase: str, done: float) -> None:
        """Record the phase and the fraction done (called from the worker thread)."""
        self.phase = phase
        self.progress = round(done, 3)

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        body: dict[str, Any] = {
            "id": self.id,
            "state": self.state.value,
            "phase": self.phase,
            "progress": self.progress,
            "from": iso_from_unix(self.request.start),
            "to": iso_from_unix(self.request.end),
            "config": self.request.config,
            "started_at": iso_from_unix(self.started),
            "finished_at": None if self.finished is None else iso_from_unix(self.finished),
            "error": self.error,
            "result": self.result,
        }
        return body


class ReplayJobs:
    """Runs replay jobs one at a time.

    Parameters
    ----------
    path
        Returns the history database to read.
    clock
        Wall-clock unix seconds.
    """

    def __init__(self, path: Callable[[], Path], clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._jobs: dict[str, ReplayJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def get(self, job_id: str) -> ReplayJob | None:
        """Return a job by id (``None`` when unknown or expired)."""
        self._expire()
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> ReplayJob | None:
        """Ask a running job to stop; returns it (``None`` when unknown)."""
        job = self.get(job_id)
        if job is not None and job.state is JobState.RUNNING:
            job.cancel.set()
        return job

    def start(self, request: ReplayRequest) -> ReplayJob:
        """Start a replay in a worker thread, cancelling the one still running."""
        for job in self._jobs.values():
            if job.state is JobState.RUNNING:
                job.cancel.set()
        self._expire()
        job = ReplayJob(secrets.token_hex(8), request, self._clock())
        self._jobs = {
            key: item for key, item in self._jobs.items() if item.state is JobState.RUNNING
        }
        self._jobs[job.id] = job
        task = asyncio.get_running_loop().create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: ReplayJob) -> None:
        """Run a replay job in a worker thread and store its result or error."""
        try:
            job.result = await asyncio.to_thread(
                run_replay,
                self._path(),
                job.request,
                progress=job.report,
                cancelled=job.cancel.is_set,
            )
            job.state = JobState.DONE
            job.phase = "done"
            job.progress = 1.0
        except ReplayCancelledError:
            job.state = JobState.CANCELLED
        except Exception as exc:
            LOGGER.exception("replay %s failed", job.id)
            job.state = JobState.FAILED
            job.error = str(exc) or type(exc).__name__
        finally:
            job.finished = self._clock()

    def _expire(self) -> None:
        """Forget finished jobs older than the keep time."""
        now = self._clock()
        self._jobs = {
            key: job
            for key, job in self._jobs.items()
            if job.finished is None or now - job.finished <= KEEP_S
        }

    async def close(self) -> None:
        """Cancel the running job and wait for it."""
        for job in self._jobs.values():
            job.cancel.set()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
