"""Invariants over every decision, command event and publish of a run.

The rules are derived from the code, not from the design text:

Decisions (``ovenbird_core.control.ovenbird``)
    - every record parses with the stable schema, has a reason, a note and the
      summary columns agree with the record;
    - setpoints and intent values are JSON integers;
    - ``refuse`` has no intents and no setpoint; ``hold`` repeats the state's
      setpoint, clamped to ``SafetyLimits.bounds(raw Outside_Temp)`` when that is fresh
      (a changed held setpoint names the safety bound as its binding); every other
      ladder level issues a setpoint and a ``pre_round``;
    - safety: a controlled setpoint lies in the integer bounds of
      ``SafetyLimits.bounds(raw Outside_Temp)`` (recomputed here and compared with the
      recorded bounds); any setpoint lies in the adapter's clamp range;
    - binding: a setpoint that differs from ``round_half_up(pre_round)`` names the
      binding constraint, and bindings come from the closed set the controller uses;
    - deadband and dwell: a change of the issued setpoint that is not forced by the
      cycling floor or a safety bound moves at least ``change_threshold_k`` from the
      previous setpoint and comes at least the applied dwell after the previous change;
      the applied dwell is ``dwell_s``, or ``ramp_dwell_s`` only while a start ramp
      runs, or 0 only on a ramp's first tick;
    - defrost and DHW: no setpoint decrease (unless a safety upper bound forces it),
      the integrator and the start-ramp cap unchanged; no pump-duty decrease in DHW;
    - defrost: no pump-duty intent at all (the pump drives its own duty);
    - wood-stove mode: while an episode runs the integrator stays at the value it had
      when the episode started (``stove_integral_k``) and the room feedback term is 0;
    - pump duty: below the heat duty never while the compressor runs or a DHW run
      is active;
    - bypass bindings are real: ``cycling_floor`` only while the compressor runs
      inside the minimum-run window (not in defrost or DHW) with the setpoint at
      the floor (its integer, the decrease headroom, the previous setpoint, or the
      rounded continuous value the floor lifted); a safety bound only with the
      setpoint at that bound;
    - an independent envelope: the setpoint lies in the bounds recomputed here from
      the envelope's points and band (piecewise-linear interpolation written out,
      not ``SafetyLimits.bounds``);
    - the integrator stays within its clamp;
    - configuration apply: the configuration is swapped between ticks; the first
      decision under a new version changes the issued setpoint only through deadband
      and dwell of the new configuration or a hard constraint (cycling floor, safety
      bound), and keeps the change time of an unchanged setpoint (the dwell timer).

Commands (``ovenbird.control.adapter``)
    - every event has a detail; values are integers inside the clamp range; topic and
      payload match the configured command;
    - every queued or sent value that is not a safety correction equals the intent
      of its kind in the decision it came from (queued) or the latest decision
      (sent);
    - no maximum pump duty is queued or sent while the plant defrosts;
    - one command in flight at a time; every ``sent`` command is concluded by
      ``verified``, ``retry``, ``failed`` (with ``verification_failed`` raised unless it
      was a safety correction) or ``dropped`` (pre-empted), or is still within its
      verification timeout when the run ends;
    - per UTC day at most ``daily_budget`` regular sends plus ``safety_reserve``;
    - the operator's pump settings (the second allowlist): only the three settings, on
      their own topics, with an integer payload inside their clamp, every event
      naming the operator (``detail`` starts with ``operator:``), never sent while
      the plant defrosts or a DHW run is reported, and never queued by a decision.

Publishes (``ovenbird.control.adapter.CommandLink`` through the harness client)
    - only while the publish guard permits, to an allowlisted topic, QoS 1, never
      retained, to a board reporting simulated firmware, at least ``min_spacing_s``
      apart, each followed by a ``sent`` event; a pump-setting topic only with a
      decimal integer inside that setting's clamp.

Plant (every 5 s cycle, from the simulated board, :meth:`InvariantChecker.plant`)
    - the setpoint register is outside the adapter's clamp range for at most
      :data:`REGISTER_GRACE_S` (a foreign write must be corrected by then);
    - the outlet stays at or below the maximum supply plus :data:`OUTLET_MARGIN_K`;
    - after a compressor start (not a defrost restart) the board's maximum pump
      duty reaches the heat duty within :data:`DUTY_LAG_S`, unless commands are
      blocked meanwhile (service, broker or board down, commands lost, an adapter
      hold, a refused publish guard, or a refusing or holding controller); a
      defrost inside that window suspends the rule (no duty command is sent during
      a defrost) and the end of the defrost, with the compressor still running,
      starts the window again.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Final

from ovenbird.control.adapter import (
    OPERATOR_PREFIX,
    SIM_VERSION_SUFFIX,
    AdapterConfig,
    CommandKind,
    CommandStatus,
)
from ovenbird.control.alarms import AlarmCode
from ovenbird.control.guard import PublishGuard
from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow
from ovenbird_core import PUMP_SETTINGS, HeishaSignal, PumpSetting
from ovenbird_core.control import IntentKind, LadderLevel, OvenbirdConfig, ReasonCode
from ovenbird_core.control.record import DecisionRecord
from ovenbird_core.control.safety import Bound

EPSILON: Final = 1e-6
CONTROL_LEVELS: Final = frozenset(
    {
        LadderLevel.OPTIMISER_PLAN,
        LadderLevel.MODEL_PLAN,
        LadderLevel.RULE_PLAN,
        LadderLevel.SCHEDULE_CURVE_FEEDBACK,
        LadderLevel.CURVE_ONLY,
    }
)
HOLD_REASONS: Final = frozenset({ReasonCode.INPUTS_MISSING, ReasonCode.OVERRIDE_MISSING})
REFUSE_REASONS: Final = frozenset(
    {
        ReasonCode.MODE_OFF,
        ReasonCode.HEISHAMON_DEAD,
        ReasonCode.MODE_UNKNOWN,
        ReasonCode.MODE_MISMATCH,
    }
)
SAFETY_BINDINGS: Final = frozenset(bound.value for bound in Bound)
HARD_HIGH: Final = frozenset({Bound.MAX_SUPPLY.value, Bound.ENVELOPE_MAX.value})
BYPASS_BINDINGS: Final = SAFETY_BINDINGS | {"cycling_floor"}
KNOWN_BINDINGS: Final = SAFETY_BINDINGS | {
    "cycling_floor",
    "defrost_hold",
    "dhw_hold",
    "dwell",
    "deadband",
    "rounding",
    "override",
    "start_ramp",
    "room_feedback_limit",
    "room_authority",
    "plan_limit",
}
CONCLUSIONS: Final = frozenset(
    {CommandStatus.VERIFIED, CommandStatus.RETRY, CommandStatus.FAILED, CommandStatus.DROPPED}
)
END_GRACE_S: Final = 60.0
REGISTER_GRACE_S: Final = 120.0
OUTLET_MARGIN_K: Final = 5.0
DUTY_LAG_S: Final = 90.0
SAFETY_PREFIX: Final = "safety correction"
DUTY_IN_DEFROST: Final = "max_pump_duty_commands_in_defrost"
SETTING_WRITES: Final = "pump_setting_commands_sent"


@dataclass(frozen=True, slots=True)
class PlantReading:
    """What the simulated plant and board show at the end of one cycle.

    Parameters
    ----------
    ts
        Cycle time.
    setpoint_register
        The pump register the adapter writes the water setpoint to.
    max_pump_duty
        The maximum pump duty register.
    outlet_c
        Outlet temperature as reported.
    running, defrosting
        Compressor running (incl. a defrost) and defrost in progress.
    commands_blocked
        Whether ovenbird could not have commanded anything (service, broker or
        board down, commands lost, an adapter hold, a refused guard, a refusing or
        holding controller).
    """

    ts: float
    setpoint_register: int
    max_pump_duty: int
    outlet_c: float | None
    running: bool
    defrosting: bool
    commands_blocked: bool
    dhw: bool = False


def envelope_bounds(
    points: list[tuple[float, float]],
    below_k: float,
    above_k: float,
    min_setpoint_c: float,
    max_supply_c: float,
    outside_c: float,
) -> tuple[int, int]:
    """Integer setpoint bounds at ``outside_c``, recomputed from the envelope's definition.

    The envelope curve is interpolated linearly between its points and flat beyond
    them; the band around it is cut by the hard limits (the maximum supply never
    below the minimum setpoint).

    Returns
    -------
    tuple of int
        ``(low, high)`` integer bounds.
    """
    ordered = sorted(points)
    if outside_c <= ordered[0][0]:
        reference = ordered[0][1]
    elif outside_c >= ordered[-1][0]:
        reference = ordered[-1][1]
    else:
        reference = ordered[-1][1]
        for (x0, y0), (x1, y1) in pairwise(ordered):
            if x0 <= outside_c <= x1:
                reference = y0 + (y1 - y0) * (outside_c - x0) / (x1 - x0)
                break
    high = max(min(max_supply_c, reference + above_k), min_setpoint_c)
    low = min(max(min_setpoint_c, reference - below_k), high)
    return math.ceil(low - 1e-9), math.floor(high + 1e-9)


@dataclass(frozen=True, slots=True)
class Violation:
    """One broken invariant.

    Parameters
    ----------
    rule
        Short rule name.
    at
        ISO 8601 UTC time of the offending decision, event or publish.
    detail
        What was observed.
    """

    rule: str
    at: str
    detail: str

    def to_json(self) -> dict[str, str]:
        """Return the JSON form."""
        return {"rule": self.rule, "at": self.at, "detail": self.detail}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def round_half_up(value: float) -> int:
    """Round halves upwards, as the controller does."""
    return math.floor(value + 0.5)


def _ref(record: DecisionRecord, signal: str) -> tuple[Any, bool]:
    for ref in record.inputs_used:
        if ref.signal == signal:
            return ref.value, ref.fresh
    return None, False


def _flag(record: DecisionRecord, signal: str) -> bool:
    value, fresh = _ref(record, signal)
    return fresh and isinstance(value, int | float) and not isinstance(value, bool) and value == 1


def _intent(record: DecisionRecord, kind: IntentKind) -> int | None:
    return next((intent.value for intent in record.intents if intent.kind is kind), None)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


@dataclass
class _InFlight:
    kind: str
    value: int
    sent_at: float
    corrective: bool


@dataclass
class InvariantChecker:
    """Check every decision, command event and publish of a run as it happens.

    Parameters
    ----------
    config
        Controller configuration of the run.
    adapter
        Adapter limits of the run.
    defrosting
        Whether the plant defrosts right now (for the command rules); ``None``
        skips those rules.
    dhw
        Whether the board reports a DHW run right now; ``None`` skips that rule.
    max_violations
        Violations kept in full (all are counted).
    """

    config: OvenbirdConfig
    adapter: AdapterConfig
    defrosting: Callable[[], bool] | None = None
    dhw: Callable[[], bool] | None = None
    max_violations: int = 200
    violations: list[Violation] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    observations: Counter[str] = field(default_factory=Counter)
    decisions: int = 0
    command_events: int = 0
    publishes: int = 0
    _prev: dict[str, Any] | None = None
    _prev_duty: int | None = None
    _in_flight: _InFlight | None = None
    _queued: dict[str, tuple[int, bool]] = field(default_factory=dict)
    _sent_per_day: Counter[str] = field(default_factory=Counter)
    _corrective_per_day: Counter[str] = field(default_factory=Counter)
    _last_publish: float | None = None
    _awaiting_sent: list[tuple[str, int, float]] = field(default_factory=list)
    _awaiting_alarm: list[float] = field(default_factory=list)
    _active_alarms: set[str] = field(default_factory=set)
    _applied: int | None = None
    applies: int = 0
    _intents: dict[str, int] = field(default_factory=dict)
    _queued_unchecked: list[tuple[float, str, int]] = field(default_factory=list)
    _register_out_since: float | None = None
    _outlet_high: bool = False
    _plant_running: bool | None = None
    _plant_defrosting: bool = False
    _duty_due: float | None = None
    _duty_blocked: bool = False
    _just_applied: bool = False

    def __post_init__(self) -> None:
        """Start the always-reported counters at zero."""
        self.observations[DUTY_IN_DEFROST] += 0
        self.observations[SETTING_WRITES] += 0

    def reconfigure(
        self, version: int | None, config: OvenbirdConfig, adapter: AdapterConfig
    ) -> None:
        """Follow a configuration applied between ticks (checked on the next decision)."""
        self.config = config
        self.adapter = adapter
        self._applied = version
        self.applies += 1

    def _fail(self, rule: str, ts: float, detail: str) -> None:
        self.counts[rule] += 1
        if len(self.violations) < self.max_violations:
            self.violations.append(Violation(rule, _iso(ts), detail))

    @property
    def total(self) -> int:
        """Number of violations found."""
        return sum(self.counts.values())

    def restart(self, restored: dict[str, Any] | None) -> None:
        """Start a new service instance: continue from its restored controller state."""
        self._prev = restored
        self._prev_duty = None if restored is None else restored.get("pump_duty")
        self._in_flight = None
        self._queued.clear()
        self._awaiting_sent.clear()
        self._active_alarms.clear()
        self._intents.clear()
        self._queued_unchecked.clear()

    def decision(self, row: DecisionRow) -> None:
        """Check one stored decision."""
        self.decisions += 1
        ts = row.ts
        raw = json.loads(row.record)
        self._check_integers(row, raw)
        try:
            record = DecisionRecord.from_json_dict(raw)
        except (ValueError, TypeError, KeyError) as exc:
            self._fail("record_schema", ts, f"record does not parse: {exc}")
            return
        self._check_columns(row, record, raw)
        state = dict(record.controller_state)
        self._check_ladder(row, record, state)
        self._check_limits(row, record, state)
        self._check_binding(row, record)
        self._check_changes(row, record, state)
        self._check_apply(row, record, state)
        self._check_duty(row, record)
        self._check_frozen(row, record, state)
        self._check_stove(row, record, state)
        self._check_bypass(row, record, state)
        self._check_envelope(row, record)
        self._check_queued_against(row, record)
        limit = self.config.feedback.integral_limit_k
        integral = _number(state.get("integral_k"))
        if integral is None or abs(integral) > limit + EPSILON:
            self._fail("integrator_clamp", ts, f"integral_k {integral} outside ±{limit}")
        for item in json.loads(row.arbiter):
            if not item.get("reason"):
                self._fail("arbiter_reason", ts, f"arbiter decision without a reason: {item}")
        self._prev = state
        duty = _intent(record, IntentKind.MAX_PUMP_DUTY)
        if duty is not None:
            self._prev_duty = duty
        self._intents = {intent.kind.value: intent.value for intent in record.intents}
        self._just_applied = False
        self._observe(record)

    def _observe(self, record: DecisionRecord) -> None:
        counts = self.observations
        counts[f"ladder_{record.ladder.value}"] += 1
        if record.ladder in (LadderLevel.REFUSE, LadderLevel.HOLD):
            counts[f"{record.ladder.value}_{record.reason.value}"] += 1
        if _flag(record, HeishaSignal.DEFROSTING_STATE):
            counts["decisions_in_defrost"] += 1
        if _flag(record, HeishaSignal.THREEWAY_VALVE_STATE):
            counts["decisions_in_dhw"] += 1
        if record.binding is not None:
            counts[f"binding_{record.binding}"] += 1

    def _check_queued_against(self, row: DecisionRow, record: DecisionRecord) -> None:
        pending = self._queued_unchecked
        self._queued_unchecked = []
        intents = {intent.kind.value: intent.value for intent in record.intents}
        for ts, kind, value in pending:
            if intents.get(kind) != value:
                self._fail(
                    "intent_match",
                    ts,
                    f"{kind}={value} queued but the decision at {_iso(row.ts)} wants "
                    f"{intents.get(kind)}",
                )

    def _check_frozen(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]
    ) -> None:
        prev = self._prev
        if prev is None or record.ladder not in CONTROL_LEVELS:
            return
        defrost = _flag(record, HeishaSignal.DEFROSTING_STATE)
        dhw = _flag(record, HeishaSignal.THREEWAY_VALVE_STATE)
        if not (defrost or dhw) or self._just_applied:
            return
        what = "defrost" if defrost else "DHW"
        before, after = _number(prev.get("integral_k")), _number(state.get("integral_k"))
        if before is not None and after is not None and abs(after - before) > EPSILON:
            self._fail("freeze", row.ts, f"integrator {before:.4f} → {after:.4f} during {what}")
        cap_before, cap_after = _number(prev.get("ramp_cap_c")), _number(state.get("ramp_cap_c"))
        if (
            cap_before is not None
            and cap_after is not None
            and abs(cap_after - cap_before) > EPSILON
        ):
            self._fail(
                "freeze", row.ts, f"ramp cap {cap_before:.2f} → {cap_after:.2f} during {what}"
            )

    def _check_stove(self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]) -> None:
        if state.get("stove_state") != "active" or record.ladder not in CONTROL_LEVELS:
            return
        held = _number(state.get("stove_integral_k"))
        integral = _number(state.get("integral_k"))
        if held is None or integral is None or abs(integral - held) > EPSILON:
            self._fail("stove_freeze", row.ts, f"integrator {integral} not held at {held}")
        feedback = next((t.value for t in record.terms if t.name == "room_feedback"), None)
        if feedback is not None and abs(feedback) > EPSILON:
            self._fail("stove_freeze", row.ts, f"room feedback {feedback:+.3f} K in stove mode")

    def _check_bypass(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]
    ) -> None:
        binding = record.binding
        setpoint = record.setpoint
        if binding is None or setpoint is None or record.ladder not in CONTROL_LEVELS:
            return
        if binding == "cycling_floor":
            self._check_floor(row, record, state, setpoint)
        elif binding in SAFETY_BINDINGS:
            outside = _number(_ref(record, HeishaSignal.OUTSIDE_TEMP)[0])
            if outside is None:
                return
            bounds = self.config.safety.bounds(outside)
            at = bounds.high_int if binding in HARD_HIGH else bounds.low_int
            self.observations["safety_bindings_checked"] += 1
            if setpoint != at:
                self._fail(
                    "binding",
                    row.ts,
                    f"binding {binding} but setpoint {setpoint} is not at the bound {at}",
                )

    def _check_floor(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any], setpoint: int
    ) -> None:
        cycling = self.config.cycling
        frequency, fresh = _ref(record, HeishaSignal.COMPRESSOR_FREQ)
        hz = _number(frequency)
        running = fresh and hz is not None and hz >= self.config.compressor_min_hz
        started = _number(state.get("run_started_at"))
        inside = started is not None and record.at.monotonic - started < cycling.min_run_s
        frozen = _flag(record, HeishaSignal.DEFROSTING_STATE) or _flag(
            record, HeishaSignal.THREEWAY_VALVE_STATE
        )
        term = record.term("cycling_floor")
        safety = record.term("safety")
        self.observations["cycling_floor_bindings_checked"] += 1
        if not (cycling.enabled and running and inside and not frozen):
            self._fail(
                "binding",
                row.ts,
                f"cycling_floor outside the minimum-run window (running {running}, "
                f"started {started}, defrost/DHW {frozen})",
            )
            return
        if term is None or safety is None or record.pre_round is None:
            self._fail("binding", row.ts, "cycling_floor without its term")
            return
        floor = term.raw + safety.raw - term.value
        previous = None if self._prev is None else self._prev.get("setpoint")
        allowed = {
            math.ceil(floor - 1e-9),
            math.ceil(floor + cycling.decrease_headroom_k - 1e-9),
            round_half_up(record.pre_round),
        }
        if previous is not None:
            allowed.add(int(previous))
        if setpoint not in allowed:
            self._fail(
                "binding",
                row.ts,
                f"cycling_floor binding with setpoint {setpoint} not at the floor "
                f"{floor:.2f} °C (allowed {sorted(allowed)})",
            )

    def _check_envelope(self, row: DecisionRow, record: DecisionRecord) -> None:
        if record.ladder not in CONTROL_LEVELS or record.setpoint is None:
            return
        outside = _number(_ref(record, HeishaSignal.OUTSIDE_TEMP)[0])
        if outside is None:
            return
        safety = self.config.safety
        low, high = envelope_bounds(
            [(point.outside_c, point.water_c) for point in safety.envelope.points],
            safety.envelope_below_k,
            safety.envelope_above_k,
            safety.min_setpoint_c,
            safety.max_supply_c,
            outside,
        )
        if not low <= record.setpoint <= high:
            self._fail(
                "envelope_independent",
                row.ts,
                f"setpoint {record.setpoint} outside the recomputed [{low}, {high}] at "
                f"{outside:g} °C outside",
            )

    def plant(self, reading: PlantReading) -> None:
        """Check the plant and the board at the end of one cycle."""
        ts = reading.ts
        low, high = self.adapter.setpoint_range
        if low <= reading.setpoint_register <= high:
            self._register_out_since = None
        elif self._register_out_since is None:
            self._register_out_since = ts
        elif ts - self._register_out_since > REGISTER_GRACE_S:
            self._fail(
                "plant_register",
                self._register_out_since,
                f"setpoint register {reading.setpoint_register} outside [{low}, {high}] for "
                f"more than {REGISTER_GRACE_S:.0f} s",
            )
            self._register_out_since = math.inf
        limit = self.config.safety.max_supply_c + OUTLET_MARGIN_K
        high_outlet = reading.outlet_c is not None and reading.outlet_c > limit
        if high_outlet and not self._outlet_high:
            self._fail("plant_outlet", ts, f"outlet {reading.outlet_c} °C above {limit:g} °C")
        self._outlet_high = high_outlet
        self._check_plant_duty(reading)

    def _check_plant_duty(self, reading: PlantReading) -> None:
        pump = self.config.pump_duty
        started = reading.running and self._plant_running is False and not reading.defrosting
        thawed = reading.running and self._plant_defrosting and not reading.defrosting
        self._plant_running = reading.running
        self._plant_defrosting = reading.defrosting
        if pump is None:
            return
        if reading.defrosting and self._duty_due is not None:
            self._duty_due = None
            self.observations["plant_starts_into_defrost"] += 1
        if started or (thawed and self._duty_due is None):
            self._duty_due = reading.ts + DUTY_LAG_S
            self._duty_blocked = reading.commands_blocked
            self.observations[
                "plant_starts_checked" if started else "plant_defrost_ends_checked"
            ] += 1
        due = self._duty_due
        if due is None:
            return
        self._duty_blocked = self._duty_blocked or reading.commands_blocked
        if not reading.running or reading.max_pump_duty >= pump.heat:
            self._duty_due = None
            return
        if reading.ts >= due:
            self._duty_due = None
            if self._duty_blocked:
                self.observations["plant_starts_excused"] += 1
                return
            self._fail(
                "plant_duty",
                reading.ts,
                f"Max_Pump_Duty {reading.max_pump_duty} below {pump.heat} {DUTY_LAG_S:.0f} s "
                "after a compressor start",
            )

    def _check_columns(self, row: DecisionRow, record: DecisionRecord, raw: dict[str, Any]) -> None:
        ts = row.ts
        if not record.note.strip():
            self._fail("reason", ts, "decision without a note")
        if row.reason != record.reason.value or row.ladder != record.ladder.value:
            self._fail("reason", ts, "summary columns disagree with the record")
        if row.setpoint != record.setpoint:
            self._fail("reason", ts, f"column setpoint {row.setpoint} != {record.setpoint}")
        if abs(record.at.wall.timestamp() - ts) > EPSILON:
            self._fail("reason", ts, "record time differs from the row time")
        if raw.get("mode") != "auto":
            self._fail("mode", ts, f"mode {raw.get('mode')!r} in an auto run")

    def _check_integers(self, row: DecisionRow, raw: dict[str, Any]) -> None:
        setpoint = raw.get("setpoint")
        if setpoint is not None and (type(setpoint) is not int):
            self._fail("integers", row.ts, f"setpoint {setpoint!r} is not an integer")
        for intent in raw.get("intents", []):
            if type(intent.get("value")) is not int:
                self._fail("integers", row.ts, f"intent {intent} is not an integer")

    def _check_ladder(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]
    ) -> None:
        ts = row.ts
        if record.ladder is LadderLevel.REFUSE:
            if record.intents or record.setpoint is not None:
                self._fail("ladder", ts, "refusal with intents or a setpoint")
            if record.reason not in REFUSE_REASONS:
                self._fail("reason", ts, f"refusal with reason {record.reason.value}")
        elif record.ladder is LadderLevel.HOLD:
            if record.reason not in HOLD_REASONS:
                self._fail("reason", ts, f"hold with reason {record.reason.value}")
            held = _intent(record, IntentKind.WATER_SETPOINT)
            if held != state.get("setpoint"):
                self._fail("ladder", ts, f"hold sends {held}, state holds {state.get('setpoint')}")
            self._check_held(ts, record)
        elif record.setpoint is None or record.pre_round is None:
            self._fail("ladder", ts, f"{record.ladder.value} without a setpoint or pre_round")
        elif _intent(record, IntentKind.WATER_SETPOINT) != record.setpoint:
            self._fail("ladder", ts, "water setpoint intent differs from the setpoint")

    def _check_held(self, ts: float, record: DecisionRecord) -> None:
        """Check that a hold with a fresh ``Outside_Temp`` keeps its setpoint inside the bounds."""
        value, fresh = _ref(record, HeishaSignal.OUTSIDE_TEMP)
        outside = _number(value)
        setpoint = record.setpoint
        if setpoint is None or outside is None or not fresh:
            return
        bounds = self.config.safety.bounds(outside)
        if not bounds.low_int <= setpoint <= bounds.high_int:
            self._fail(
                "envelope",
                ts,
                f"held setpoint {setpoint} outside [{bounds.low_int}, {bounds.high_int}] "
                f"at {outside:g} °C outside",
            )
        previous = None if self._prev is None else _number(self._prev.get("setpoint"))
        if previous is None or setpoint == previous:
            return
        expected = bounds.clamp_int(int(previous))
        if setpoint != expected or record.binding not in SAFETY_BINDINGS:
            self._fail(
                "ladder",
                ts,
                f"hold changes {previous:g} → {setpoint} (binding {record.binding}); only a "
                f"safety clamp to {expected} may",
            )

    def _check_limits(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]
    ) -> None:
        ts = row.ts
        low, high = self.adapter.setpoint_range
        for value in (record.setpoint, _intent(record, IntentKind.WATER_SETPOINT)):
            if value is not None and not low <= value <= high:
                self._fail("safety_limits", ts, f"setpoint {value} outside [{low}, {high}]")
        if record.ladder not in CONTROL_LEVELS or record.setpoint is None:
            return
        outside = _number(_ref(record, HeishaSignal.OUTSIDE_TEMP)[0])
        if outside is None:
            self._fail("safety_limits", ts, "controlled decision without Outside_Temp")
            return
        bounds = self.config.safety.bounds(outside)
        if not bounds.low_int <= record.setpoint <= bounds.high_int:
            self._fail(
                "envelope",
                ts,
                f"setpoint {record.setpoint} outside [{bounds.low_int}, {bounds.high_int}] "
                f"at {outside:g} °C outside",
            )
        recorded = (_number(state.get("safety_low_c")), _number(state.get("safety_high_c")))
        if recorded[0] is None or recorded[1] is None:
            self._fail("envelope", ts, "controlled decision without recorded safety bounds")
        elif abs(recorded[0] - bounds.low) > EPSILON or abs(recorded[1] - bounds.high) > EPSILON:
            self._fail("envelope", ts, f"recorded bounds {recorded} != recomputed {bounds}")

    def _check_binding(self, row: DecisionRow, record: DecisionRecord) -> None:
        binding = record.binding
        if binding is not None and binding not in KNOWN_BINDINGS:
            self._fail("binding", row.ts, f"unknown binding {binding!r}")
        if record.ladder not in CONTROL_LEVELS or record.pre_round is None:
            return
        if record.setpoint != round_half_up(record.pre_round) and binding is None:
            self._fail(
                "binding",
                row.ts,
                f"setpoint {record.setpoint} != round({record.pre_round:.3f}) without a binding",
            )

    def _ramp_evident(self, prev: dict[str, Any], state: dict[str, Any]) -> bool:
        if not self.config.ramp.enabled:
            return False
        started = state.get("run_started_at")
        tick = state.get("last_tick_at")
        just_started = started is not None and tick is not None and abs(started - tick) < EPSILON
        phases = (prev.get("ramp_phase"), state.get("ramp_phase"))
        return just_started or any(phase not in (None, "idle") for phase in phases)

    def _check_changes(
        self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]
    ) -> None:
        prev = self._prev
        ts = row.ts
        if prev is None or record.ladder not in CONTROL_LEVELS or record.setpoint is None:
            return
        reference = prev.get("setpoint")
        if reference is None or record.setpoint == reference or record.pre_round is None:
            return
        defrost = _flag(record, HeishaSignal.DEFROSTING_STATE)
        dhw = _flag(record, HeishaSignal.THREEWAY_VALVE_STATE)
        if (defrost or dhw) and record.setpoint < reference and record.binding not in HARD_HIGH:
            what = "defrost" if defrost else "DHW"
            self._fail(
                "freeze",
                ts,
                f"setpoint {reference} → {record.setpoint} during {what} "
                f"(binding {record.binding})",
            )
        if record.binding in BYPASS_BINDINGS:
            return
        stages = self.config.stages
        distance = abs(record.pre_round - reference)
        if distance < stages.change_threshold_k - EPSILON:
            self._fail(
                "deadband",
                ts,
                f"setpoint {reference} → {record.setpoint} with pre_round {record.pre_round:.3f} "
                f"only {distance:.3f} K away (threshold {stages.change_threshold_k} K)",
            )
        last_change = _number(prev.get("last_change_at"))
        applied = _number(state.get("dwell_remaining_s"))
        if last_change is None:
            return
        if applied is None:
            self._fail("dwell", ts, "setpoint change without a recorded dwell")
            return
        elapsed = record.at.monotonic - last_change
        if elapsed < applied - EPSILON:
            self._fail(
                "dwell",
                ts,
                f"setpoint {reference} → {record.setpoint} {elapsed:.0f} s after the previous "
                f"change (dwell {applied:.0f} s)",
            )
        allowed = {stages.dwell_s}
        if self._ramp_evident(prev, state):
            allowed.add(stages.ramp_dwell_s)
            if prev.get("ramp_cap_c") is None:
                allowed.add(0.0)
        if not any(abs(applied - option) < EPSILON for option in allowed):
            self._fail(
                "dwell",
                ts,
                f"applied dwell {applied:.0f} s is not one of {sorted(allowed)} "
                f"(ramp {prev.get('ramp_phase')} → {state.get('ramp_phase')})",
            )

    def _check_apply(self, row: DecisionRow, record: DecisionRecord, state: dict[str, Any]) -> None:
        version = self._applied
        if version is None or row.config_version != version:
            return
        self._applied = None
        self._just_applied = True
        self.observations["config_applies_checked"] += 1
        prev = self._prev
        if prev is None or record.ladder not in CONTROL_LEVELS or record.setpoint is None:
            return
        reference = prev.get("setpoint")
        if reference is None:
            return
        ts = row.ts
        if record.setpoint == reference:
            if state.get("last_change_at") != prev.get("last_change_at"):
                self._fail("apply_jump", ts, "the dwell timer was reset by the apply")
            return
        if record.binding in BYPASS_BINDINGS or record.pre_round is None:
            return
        stages = self.config.stages
        distance = abs(record.pre_round - reference)
        last_change = _number(prev.get("last_change_at"))
        elapsed = None if last_change is None else record.at.monotonic - last_change
        dwell = _number(state.get("dwell_remaining_s"))
        too_close = distance < stages.change_threshold_k - EPSILON
        too_soon = elapsed is not None and dwell is not None and elapsed < dwell - EPSILON
        if too_close or too_soon:
            self._fail(
                "apply_jump",
                ts,
                f"setpoint {reference} → {record.setpoint} on the first tick of configuration "
                f"version {version} (pre_round {record.pre_round:.3f}, elapsed {elapsed})",
            )

    def _check_duty(self, row: DecisionRow, record: DecisionRecord) -> None:
        pump = self.config.pump_duty
        duty = _intent(record, IntentKind.MAX_PUMP_DUTY)
        if pump is None or duty is None:
            return
        ts = row.ts
        frequency, fresh = _ref(record, HeishaSignal.COMPRESSOR_FREQ)
        hz = _number(frequency)
        running = fresh and hz is not None and hz >= self.config.compressor_min_hz
        defrost = _flag(record, HeishaSignal.DEFROSTING_STATE)
        dhw = _flag(record, HeishaSignal.THREEWAY_VALVE_STATE)
        if defrost:
            self._fail(
                "duty_in_defrost",
                ts,
                f"pump duty intent {duty} during a defrost (the pump drives its own duty)",
            )
            return
        if (running or dhw) and duty < pump.heat:
            self._fail(
                "idle_duty_running",
                ts,
                f"pump duty {duty} below the heat duty {pump.heat} while the compressor runs "
                f"or DHW is active ({hz} Hz, DHW {dhw}, ladder {record.ladder.value})",
            )
        previous = self._prev_duty
        if dhw and previous is not None and duty != previous:
            if duty < previous:
                self._fail("freeze", ts, f"pump duty {previous} → {duty} during DHW")
            else:
                self.observations["pump_duty_raised_in_dhw"] += 1

    def publish(
        self,
        ts: float,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
        guard: PublishGuard,
        firmware: str | None,
    ) -> None:
        """Check one publish as it leaves the command link."""
        self.publishes += 1
        if not guard.permits:
            self._fail("guard", ts, f"published {topic} while the guard refuses")
        if topic not in self.adapter.topics():
            self._fail("guard", ts, f"published to {topic}, not allowlisted")
        self._check_setting_publish(ts, topic, payload)
        if retain or qos != 1:
            self._fail("guard", ts, f"published {topic} with retain={retain} qos={qos}")
        if firmware is None or not firmware.endswith(SIM_VERSION_SUFFIX):
            self._fail("guard", ts, f"published to a board reporting firmware {firmware!r}")
        last = self._last_publish
        if last is not None and ts - last < self.adapter.min_spacing_s - EPSILON:
            self._fail("spacing", ts, f"publishes {ts - last:.1f} s apart")
        self._last_publish = ts
        self._awaiting_sent.append((topic, len(payload), ts))

    def _check_setting_publish(self, ts: float, topic: str, payload: str) -> None:
        setting = next(
            (s for s in PumpSetting if self.adapter.topic(s) == topic),
            None,
        )
        if setting is None:
            return
        spec = PUMP_SETTINGS[setting]
        if not payload.lstrip("-").isdigit() or not spec.low <= int(payload) <= spec.high:
            self._fail(
                "pump_setting",
                ts,
                f"published {payload!r} to {topic}, not an integer in [{spec.low}, {spec.high}]",
            )

    def _check_setting_command(self, row: CommandRow, status: CommandStatus) -> None:
        if not row.detail.startswith(OPERATOR_PREFIX):
            self._fail("pump_setting", row.ts, f"{row.kind} {row.status} not by an operator")
        if status is not CommandStatus.SENT:
            return
        self.observations[SETTING_WRITES] += 1
        if self.defrosting is not None and self.defrosting():
            self._fail("pump_setting", row.ts, f"{row.kind}={row.value} sent during a defrost")
        if self.dhw is not None and self.dhw():
            self._fail("pump_setting", row.ts, f"{row.kind}={row.value} sent during a DHW run")

    def command(self, row: CommandRow) -> None:
        """Check one stored command event."""
        self.command_events += 1
        ts = row.ts
        self._settle_alarms(ts)
        kind: CommandKind
        try:
            status = CommandStatus(row.status)
            kind = PumpSetting(row.kind) if row.kind in PUMP_SETTINGS else IntentKind(row.kind)
        except ValueError:
            self._fail("command_schema", ts, f"unknown status or kind in {row}")
            return
        operator = isinstance(kind, PumpSetting)
        if isinstance(kind, PumpSetting):
            self._check_setting_command(row, status)
        if not row.detail.strip():
            self._fail("explained", ts, f"{row.kind} {row.status} without a detail")
        if type(row.value) is not int:
            self._fail("integers", ts, f"command value {row.value!r} is not an integer")
        if status is not CommandStatus.REFUSED:
            self._check_command_shape(row, kind)
        self.observations[f"command_{status.value}"] += 1
        corrective = row.detail.startswith(SAFETY_PREFIX)
        if corrective and status is CommandStatus.QUEUED:
            self.observations["safety_corrections"] += 1
        self._check_duty_command(row, kind, status)
        if status is CommandStatus.QUEUED and not corrective and not operator:
            self._queued_unchecked.append((ts, row.kind, row.value))
        match status:
            case CommandStatus.QUEUED:
                self._queued[row.kind] = (row.value, corrective)
            case CommandStatus.SENT:
                self._sent(row)
            case CommandStatus.DROPPED:
                self._dropped(row)
            case CommandStatus.VERIFIED | CommandStatus.RETRY | CommandStatus.FAILED:
                self._concluded(row, status)
            case CommandStatus.REFUSED:
                pass

    def _check_duty_command(
        self, row: CommandRow, kind: CommandKind, status: CommandStatus
    ) -> None:
        if kind is not IntentKind.MAX_PUMP_DUTY or self.defrosting is None:
            return
        if status not in (CommandStatus.QUEUED, CommandStatus.SENT) or not self.defrosting():
            return
        self.observations[DUTY_IN_DEFROST] += 1
        self._fail(
            "duty_in_defrost",
            row.ts,
            f"max_pump_duty={row.value} {row.status} while the plant defrosts",
        )

    def _check_command_shape(self, row: CommandRow, kind: CommandKind) -> None:
        low, high = self.adapter.clamp_range(kind)
        if not low <= row.value <= high:
            self._fail("safety_limits", row.ts, f"{row.kind}={row.value} outside [{low}, {high}]")
        if row.topic is not None and row.topic != self.adapter.topic(kind):
            self._fail("command_shape", row.ts, f"{row.kind} on topic {row.topic}")
        if row.payload is not None and row.payload != self.adapter.payload(kind, row.value):
            self._fail("command_shape", row.ts, f"{row.kind} payload {row.payload!r}")

    def _sent(self, row: CommandRow) -> None:
        ts = row.ts
        flying = self._in_flight
        if flying is not None and not (flying.kind == row.kind and flying.value == row.value):
            self._fail(
                "one_in_flight",
                ts,
                f"{row.kind}={row.value} sent while {flying.kind}={flying.value} is unconcluded",
            )
        matched = next(
            (item for item in self._awaiting_sent if item[0] == row.topic and ts - item[2] < 1.0),
            None,
        )
        if matched is None:
            self._fail("guard", ts, f"{row.kind}={row.value} journalled as sent without a publish")
        else:
            self._awaiting_sent.remove(matched)
        queued = self._queued.pop(row.kind, None)
        if queued is None or queued[0] != row.value:
            self._fail("explained", ts, f"{row.kind}={row.value} sent without being queued")
        corrective = queued is not None and queued[1]
        wanted = self._intents.get(row.kind)
        if not corrective and row.kind not in PUMP_SETTINGS and wanted != row.value:
            self._fail(
                "intent_match",
                ts,
                f"{row.kind}={row.value} sent but the latest decision wants {wanted}",
            )
        self._in_flight = _InFlight(row.kind, row.value, ts, corrective)
        day = _iso(ts)[:10]
        self._sent_per_day[day] += 1
        if corrective:
            self._corrective_per_day[day] += 1
        regular = self._sent_per_day[day] - self._corrective_per_day[day]
        if self._sent_per_day[day] > self.adapter.daily_budget + self.adapter.safety_reserve:
            self._fail("budget", ts, f"{self._sent_per_day[day]} commands on {day}")
        if regular > self.adapter.daily_budget:
            self._fail("budget", ts, f"{regular} regular commands on {day}")

    def _dropped(self, row: CommandRow) -> None:
        flying = self._in_flight
        matches = flying is not None and (flying.kind, flying.value) == (row.kind, row.value)
        if matches and ("pre-empted" in row.detail or "in flight" in row.detail):
            self._in_flight = None
            return
        queued = self._queued.get(row.kind)
        if queued is not None and queued[0] == row.value:
            self._queued.pop(row.kind, None)

    def _concluded(self, row: CommandRow, status: CommandStatus) -> None:
        flying = self._in_flight
        if flying is None or flying.kind != row.kind or flying.value != row.value:
            self._fail(
                "explained",
                row.ts,
                f"{row.kind}={row.value} {status.value} without a matching command in flight",
            )
            return
        self._in_flight = None
        if status is CommandStatus.RETRY:
            self._queued[row.kind] = (row.value, flying.corrective)
        if status is CommandStatus.FAILED and not flying.corrective:
            self._awaiting_alarm.append(row.ts)

    def alarm(self, row: AlarmRow) -> None:
        """Track active alarms (for the ``failed`` → alarm rule)."""
        if row.event == "raised":
            self._active_alarms.add(row.code)
        elif row.event == "cleared":
            self._active_alarms.discard(row.code)
        self._settle_alarms(row.ts, final=False)

    def _settle_alarms(self, ts: float, final: bool = False) -> None:
        if not self._awaiting_alarm:
            return
        if AlarmCode.VERIFICATION_FAILED.value in self._active_alarms:
            self._awaiting_alarm.clear()
            return
        due = [t for t in self._awaiting_alarm if final or ts - t > EPSILON]
        for t in due:
            self._fail("explained", t, "failed command without a verification_failed alarm")
            self._awaiting_alarm.remove(t)

    def finish(self, ts: float, verify_timeout_s: float) -> None:
        """Close the run at ``ts``: unconcluded commands must still be within their timeout."""
        self._settle_alarms(ts, final=True)
        flying = self._in_flight
        if flying is not None and ts - flying.sent_at > verify_timeout_s + END_GRACE_S:
            self._fail(
                "explained",
                flying.sent_at,
                f"{flying.kind}={flying.value} sent and never verified or explained",
            )
        for topic, _, at in self._awaiting_sent:
            self._fail("guard", at, f"publish to {topic} never journalled as sent")
        self._awaiting_sent.clear()

    def summary(self) -> dict[str, Any]:
        """Return the JSON summary."""
        return {
            "decisions_checked": self.decisions,
            "command_events_checked": self.command_events,
            "publishes_checked": self.publishes,
            "violations": self.total,
            "by_rule": dict(sorted(self.counts.items())),
            "first": [item.to_json() for item in self.violations[:50]],
            "observations": dict(sorted(self.observations.items())),
        }
