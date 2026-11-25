"""Preview of a candidate configuration: the effect now, and an open-loop run.

- **Now**: the controller stepped once with the candidate on the current inputs and a
  copy of the current state (carried over as an apply would), next to the active
  configuration stepped on the same inputs and state.
- **Open-loop run**: the recorded ticks of the window (``hours``, 1-72) replayed with the
  candidate from the recorded controller state at the window start. Inputs are
  rebuilt from each decision's ``inputs_used`` (:func:`~ovenbird_core.control.replay_inputs`).
  The replay is **open loop**: the candidate reacts to what the house actually did
  under the recorded control, so it makes no energy or comfort claim.
- **Identity check**: the same replay with the *active* configuration must reproduce
  the recorded setpoint of every tick made under the active version (``identity_ok``).
  It re-seeds from the recorded state where the version changes (carried over as the
  apply did) and follows restarts as the service does (state re-anchored on the new
  monotonic axis, or a fresh state when the saved one was too old).

The stepping itself is shared with the replay (:mod:`ovenbird.replay.stepping`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.config import Settings
from ovenbird.history.journal import decision_before, decisions_between
from ovenbird.replay.stepping import (
    CandidateStepper,
    ConfigOf,
    Identity,
    IdentityStepper,
    Tally,
    Tick,
    limitations,
    parse_rows,
)
from ovenbird_core import Instant, Snapshot
from ovenbird_core.control import (
    Mode,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    control_inputs,
)
from ovenbird_core.control.ovenbird import carry_state

MIN_HOURS: Final = 1
MAX_HOURS: Final = 72
DEFAULT_HOURS: Final = 24


def identity_check(
    ticks: Sequence[Tick],
    seed: Tick | None,
    active: Settings,
    version: int | None,
    config_of: ConfigOf,
) -> Identity:
    """Replay with the active configuration and compare the recorded setpoints.

    Parameters
    ----------
    ticks
        Recorded ticks, oldest first.
    seed
        The tick before the window (its state starts the replay).
    active
        Active settings.
    version
        Active configuration version; only its ticks are compared.
    config_of
        Controller configuration of a version (``None`` when unknown).

    Returns
    -------
    Identity
        The comparison.
    """
    stepper = IdentityStepper(seed, lambda v: active if v == version else None, config_of)
    for tick in ticks:
        stepper.feed(tick)
    return stepper.result()


def open_loop_run(
    ticks: Sequence[Tick],
    seed: Tick | None,
    candidate: Settings,
    config_of: ConfigOf,
    span: tuple[float, float],
) -> dict[str, Any]:
    """Replay the recorded ticks with the candidate (open loop) and summarise.

    Parameters
    ----------
    ticks
        Recorded ticks, oldest first.
    seed
        The tick before the window (its state starts the replay).
    candidate
        Candidate settings.
    config_of
        Controller configuration of a version (``None`` when unknown).
    span
        Window ``(from, to)`` in unix seconds.

    Returns
    -------
    dict
        ``series``, ``summary`` and the number of ticks that could not be replayed
        (``skipped``).
    """
    stepper = CandidateStepper(seed, candidate, config_of)
    tally = Tally()
    at: list[str] = []
    pre_round: list[float | None] = []
    for tick in ticks:
        decision = stepper.feed(tick)
        if decision is None:
            continue
        at.append(iso_from_unix(tick.ts))
        pre_round.append(None if decision.pre_round is None else round(decision.pre_round, 2))
        tally.add(tick.record, decision)
    return {
        "series": {
            "at": at,
            "recorded": tally.recorded,
            "candidate": tally.replayed,
            "candidate_pre_round": pre_round,
        },
        "summary": tally.summary(span, candidate.command_daily_budget),
        "skipped": stepper.skipped,
    }


def run_open_loop(
    history_path: Path,
    active: Settings,
    version: int | None,
    candidate: Settings,
    config_of: ConfigOf,
    span: tuple[float, float],
) -> dict[str, Any]:
    """Read the window from ``history.db`` and return the ``open_loop_run`` object of the preview.

    Parameters
    ----------
    history_path
        ``history.db``.
    active
        Active settings (identity check).
    version
        Active configuration version.
    candidate
        Candidate settings.
    config_of
        Controller configuration of a version (``None`` when unknown).
    span
        Window ``(from, to)`` in unix seconds.

    Returns
    -------
    dict
        ``from``, ``to``, ``ticks``, ``skipped``, ``identity_ok`` (with
        ``identity_ticks`` and ``identity_mismatches``), ``open_loop``, ``series``,
        ``summary`` and ``limitations``.
    """
    start, end = span
    rows = decisions_between(history_path, start, end)
    seed_row = decision_before(history_path, start)
    ticks, unreadable = parse_rows(rows)
    seeds, _ = parse_rows([seed_row] if seed_row is not None else [])
    seed = seeds[0] if seeds else None
    identity = identity_check(ticks, seed, active, version, config_of)
    result = open_loop_run(ticks, seed, candidate, config_of, span)
    return {
        "from": iso_from_unix(start),
        "to": iso_from_unix(end),
        "ticks": len(rows),
        "skipped": unreadable + result["skipped"],
        "identity_ok": identity.ok,
        "identity_ticks": identity.ticks,
        "identity_mismatches": identity.mismatches,
        "identity_first_mismatch": None
        if identity.first is None
        else iso_from_unix(identity.first),
        "open_loop": True,
        "series": result["series"],
        "summary": result["summary"],
        "limitations": limitations(candidate, active),
    }


def preview_now(
    snapshot: Snapshot,
    state: OvenbirdState,
    mode: Mode,
    room_signal: str | None,
    current_config: OvenbirdConfig,
    candidate: Settings,
) -> dict[str, Any]:
    """Step the active and the candidate configuration once on the current inputs.

    Parameters
    ----------
    snapshot
        Current state snapshot.
    state
        Current controller state (a copy is carried over to the candidate).
    mode
        Effective mode.
    room_signal
        Room signal the loop runs with.
    current_config
        The controller configuration the loop runs.
    candidate
        Candidate settings.

    Returns
    -------
    dict
        ``current`` and ``candidate`` decision records and ``delta_setpoint``.
    """
    config = candidate.controller_config()
    now_inputs = control_inputs(
        snapshot,
        room_signal=room_signal,
        mode=mode,
        room_profile=current_config.room,
    )
    cand_inputs = control_inputs(
        snapshot,
        room_signal=candidate.control_room_signal,
        mode=mode,
        room_profile=config.room,
    )
    active = OvenbirdController(current_config).step(state, now_inputs).decision
    carried = carry_state(state, current_config, config)
    proposed = OvenbirdController(config).step(carried, cand_inputs).decision
    delta = (
        None
        if active.setpoint is None or proposed.setpoint is None
        else proposed.setpoint - active.setpoint
    )
    return {
        "current": active.to_json_dict(),
        "candidate": proposed.to_json_dict(),
        "delta_setpoint": delta,
    }


def window(now: Instant, hours: float) -> tuple[float, float]:
    """Return the open-loop run window ending at ``now``."""
    end = now.wall.timestamp()
    return end - hours * 3600.0, end


def valid_hours(value: Any) -> float | None:
    """Return ``value`` as a number of hours within 1-72, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    hours = float(value)
    if not math.isfinite(hours) or not MIN_HOURS <= hours <= MAX_HOURS:
        return None
    return hours
