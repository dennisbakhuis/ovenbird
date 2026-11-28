"""What the control path recovers after a restart.

- **Controller state** (integrator, filters, run timers, ramp, last setpoints, the
  wood-stove episode) is
  stored after every tick in ``control_state`` under ``controller``. Times in the
  state are monotonic seconds, which do not survive a restart, so they are stored as
  ages relative to the tick's wall time and re-anchored on load; the gap since the
  save counts as elapsed time. A state older than the staleness limit (or from the
  future, e.g. a simulated clock that restarted) is ignored and the controller starts
  fresh.
- **Adapter state** is rebuilt from the journal: the ``sent`` command events since
  UTC midnight give the daily write budget used, the ``command_hold`` events give
  the escalation count (holds since the last operator release) and the hold that was
  active at shutdown (a latched hold stays latched; a timed hold keeps its end), and
  the operator's ``queued`` pump-setting requests of the last 24 h keep their rate
  limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import fields
from datetime import UTC, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from ovenbird.control.adapter import (
    OPERATOR_PREFIX,
    OPERATOR_WINDOW_S,
    HoldRecord,
    RestoredAdapter,
)
from ovenbird.control.alarms import HOLD_JOURNAL_CODE, AlarmEventKind
from ovenbird.history.journal import alarms_since, command_events_of, count_sent, read_state
from ovenbird_core import Instant, PumpSetting
from ovenbird_core.control import OvenbirdState, RampPhase, StoveSource, StoveTrigger

LOGGER = logging.getLogger("ovenbird.control.persist")
STATE_KEY: Final = "controller"
STATE_SCHEMA: Final = 1
TIME_FIELDS: Final = frozenset(
    {
        "last_change_at",
        "outside_at",
        "last_tick_at",
        "run_started_at",
        "stopped_at",
        "crosscheck_since",
        "room_lost_at",
        "stove_since",
        "stove_low_at",
        "stove_trusted_since",
        "stove_high_at",
        "stove_step_low_at",
        "summer_mean_at",
        "summer_mean_from",
    }
)
OPTIONAL_FIELDS: Final = frozenset(
    {"summer_mean_c", "summer_mean_at", "summer_mean_from", "summer_active"}
)
ENUM_FIELDS: Final = {
    "ramp_phase": RampPhase,
    "stove_source": StoveSource,
    "stove_trigger": StoveTrigger,
}


def encode_state(state: OvenbirdState, now: Instant) -> str:
    """Return the stored JSON form of ``state`` at ``now``.

    Parameters
    ----------
    state
        Controller state after the tick.
    now
        Tick instant.

    Returns
    -------
    str
        ``{"schema", "wall", "state"}`` with times as ages in seconds; the summer
        switch's fields are left out while at their defaults (a missing field loads as
        its default), so a configuration without the switch stores what it did before.
    """
    values: dict[str, Any] = {}
    defaults = OvenbirdState()
    for item in fields(state):
        value = getattr(state, item.name)
        if item.name in OPTIONAL_FIELDS and value == getattr(defaults, item.name):
            continue
        if item.name in TIME_FIELDS and value is not None:
            value = now.monotonic - value
        elif isinstance(value, StrEnum):
            value = value.value
        values[item.name] = value
    body = {"schema": STATE_SCHEMA, "wall": now.wall.timestamp(), "state": values}
    return json.dumps(body, separators=(",", ":"))


def _number(value: Any) -> float:
    """Return ``value`` as a float, refusing booleans and non-numbers."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("not a number")
    return float(value)


def decode_state(text: str, now: Instant, max_age_s: float) -> tuple[OvenbirdState | None, str]:
    """Return the stored state re-anchored at ``now``, or ``None`` with the reason.

    Parameters
    ----------
    text
        What :func:`encode_state` produced.
    now
        Current instant.
    max_age_s
        Staleness limit.

    Returns
    -------
    tuple
        The state (``None`` when unusable) and a human explanation.
    """
    try:
        body = json.loads(text)
        if body.get("schema") != STATE_SCHEMA:
            return None, f"unknown state schema {body.get('schema')!r}"
        gap = now.wall.timestamp() - _number(body["wall"])
        if gap < 0:
            return None, "saved state is from the future (clock restarted)"
        if gap > max_age_s:
            return None, f"saved state is {gap:.0f} s old (limit {max_age_s:.0f} s)"
        stored = body["state"]
        defaults = OvenbirdState()
        values: dict[str, Any] = {}
        for item in fields(defaults):
            if item.name not in stored:
                continue
            value = stored[item.name]
            if value is None:
                values[item.name] = None
            elif item.name in TIME_FIELDS:
                values[item.name] = now.monotonic - _number(value) - gap
            elif item.name in ENUM_FIELDS:
                values[item.name] = ENUM_FIELDS[item.name](value)
            else:
                values[item.name] = _check(getattr(defaults, item.name), value)
        return OvenbirdState(**values), f"restored state saved {gap:.0f} s ago"
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return None, f"saved state unreadable ({type(exc).__name__})"


def _check(default: Any, value: Any) -> Any:
    """Return the stored ``value`` if its type fits ``default``, else raise ``TypeError``."""
    if isinstance(value, bool):
        return value
    if isinstance(default, float) or isinstance(value, float):
        return _number(value)
    if isinstance(value, int):
        return value
    raise TypeError("unexpected state value")


def load_state(path: Path, now: Instant, max_age_s: float) -> OvenbirdState | None:
    """Return the controller state stored in ``history.db``, if recent enough."""
    if not path.exists():
        return None
    try:
        row = read_state(path, STATE_KEY)
    except Exception:
        LOGGER.exception("cannot read the saved controller state")
        return None
    if row is None:
        return None
    state, why = decode_state(row.value, now, max_age_s)
    LOGGER.info("controller state: %s", why)
    return state


def _hold(detail: dict[str, Any]) -> HoldRecord:
    """Return the command hold record rebuilt from its stored detail."""
    until = detail.get("until")
    return HoldRecord(
        reason=str(detail.get("reason", "restored hold")),
        until=None if until is None else datetime.fromtimestamp(_number(until), UTC),
        latched=bool(detail.get("latched", False)),
        incident=int(detail.get("incident", 1)),
    )


def restore_adapter(path: Path, now: Instant) -> RestoredAdapter:
    """Rebuild the adapter's budget, escalation count and hold from the journal.

    Parameters
    ----------
    path
        ``history.db``.
    now
        Current instant; journal rows after it (a restarted simulated clock) are
        ignored.

    Returns
    -------
    RestoredAdapter
        Empty when there is no journal.
    """
    if not path.exists():
        return RestoredAdapter()
    stamp = now.wall.timestamp()
    day = now.wall.date()
    midnight = datetime.combine(day, time(), UTC).timestamp()
    try:
        sent = count_sent(path, midnight, stamp + 1.0)
        rows = alarms_since(path, HOLD_JOURNAL_CODE, 0.0)
        requests = command_events_of(
            path,
            [setting.value for setting in PumpSetting],
            stamp - OPERATOR_WINDOW_S,
            stamp + 1.0,
            status="queued",
        )
    except Exception:
        LOGGER.exception("cannot read the command journal; starting with an empty budget")
        return RestoredAdapter()
    incidents: list[float] = []
    hold: HoldRecord | None = None
    for row in rows:
        if row.ts > stamp:
            continue
        event = row.event
        if event == AlarmEventKind.STARTED:
            incidents.append(row.ts)
            try:
                hold = _hold(json.loads(row.detail))
            except ValueError, TypeError:
                hold = HoldRecord("restored hold", None, True, len(incidents))
        elif event == AlarmEventKind.EXPIRED:
            hold = None
        elif event == AlarmEventKind.RELEASED:
            hold = None
            incidents.clear()
    operator = tuple(
        (row.ts, PumpSetting(row.kind))
        for row in requests
        if row.detail.startswith(OPERATOR_PREFIX)
    )
    return RestoredAdapter(
        day=day,
        sent_today=sent,
        incidents=tuple(incidents),
        hold=hold,
        operator_requests=operator,
    )
