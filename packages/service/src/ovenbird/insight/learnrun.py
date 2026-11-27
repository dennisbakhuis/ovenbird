"""Runs the house-model learner as a supervised, low-priority child process.

The learner (``python -m ovenbird_sim.learn``) needs numpy and scipy, which the service
never imports: it is started as a separate process, only when the installation has the
learner extra (``importlib.util.find_spec``), one run at a time, from fixed arguments
built from the data directory. One building-only run takes about 11 s of CPU and
240 MB of memory; the child gets a lowered priority, a CPU limit, its own process
group (a kill takes its threads and children), a wall-clock timeout and a resident
memory cap checked every few seconds on Linux. The child is started with ``-P`` (the
working directory is never put on ``sys.path``, so a file planted in the data volume is
never imported), from the learner directory, and lowers its own priority and CPU limit
(``--low-priority``); it holds an exclusive lock on ``<models>/.learner.lock`` and exits
with 75 when another learner has it (not a failure). A scheduled run is skipped, and
tried again the next night, while less than 400 MB of memory is available.

Schedule (wall clock): with ``house_learn_enabled`` a run is due when the learner's
last ``status.json`` is older than ``house_learn_interval_h`` (one hour of slack, so a
weekly run keeps its night), or after a day when the last outcome was ``learning``
(not enough data yet). Scheduled runs start only between 02:00 and 05:00 in
``control_timezone``, never within ten minutes of the service start, never within a
day of a failure and never when the clock is simulated. A run requested through the
API starts at once. The last failure is kept as a fact so the backoff survives a
restart; the next successful run clears it. The learner's own files are still read
only through :mod:`ovenbird.insight.house`.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import os
import re
import signal
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as day_time
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from zoneinfo import ZoneInfo

from ovenbird.clock import iso_z
from ovenbird.config import Settings
from ovenbird.insight import house
from ovenbird.system.facts import Facts

LOGGER = logging.getLogger("ovenbird.insight")
MODULE: Final = "ovenbird_sim.learn"
FACT_KEY: Final = "learner_run_failure"
TIMEOUT_S: Final = 30 * 60.0
MEMORY_CAP_BYTES: Final = 512 * 1024 * 1024
MIN_AVAILABLE_BYTES: Final = 400 * 1024 * 1024
COOL_DOWN: Final = timedelta(minutes=5)
BUSY_EXIT: Final = 75
SUMMARY_CHARS: Final = 200
WATCH_S: Final = 5.0
KILL_GRACE_S: Final = 5.0
DRAIN_S: Final = 5.0
TICK_S: Final = 60.0
TAIL_BYTES: Final = 3840
MAX_DETAIL: Final = 4000
CPU_LIMIT_S: Final = 1800
START_DELAY: Final = timedelta(minutes=10)
FAILURE_BACKOFF: Final = timedelta(hours=24)
LEARNING_RETRY_H: Final = 24.0
DUE_SLACK_H: Final = 1.0
MIN_GAP: Final = timedelta(hours=6)
NIGHT_START_H: Final = 2
NIGHT_END_H: Final = 5
THREAD_LIMITS: Final = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
INHERITED_ENV: Final = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TZ",
)

PATH_PATTERN: Final = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s:'\"()<>,;]+(?:[\\/][^\s:'\"()<>,;]+)*")

type State = Literal["idle", "running", "unavailable"]
type Reason = Literal["timeout", "memory", "exit", "spawn"]
type Json = dict[str, Any]

STATES: Final = ("idle", "running", "unavailable")
FAILURE_REASONS: Final = ("timeout", "memory", "exit", "spawn")
REFUSAL_CODES: Final = ("learner_running", "learner_unavailable")


class LearnerRunningError(RuntimeError):
    """A run is already in progress."""


class LearnerUnavailableError(RuntimeError):
    """The learner is not installed in this service."""


class LearnerLowMemoryError(LearnerUnavailableError):
    """Too little memory is available to start a run."""


class LearnerCoolingDownError(LearnerRunningError):
    """A run finished a moment ago."""


class Child(Protocol):
    """The part of a child process the runner uses (tests pass a fake)."""

    @property
    def pid(self) -> int | None:
        """Process id."""
        ...

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        """Combined output stream."""
        ...

    async def wait(self) -> int:
        """Wait for the exit and return the code (negative for a signal)."""
        ...

    def terminate(self) -> None:
        """Ask the child and its process group to stop."""
        ...

    def kill(self) -> None:
        """Kill the child and its process group."""
        ...


type Spawn = Callable[[Sequence[str], Mapping[str, str], Path], Awaitable[Child]]
type Outcome = Failure | Literal["busy"] | None
type Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Failure:
    """A failed attempt: when, why and what the child said last."""

    at: datetime
    reason: Reason
    detail: str

    @property
    def summary(self) -> str:
        """The last line of the detail with absolute paths removed."""
        lines = [line.strip() for line in self.detail.splitlines() if line.strip()]
        line = lines[-1] if lines else ""
        return PATH_PATTERN.sub("<path>", line)[:SUMMARY_CHARS]

    def to_json(self, *, full: bool = True) -> Json:
        """Return the API form; ``full=False`` replaces the detail by :attr:`summary`."""
        detail = self.detail if full else self.summary
        return {"at": iso_z(self.at), "reason": self.reason, "detail": detail}


def learner_installed() -> bool:
    """Whether ``ovenbird_sim.learn`` can be imported (the learner extra is installed)."""
    try:
        return importlib.util.find_spec(MODULE) is not None
    except ImportError, ValueError:
        return False


def read_mem_available_bytes() -> int | None:
    """Return ``MemAvailable`` from ``/proc/meminfo`` (``None`` where there is none)."""
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        return None
    return None


class GroupChild:
    """A child process in its own process group; signals reach the whole group."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    @property
    def pid(self) -> int | None:
        """Process id."""
        return self.process.pid

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        """Combined output stream."""
        return self.process.stdout

    async def wait(self) -> int:
        """Wait for the exit."""
        return await self.process.wait()

    def _signal(self, number: int) -> None:
        if self.process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix":
                os.killpg(self.process.pid, number)
            else:
                self.process.send_signal(number)

    def terminate(self) -> None:
        """Send SIGTERM to the group."""
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        """Send SIGKILL to the group."""
        self._signal(getattr(signal, "SIGKILL", signal.SIGTERM))


async def spawn_child(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Child:
    """Start the learner: no shell, own process group, output captured, from ``cwd``."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=dict(env),
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )
    return GroupChild(process)


def read_rss_bytes(pid: int) -> int | None:
    """Return the resident set size of ``pid`` from ``/proc`` (``None`` where there is none)."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        return None
    return None


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except OSError, ValueError, KeyError:
        return UTC


def in_night_window(moment: datetime, zone: tzinfo) -> bool:
    """Whether ``moment`` is between 02:00 and 05:00 local time."""
    return NIGHT_START_H <= moment.astimezone(zone).hour < NIGHT_END_H


def next_night_window(moment: datetime, zone: tzinfo) -> datetime:
    """Return ``moment`` when it is inside the night window, else the next 02:00 (UTC)."""
    if in_night_window(moment, zone):
        return moment
    local = moment.astimezone(zone)
    day: date = local.date()
    if local.hour >= NIGHT_START_H:
        day += timedelta(days=1)
    return datetime.combine(day, day_time(NIGHT_START_H), tzinfo=zone).astimezone(UTC)


def _text(tail: bytes) -> str:
    return tail.decode("utf-8", errors="replace").strip()


class LearnRunner:
    """Starts, watches and schedules learner runs.

    Parameters
    ----------
    settings
        Returns the effective settings.
    facts
        Keeps the last failure across restarts.
    available
        Whether the learner is installed.
    spawn, rss, memory_available, now, monotonic, sleep, export
        Process start, memory reader, wall clock, monotonic clock, sleep and the
        history export; tests replace them.
    """

    def __init__(
        self,
        settings: Callable[[], Settings],
        facts: Facts,
        *,
        available: Callable[[], bool] = learner_installed,
        spawn: Spawn = spawn_child,
        rss: Callable[[int], int | None] = read_rss_bytes,
        memory_available: Callable[[], int | None] = read_mem_available_bytes,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        export: Callable[[Settings], Path | None] = house.export_history,
    ) -> None:
        self.settings = settings
        self.facts = facts
        self.available = bool(available())
        self.spawn = spawn
        self.rss = rss
        self.memory_available = memory_available
        self.now = now
        self.monotonic = monotonic
        self.sleep = sleep
        self.export = export
        self.born = now()
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.skipped_until: datetime | None = None
        self.skip_reason: str | None = None
        self.snapshot_age_s: float | None = None
        self.failure: Failure | None = self._load_failure()
        self._task: asyncio.Task[None] | None = None

    def _load_failure(self) -> Failure | None:
        raw = self.facts.get(FACT_KEY)
        if not isinstance(raw, dict):
            return None
        at, reason, detail = _parse(raw.get("at")), raw.get("reason"), raw.get("detail")
        if at is None or reason not in FAILURE_REASONS or not isinstance(detail, str):
            return None
        return Failure(at, reason, detail[-MAX_DETAIL:])

    @property
    def running(self) -> bool:
        """Whether a run is in progress."""
        return self._task is not None and not self._task.done()

    @property
    def state(self) -> State:
        """``unavailable``, ``running`` or ``idle``."""
        if not self.available:
            return "unavailable"
        return "running" if self.running else "idle"

    def start(self, *, scheduled: bool = False) -> None:
        """Begin a run now.

        Parameters
        ----------
        scheduled
            A run the schedule starts; it is not held back by the cool-down.

        Raises
        ------
        LearnerUnavailableError
            When the learner is not installed (or, as ``LearnerLowMemoryError``, when
            less than 400 MB of memory is available).
        LearnerRunningError
            When a run is in progress (or, as ``LearnerCoolingDownError``, ended
            less than five minutes ago and the run is not scheduled).
        """
        if not self.available:
            raise LearnerUnavailableError("the house model learner is not installed")
        if self.running:
            raise LearnerRunningError("a learner run is already in progress")
        if (
            not scheduled
            and self.finished_at is not None
            and self.now() - self.finished_at < COOL_DOWN
        ):
            raise LearnerCoolingDownError("a learner run ended a moment ago; try again shortly")
        free = self.memory_available()
        if free is not None and free < MIN_AVAILABLE_BYTES:
            raise LearnerLowMemoryError(
                f"only {free / 2**20:.0f} MB of memory is available, "
                f"{MIN_AVAILABLE_BYTES / 2**20:.0f} MB are needed"
            )
        self.started_at = self.now()
        self._task = asyncio.create_task(self._execute(), name="learner-run")

    async def run(self) -> None:
        """Schedule runs forever (a supervised component); a running child dies with it."""
        try:
            while True:
                await self.tick()
                await self.sleep(TICK_S)
        finally:
            if self._task is not None and not self._task.done():
                self._task.cancel()

    def _base(self, run: Json | None, settings: Settings) -> datetime:
        """Earliest moment the schedule allows a run, before the night window."""
        base = self.born + START_DELAY
        at = _parse(run.get("at")) if run is not None else None
        if at is not None:
            at = min(at, self.now())
            period = settings.house_learn_interval_h
            if run is not None and run.get("outcome") == "learning":
                period = min(period, LEARNING_RETRY_H)
            base = max(base, at + timedelta(hours=period - DUE_SLACK_H))
        if self.failure is not None:
            base = max(base, self.failure.at + FAILURE_BACKOFF)
        if self.finished_at is not None:
            base = max(base, self.finished_at + MIN_GAP)
        if self.skipped_until is not None:
            base = max(base, self.skipped_until)
        return base

    async def tick(self) -> None:
        """Start a scheduled run when one is due (called every ``TICK_S``)."""
        if not self.available or self.running:
            return
        settings = self.settings()
        if not settings.house_learn_enabled or not settings.realtime_clock:
            return
        now = self.now()
        if not in_night_window(now, _zone(settings.control_timezone)):
            return
        run = await asyncio.to_thread(house.last_run, house.models_dir(settings))
        if now < self._base(run, settings):
            return
        try:
            self.start(scheduled=True)
        except LearnerLowMemoryError as exc:
            self.skip_reason = str(exc)
            self.skipped_until = next_night_window(
                now + timedelta(hours=4), _zone(settings.control_timezone)
            )
            LOGGER.warning("scheduled house model learner run skipped: %s", exc)
            return
        except LearnerRunningError:
            return
        self.skipped_until = None
        self.skip_reason = None
        LOGGER.info("scheduled house model learner run started")

    def payload(self, *, full_detail: bool = False) -> Json:
        """Return the body of ``GET insight/house/run`` (reads ``status.json``).

        Parameters
        ----------
        full_detail
            Include the child's output tail in ``failure.detail`` (operate role and up);
            otherwise only a one-line summary without paths.
        """
        settings = self.settings()
        run = house.last_run(house.models_dir(settings))
        next_due: str | None = None
        if self.available and settings.house_learn_enabled and settings.realtime_clock:
            zone = _zone(settings.control_timezone)
            after = max(self._base(run, settings), self.now())
            next_due = iso_z(next_night_window(after, zone))
        last: Json | None = None
        if (
            run is not None
            and isinstance(run.get("at"), str)
            and isinstance(run.get("outcome"), str)
        ):
            last = {
                "at": run["at"],
                "outcome": run["outcome"],
                "message": run.get("message") or run.get("error"),
                "runtime_s": run.get("runtime_s"),
                "model": run.get("model"),
            }
        running = self.state == "running"
        return {
            "state": self.state,
            "enabled": settings.house_learn_enabled,
            "started_at": iso_z(self.started_at) if running and self.started_at else None,
            "next_due_at": next_due,
            "interval_h": settings.house_learn_interval_h,
            "last": last,
            "failure": self.failure.to_json(full=full_detail) if self.failure is not None else None,
        }

    async def _execute(self) -> None:
        try:
            outcome = await self._attempt()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("house model learner run crashed")
            outcome = self._failed("spawn", f"{type(exc).__name__}: {exc}")
        self.finished_at = self.now()
        if outcome == "busy":
            LOGGER.info("house model learner run skipped: another learner is running")
            return
        failure = outcome
        self.failure = failure
        self.facts.set(
            FACT_KEY,
            None
            if failure is None
            else {"at": iso_z(failure.at), "reason": failure.reason, "detail": failure.detail},
        )
        if failure is None:
            LOGGER.info("house model learner run finished")
        else:
            LOGGER.warning(
                "house model learner run failed (%s): %s", failure.reason, failure.detail
            )

    def _failed(self, reason: Reason, detail: str) -> Failure:
        return Failure(self.now(), reason, detail[-MAX_DETAIL:])

    def _argv(self, settings: Settings) -> list[str]:
        folder = house.learner_dir(settings)
        return [
            sys.executable,
            "-P",
            "-m",
            MODULE,
            "--low-priority",
            str(CPU_LIMIT_S),
            "--history",
            str(folder / house.HISTORY_EXPORT),
            "--config",
            str(folder / house.LEARNER_CONFIG),
            "--models",
            str(house.models_dir(settings)),
            "--building-only",
        ]

    def _env(self) -> dict[str, str]:
        env = {name: os.environ[name] for name in INHERITED_ENV if name in os.environ}
        return env | THREAD_LIMITS

    def _snapshot_age(self, settings: Settings) -> float | None:
        try:
            return max(0.0, self.now().timestamp() - settings.snapshot_path.stat().st_mtime)
        except OSError:
            return None

    async def _wait(self, task: asyncio.Future[Any], seconds: float) -> bool:
        """Wait up to ``seconds`` (on the injected sleep) for ``task``; whether it finished."""
        timer = asyncio.ensure_future(self.sleep(seconds))
        try:
            await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
        return task.done()

    async def _stop(self, child: Child, waiter: asyncio.Future[int]) -> None:
        child.terminate()
        if await self._wait(waiter, KILL_GRACE_S):
            return
        child.kill()
        await self._wait(waiter, KILL_GRACE_S)

    async def _attempt(self) -> Outcome:
        settings = self.settings()
        exported = await asyncio.to_thread(self.export, settings)
        if exported is None:
            return self._failed("spawn", "there is no history snapshot to learn from yet")
        self.snapshot_age_s = await asyncio.to_thread(self._snapshot_age, settings)
        LOGGER.info("starting the house model learner on a snapshot %s s old", self.snapshot_age_s)
        try:
            child = await self.spawn(self._argv(settings), self._env(), house.learner_dir(settings))
        except Exception as exc:
            return self._failed("spawn", f"{type(exc).__name__}: {exc}")
        tail = bytearray()
        drain = asyncio.ensure_future(self._drain(child.stdout, tail))
        waiter = asyncio.ensure_future(child.wait())
        try:
            problem = await self._watch(child, waiter)
            if problem is not None:
                await self._stop(child, waiter)
        except BaseException:
            child.kill()
            drain.cancel()
            raise
        if not await self._wait(drain, DRAIN_S):
            drain.cancel()
        output = _text(bytes(tail))
        if problem is not None:
            reason, message = problem
            return self._failed(reason, f"{message}\n{output}".strip())
        code = waiter.result()
        if code == 0:
            return None
        if code == BUSY_EXIT:
            return "busy"
        return self._failed("exit", f"exit code {code}\n{output}".strip())

    async def _watch(self, child: Child, waiter: asyncio.Future[int]) -> tuple[Reason, str] | None:
        """Wait for the exit; return why the child must be stopped, or ``None`` when it ended."""
        deadline = self.monotonic() + TIMEOUT_S
        while True:
            if await self._wait(waiter, WATCH_S):
                return None
            if self.monotonic() >= deadline:
                return "timeout", f"no result within {TIMEOUT_S / 60:.0f} minutes; stopped"
            pid = child.pid
            used = self.rss(pid) if pid is not None else None
            if used is not None and used > MEMORY_CAP_BYTES:
                return (
                    "memory",
                    f"resident memory {used / 2**20:.0f} MB above the "
                    f"{MEMORY_CAP_BYTES / 2**20:.0f} MB limit; stopped",
                )

    async def _drain(self, stream: asyncio.StreamReader | None, tail: bytearray) -> None:
        if stream is None:
            return
        while chunk := await stream.read(1024):
            tail += chunk
            if len(tail) > TAIL_BYTES:
                del tail[: len(tail) - TAIL_BYTES]
