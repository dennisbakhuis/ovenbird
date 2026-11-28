"""Replay endpoints: what ovenbird would have sent over a recorded period.

``GET replay/coverage`` and ``GET replay/{id}`` are open to every role (as the decision
journal is); starting and cancelling a replay need ``operate`` (as the configuration
preview does), follow the request rules of :mod:`ovenbird.api.deps` and are refused
with an audit row otherwise. A replay runs as a job in a worker thread, one at a time.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Query, Request

from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, bound, read_json, require_role
from ovenbird.api.models.base import returns
from ovenbird.api.models.replay import ReplayCoverage, ReplayJob
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.payloads import Json
from ovenbird.replay.engine import ReplayRequest, coverage_payload, max_days
from ovenbird.replay.jobs import ReplayJobs
from ovenbird.runtime import Runtime
from ovenbird.trial.divergence import DEFAULT_THRESHOLD_K, STEPS

DAY_S: Final = 86_400.0
KINDS: Final = ("active", "version", "draft")
MAX_THRESHOLD_K: Final = 20.0

type Parse = Callable[[str, str], datetime]


@dataclass(frozen=True, slots=True)
class ReplayDeps:
    """What the replay handlers need.

    Parameters
    ----------
    runtime
        Service clock.
    settings
        Roles and request rules (the effective settings come from ``config``).
    config
        Configuration manager (active settings, stored versions, draft validation);
        ``None`` replays the installation's settings only.
    audit
        Records refused state-changing requests.
    parse
        Parses a ``from``/``to`` value.
    jobs
        The replay jobs.
    """

    runtime: Runtime
    settings: Settings
    config: ConfigManager | None
    audit: RefusalAudit
    parse: Parse
    jobs: ReplayJobs

    def current(self) -> Settings:
        """Return the effective settings."""
        return self.config.settings if self.config is not None else self.settings


def _retention(settings: Settings) -> float:
    """Return the journal retention in days (0 when the journal is kept without limit)."""
    days = settings.history_journal_days()
    return 0.0 if days is None else float(days)


def _window(deps: ReplayDeps, start: Any, end: Any, *, required: bool) -> tuple[float, float]:
    """Return the validated ``(start, end)`` of a replay period as Unix seconds.

    Parameters
    ----------
    deps
        Replay dependencies (clock and settings).
    start, end
        ISO 8601 times from the request, or ``None`` for the default bound.
    required
        Whether both bounds must be given.
    """
    limit = max_days(_retention(deps.current()))
    if required and (not isinstance(start, str) or not isinstance(end, str)):
        raise HTTPException(400, "from and to are required (ISO 8601)")
    until = deps.parse(end, "to") if end is not None else deps.runtime.clock().wall
    since = (
        deps.parse(start, "from").timestamp()
        if start is not None
        else until.timestamp() - limit * DAY_S
    )
    if since >= until.timestamp():
        raise HTTPException(400, "from must be before to")
    if until.timestamp() - since > limit * DAY_S + 1.0:
        raise HTTPException(400, f"the period must be at most {limit:g} days")
    return since, until.timestamp()


async def coverage(
    deps: ReplayDeps,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
) -> Json:
    """``GET replay/coverage``: where stored decisions exist, per day and version.

    The history database is read in a worker thread, never on the event loop.
    """
    since, until = _window(deps, start, end, required=False)
    current = deps.current()
    return await asyncio.to_thread(
        coverage_payload,
        current.history_path,
        start=since,
        end=until,
        timezone=current.control_timezone,
        interval_s=current.control_interval_s,
        decision_days=_retention(current),
    )


def _chosen(deps: ReplayDeps, body: dict[str, Any]) -> tuple[Settings, dict[str, Any]]:
    """Return the settings to replay with and a description of the choice.

    The choice is the active configuration, a stored version or a draft of changes.

    Parameters
    ----------
    deps
        Replay dependencies.
    body
        Request body (``config``, and ``version`` or ``changes``).
    """
    kind = body.get("config", "active")
    if kind not in KINDS:
        raise HTTPException(400, "config must be active, version or draft")
    active = deps.current()
    version = deps.config.version if deps.config is not None else None
    if kind == "active":
        return active, {"kind": "active", "version": version}
    if deps.config is None:
        raise HTTPException(409, "without a configuration store only the active one replays")
    if kind == "version":
        number = body.get("version")
        if type(number) is not int or number < 1:
            raise HTTPException(400, "version must be a positive integer")
        found = deps.config.settings_of(number)
        if found is None:
            raise HTTPException(404, f"version {number} is unknown or no longer valid")
        return found, {"kind": "version", "version": number}
    changes = body.get("changes")
    if not isinstance(changes, dict):
        raise HTTPException(400, "changes must be a JSON object of field: value")
    validation = deps.config.validate(changes)
    if not validation.valid or validation.settings is None:
        issues = validation.to_json().get("errors") or []
        first = issues[0].get("message") if issues and isinstance(issues[0], dict) else None
        raise HTTPException(400, f"the draft does not validate: {first or 'invalid'}")
    return validation.settings, {
        "kind": "draft",
        "version": version,
        "changes": dict(changes),
    }


def _threshold(body: dict[str, Any]) -> float:
    """Return the divergence threshold in K from the request body, defaulting when absent."""
    value = body.get("threshold_k", DEFAULT_THRESHOLD_K)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0.0 < value <= MAX_THRESHOLD_K
    ):
        raise HTTPException(400, f"threshold_k must be above 0 and at most {MAX_THRESHOLD_K:g}")
    return float(value)


def _step(body: dict[str, Any]) -> int | None:
    """Return the series step in seconds from the request body, or ``None`` for the default."""
    value = body.get("step")
    if value is None:
        return None
    if type(value) is not int or value not in STEPS:
        raise HTTPException(400, f"step must be one of {', '.join(map(str, STEPS))}")
    return value


async def start_replay(deps: ReplayDeps, request: Request) -> Json:
    """``POST replay``: start a replay of a period with the chosen configuration."""
    require_role(request, deps.settings, Role.OPERATE, deps.audit)
    body = await read_json(request)
    since, until = _window(deps, body.get("from"), body.get("to"), required=True)
    candidate, described = _chosen(deps, body)
    active = deps.current()
    config = deps.config
    job = deps.jobs.start(
        ReplayRequest(
            start=since,
            end=until,
            candidate=candidate,
            reference=active,
            settings_of=config.settings_of if config is not None else lambda _: active,
            config_of=config.config_of
            if config is not None
            else lambda _: active.controller_config(),
            config=described,
            timezone=active.control_timezone,
            interval_s=active.control_interval_s,
            threshold_k=_threshold(body),
            step=_step(body),
        )
    )
    return job.to_json()


async def replay_job(deps: ReplayDeps, job_id: str) -> Json:
    """``GET replay/{id}``: a replay's phase and progress, and its result when done."""
    job = deps.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired replay")
    return job.to_json()


async def cancel_replay(deps: ReplayDeps, job_id: str, request: Request) -> Json:
    """``POST replay/{id}/cancel``: stop a running replay."""
    require_role(request, deps.settings, Role.OPERATE, deps.audit)
    await read_json(request)
    job = deps.jobs.cancel(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired replay")
    return job.to_json()


def build_replay_router(deps: ReplayDeps) -> APIRouter:
    """Return the replay routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/replay/coverage", **returns(ReplayCoverage))(bound(coverage, deps))
    router.post("/replay", status_code=202, **returns(ReplayJob))(bound(start_replay, deps))
    router.get("/replay/{job_id}", **returns(ReplayJob))(bound(replay_job, deps))
    router.post("/replay/{job_id}/cancel", **returns(ReplayJob))(bound(cancel_replay, deps))
    return router
