"""The scenario framework: what a fault scenario records and how it is judged.

Each scenario acts on the run at offsets from its start and records the decisions,
command events, alarm transitions and true room temperatures of its window; at the
end every expectation is ``pass`` or ``fail``. There is no ``pending``: an
expectation that cannot be evaluated (for example no held decision under an
``on_change`` profile) fails, and :class:`FullRun` treats any status other than
``pass`` as a failed run. Every scenario reports the counts of the paths it
exercised in its notes (retries, refusals, holds, ...), so a path that was never
taken shows as zero.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow
from ovenbird_core import HeishaSignal
from ovenbird_core.control import IntentKind

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun


HOUR: Final = 3600.0
TICK_S: Final = 60.0
SLACK_S: Final = 2 * TICK_S
WARMUP_S: Final = 86_400.0
TAIL_S: Final = 2 * HOUR
CONTROL: Final = frozenset(
    {"optimiser_plan", "model_plan", "rule_plan", "schedule_curve_feedback", "curve_only"}
)
TROUBLE: Final = frozenset({"foreign_writer", "verification_failed", "hold_latched"})
EPSILON: Final = 1e-6
COMFORT_FLOOR_K: Final = 1.5
BAND_K: Final = 0.5
CYCLE_S: Final = 5.0
TICK_CYCLES: Final = int(TICK_S // CYCLE_S)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Seen:
    """One decision as a scenario sees it.

    Parameters
    ----------
    ts
        Tick time.
    ladder, reason
        Ladder level and reason.
    setpoint
        Desired setpoint.
    room
        ``(value, age, fresh)`` of the room input, if any.
    held_s
        Seconds the room value has been unchanged (the age when not recorded).
    feedback
        Value of the ``room_feedback`` term, if any.
    state
        Controller state after the tick.
    curve
        Value of the ``curve`` term, if any.
    config_version
        Configuration version of the tick.
    note
        The decision note.
    duty
        The max-pump-duty intent, if any.
    dhw
        A DHW run was reported (fresh ``ThreeWay_Valve_State`` 1).
    terms
        Value of every decision term by name.
    """

    ts: float
    ladder: str
    reason: str
    setpoint: int | None
    room: tuple[float | None, float | None, bool] | None
    held_s: float | None
    feedback: float | None
    state: dict[str, Any]
    curve: float | None = None
    config_version: int | None = None
    note: str = ""
    duty: int | None = None
    dhw: bool = False
    terms: dict[str, float] = field(default_factory=dict)


def seen(row: DecisionRow) -> Seen:
    """Extract what the scenarios look at from a stored decision."""
    record = json.loads(row.record)
    room_ref = next((r for r in record["inputs_used"] if r.get("source") == "room"), None)
    room = None
    if room_ref is not None:
        room = (room_ref.get("value"), room_ref.get("age"), bool(room_ref.get("fresh")))
    feedback = next((t["value"] for t in record["terms"] if t["name"] == "room_feedback"), None)
    curve = next((t["value"] for t in record["terms"] if t["name"] == "curve"), None)
    state = record["controller_state"]
    held = state.get("room_held_s", room[1] if room is not None else None)
    duty = next(
        (i["value"] for i in record["intents"] if i["kind"] == IntentKind.MAX_PUMP_DUTY.value),
        None,
    )
    valve = next(
        (r for r in record["inputs_used"] if r["signal"] == HeishaSignal.THREEWAY_VALVE_STATE),
        None,
    )
    dhw = valve is not None and bool(valve.get("fresh")) and valve.get("value") == 1
    return Seen(
        row.ts,
        row.ladder,
        row.reason,
        row.setpoint,
        room,
        held,
        feedback,
        state,
        curve,
        row.config_version,
        record["note"],
        duty,
        dhw,
        {t["name"]: float(t["value"]) for t in record["terms"]},
    )


@dataclass
class Check:
    """One expectation of a scenario.

    Parameters
    ----------
    name
        What is expected.
    status
        ``pass`` or ``fail``.
    detail
        What was observed.
    """

    name: str
    status: str
    detail: str = ""

    def to_json(self) -> dict[str, str]:
        """Return the JSON form."""
        return {"check": self.name, "status": self.status, "detail": self.detail}


def verdict(name: str, ok: bool, detail: str = "") -> Check:
    """Return a passed or failed check."""
    return Check(name, "pass" if ok else "fail", detail)


@dataclass
class Scenario:
    """Base of the fault scenarios: a timeline of actions and a recorded window.

    Parameters
    ----------
    name
        Scenario name.
    window_s
        Time from the start to the end of the assessment.
    """

    name: str
    window_s: float
    start: float = math.nan
    begun: bool = False
    done: bool = False
    decisions: list[Seen] = field(default_factory=list)
    commands: list[CommandRow] = field(default_factory=list)
    alarms: list[AlarmRow] = field(default_factory=list)
    rooms: list[tuple[float, float]] = field(default_factory=list)
    outside: list[float] = field(default_factory=list)
    actions: list[tuple[float, Callable[[FullRun, float], None]]] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)
    run: FullRun | None = None

    @property
    def end(self) -> float:
        """End of the window."""
        return self.start + self.window_s

    def at(self, offset_s: float, action: Callable[[FullRun, float], None]) -> None:
        """Schedule ``action`` at ``offset_s`` after the start."""
        self.actions.append((offset_s, action))
        self.actions.sort(key=lambda item: item[0])

    def plan(self, run: FullRun) -> None:
        """Schedule the scenario's actions (subclasses)."""

    def attach(self, run: FullRun) -> None:
        """Start recording the window."""
        self.run = run
        run.on_decision.append(self._decision)
        run.on_command.append(self._command)
        run.on_alarm.append(self._alarm)
        run.on_cycle.append(lambda t: self._cycle(run, t))

    def _inside(self, ts: float) -> bool:
        return self.begun and not self.done and ts >= self.start - EPSILON

    def _decision(self, row: DecisionRow) -> None:
        if self._inside(row.ts):
            self.decisions.append(seen(row))

    def _command(self, row: CommandRow) -> None:
        if self._inside(row.ts):
            self.commands.append(row)

    def _alarm(self, row: AlarmRow) -> None:
        if self._inside(row.ts):
            self.alarms.append(row)

    def _cycle(self, run: FullRun, t: float) -> None:
        observation = run.board.observation
        if self._inside(t) and observation is not None:
            self.rooms.append((t, observation.room_temp))
            self.outside.append(observation.outside_temp)

    def before(self, run: FullRun, t: float) -> None:
        """Run the actions due at ``t``."""
        if self.done or t < self.start:
            return
        if not self.begun:
            self.begun = True
            self.plan(run)
        while self.actions and self.start + self.actions[0][0] <= t + EPSILON:
            _, action = self.actions.pop(0)
            action(run, t)
        if t >= self.end:
            self.done = True

    def raised(self, code: str, after: float = -math.inf) -> list[AlarmRow]:
        """Alarm rows raising ``code`` at or after ``after``."""
        return [a for a in self.alarms if a.code == code and a.event == "raised" and a.ts >= after]

    def trouble(self, after: float) -> list[str]:
        """Codes of foreign-writer, verification and latch alarms raised after ``after``."""
        return sorted(
            {a.code for a in self.alarms if a.event == "raised" and a.ts >= after} & TROUBLE
        )

    def between(self, a: float, b: float) -> list[Seen]:
        """Decisions with ``a < ts < b``."""
        return [d for d in self.decisions if a < d.ts < b]

    def checks(self, run: FullRun) -> list[Check]:
        """Evaluate the expectations (subclasses)."""
        return []

    def outcome(self, run: FullRun) -> dict[str, Any]:
        """Return the JSON outcome."""
        if not self.begun:
            checks = [Check("scenario ran", "fail", "the span ended before it started")]
        else:
            checks = self.checks(run)
        failed = any(c.status == "fail" for c in checks)
        return {
            "name": self.name,
            "at": _iso(self.start) if math.isfinite(self.start) else None,
            "outside_c": _spread(self.outside),
            "status": "fail" if failed else "pass",
            "checks": [c.to_json() for c in checks],
            "notes": self.notes,
        }


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": round(min(values), 2),
        "mean": round(sum(values) / len(values), 2),
        "max": round(max(values), 2),
    }


def _resumes(scenario: Scenario, after: float, within: float) -> Check:
    first = next((d for d in scenario.decisions if d.ts > after and d.ladder in CONTROL), None)
    late = None if first is None else first.ts - after
    return verdict(
        f"control resumes within {within / 60:.0f} min",
        late is not None and late <= within,
        "never" if late is None else f"after {late:.0f} s ({first.ladder if first else ''})",
    )


def _refuses_dead(scenario: Scenario, a: float, b: float) -> Check:
    during = scenario.between(a, b)
    bad = [d for d in during if not (d.ladder == "refuse" and d.reason == "heishamon_dead")]
    return verdict(
        "every decision while HeishaMon is silent refuses (heishamon_dead)",
        bool(during) and not bad,
        f"{len(during)} decisions, {len(bad)} not refusing"
        + (f" (first {bad[0].ladder}/{bad[0].reason} at {_iso(bad[0].ts)})" if bad else ""),
    )


def _no_trouble(scenario: Scenario, after: float) -> Check:
    found = scenario.trouble(after)
    holds = [a for a in scenario.alarms if a.code == "command_hold" and a.ts >= after]
    return verdict(
        "no foreign-writer, verification or latch alarm and no hold",
        not found and not holds,
        f"alarms {found}, holds {[a.message for a in holds]}",
    )


def _sent_between(scenario: Scenario, a: float, b: float) -> list[CommandRow]:
    return [
        c
        for c in scenario.commands
        if c.status == "sent" and a <= c.ts < b and not c.detail.startswith("safety")
    ]
