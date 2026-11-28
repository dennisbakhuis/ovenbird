from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

from ovenbird.control import PublishGuard
from ovenbird.control.loop import controller_config
from ovenbird.history.journal import CommandRow, DecisionRow
from ovenbird_core.control import Mode
from ovenbird_harness.invariants import (
    DUTY_IN_DEFROST,
    InvariantChecker,
    PlantReading,
    envelope_bounds,
    round_half_up,
)
from ovenbird_harness.testing import RecordedRun

CONTROL = ("schedule_curve_feedback", "curve_only")


def checker(short_run: RecordedRun) -> InvariantChecker:
    """Return a fresh invariant checker on the recorded run's controller and adapter settings."""
    run = short_run.run
    return InvariantChecker(controller_config(run.settings), run.system.adapter.config)


def mutate(row: DecisionRow, change: Callable[[dict[str, Any]], None]) -> DecisionRow:
    """Return ``row`` with its decision record changed in place by ``change``."""
    record = json.loads(row.record)
    change(record)
    return dataclasses.replace(row, record=json.dumps(record), setpoint=record["setpoint"])


def intent(record: dict[str, Any], kind: str) -> dict[str, Any]:
    """Return the intent of ``kind`` in the decision record."""
    return next(item for item in record["intents"] if item["kind"] == kind)


def ref(record: dict[str, Any], signal: str) -> dict[str, Any]:
    """Return the used input of ``signal`` in the decision record."""
    return next(item for item in record["inputs_used"] if item["signal"] == signal)


def controlled(short_run: RecordedRun) -> list[int]:
    """Return the indices of the decisions made under automatic control."""
    return [i for i, row in enumerate(short_run.decisions) if row.ladder in CONTROL]


def feed(check: InvariantChecker, rows: list[DecisionRow]) -> InvariantChecker:
    """Show ``rows`` to ``check`` in order and return it."""
    for row in rows:
        check.decision(row)
    return check


def test_the_recorded_run_is_clean(short_run: RecordedRun) -> None:
    """The unmodified recorded run has no violation and all 720 decisions are checked."""
    assert short_run.result.passed
    check = feed(checker(short_run), short_run.decisions)
    assert check.total == 0, check.summary()
    assert check.decisions == len(short_run.decisions) == 720


def test_setpoint_outside_the_envelope(short_run: RecordedRun) -> None:
    """A setpoint above the safety envelope is a violation."""
    index = controlled(short_run)[-1]

    def above(record: dict[str, Any]) -> None:
        """Raise the setpoint one degree above the safety maximum."""
        high = record["controller_state"]["safety_high_c"]
        record["setpoint"] = int(high) + 1
        intent(record, "water_setpoint")["value"] = int(high) + 1
        record["binding"] = "safety_max"

    rows = [*short_run.decisions[:index], mutate(short_run.decisions[index], above)]
    check = feed(checker(short_run), rows)
    assert check.counts["envelope"] >= 1


def test_unexplained_rounding_needs_a_binding(short_run: RecordedRun) -> None:
    """A rounded setpoint that differs from plain rounding of the unrounded one needs a binding."""
    rows = short_run.decisions
    index = next(
        i
        for i in controlled(short_run)
        if json.loads(rows[i].record)["binding"] is None
        and json.loads(rows[i].record)["setpoint"]
        == round_half_up(json.loads(rows[i].record)["pre_round"])
    )

    def shift(record: dict[str, Any]) -> None:
        """Shift the unrounded setpoint by 0.8 K."""
        record["pre_round"] += 0.8

    check = feed(checker(short_run), [*rows[:index], mutate(rows[index], shift)])
    assert check.counts["binding"] == 1


def test_non_integer_setpoint(short_run: RecordedRun) -> None:
    """A fractional water setpoint intent is a violation."""
    index = controlled(short_run)[0]

    def fractional(record: dict[str, Any]) -> None:
        """Make the water setpoint intent half a degree fractional."""
        intent(record, "water_setpoint")["value"] = record["setpoint"] + 0.5

    check = feed(checker(short_run), [mutate(short_run.decisions[index], fractional)])
    assert check.counts["integers"] == 1


def test_idle_pump_duty_while_the_compressor_runs(short_run: RecordedRun) -> None:
    """The idle pump duty while the compressor runs is a violation."""
    rows = short_run.decisions
    pump = controller_config(short_run.run.settings).pump_duty
    assert pump is not None

    def running(i: int) -> bool:
        """Return whether the compressor of decision ``i`` runs."""
        record = json.loads(rows[i].record)
        frequency = ref(record, "main/Compressor_Freq")
        return bool(frequency["fresh"]) and frequency["value"] >= 1

    index = next(i for i in controlled(short_run) if running(i))

    def idle(record: dict[str, Any]) -> None:
        """Replace the pump duty intent by the idle duty."""
        intent(record, "max_pump_duty")["value"] = pump.idle

    check = feed(checker(short_run), [mutate(rows[index], idle)])
    assert check.counts["idle_duty_running"] == 1


def test_integrator_beyond_its_clamp(short_run: RecordedRun) -> None:
    """An integrator beyond its clamp is a violation."""

    def wound(record: dict[str, Any]) -> None:
        """Wind the integrator up to 4 K."""
        record["controller_state"]["integral_k"] = 4.0

    check = feed(checker(short_run), [mutate(short_run.decisions[-1], wound)])
    assert check.counts["integrator_clamp"] == 1


def _change_pair(short_run: RecordedRun) -> tuple[DecisionRow, DecisionRow]:
    """Return two consecutive decisions that are both under automatic control."""
    rows = short_run.decisions
    first, second = next(
        (rows[i], rows[i + 1])
        for i in controlled(short_run)
        if i + 1 < len(rows) and rows[i + 1].ladder in CONTROL
    )
    return first, second


def test_dwell_is_enforced(short_run: RecordedRun) -> None:
    """A setpoint change inside the dwell time is a violation."""
    first, second = _change_pair(short_run)
    stages = controller_config(short_run.run.settings).stages

    def changed(record: dict[str, Any]) -> None:
        """Change the setpoint by 2 K with the dwell time still running."""
        state = record["controller_state"]
        reference = json.loads(first.record)["controller_state"]["setpoint"]
        record["setpoint"] = reference + 2
        record["pre_round"] = reference + 2.0
        record["binding"] = None
        intent(record, "water_setpoint")["value"] = reference + 2
        state["setpoint"] = reference + 2
        state["dwell_remaining_s"] = stages.dwell_s

    def recent(record: dict[str, Any]) -> None:
        """Mark the previous setpoint change as having just happened."""
        state = record["controller_state"]
        state["last_change_at"] = record["at"]["monotonic"]
        state["ramp_phase"] = "idle"

    check = feed(checker(short_run), [mutate(first, recent), mutate(second, changed)])
    assert check.counts["dwell"] >= 1


def test_deadband_is_enforced(short_run: RecordedRun) -> None:
    """A setpoint change smaller than the deadband is a violation."""
    first, second = _change_pair(short_run)

    def nudged(record: dict[str, Any]) -> None:
        """Nudge the setpoint by 1 K, rounded from only 0.6 K."""
        reference = json.loads(first.record)["controller_state"]["setpoint"]
        record["setpoint"] = reference + 1
        record["pre_round"] = reference + 0.6
        record["binding"] = "rounding"
        intent(record, "water_setpoint")["value"] = reference + 1

    check = feed(checker(short_run), [first, mutate(second, nudged)])
    assert check.counts["deadband"] == 1


def test_no_decrease_during_defrost(short_run: RecordedRun) -> None:
    """A setpoint decrease while the pump defrosts is a violation."""
    first, second = _change_pair(short_run)

    def defrosting(record: dict[str, Any]) -> None:
        """Report a defrost and lower the setpoint by 2 K."""
        reference = json.loads(first.record)["controller_state"]["setpoint"]
        ref(record, "main/Defrosting_State")["value"] = 1
        ref(record, "main/Defrosting_State")["fresh"] = True
        record["setpoint"] = reference - 2
        record["pre_round"] = reference - 2.0
        record["binding"] = None
        intent(record, "water_setpoint")["value"] = reference - 2

    check = feed(checker(short_run), [first, mutate(second, defrosting)])
    assert check.counts["freeze"] == 1


def _command(ts: float, status: str, value: int = 30, detail: str = "x") -> CommandRow:
    """Return a ``water_setpoint`` command row of ``status`` at ``ts``.

    Parameters
    ----------
    ts
        Time of the event in unix seconds.
    status
        Command status (``queued``, ``sent``, ``verified``).
    value
        Water setpoint in °C.
    detail
        Free-text detail of the event.

    Returns
    -------
    CommandRow
        A first-attempt row with the matching SetCurves payload.
    """
    return CommandRow(
        ts,
        "water_setpoint",
        value,
        status,
        1,
        "panasonic_heat_pump/commands/SetCurves",
        f'{{"zone1":{{"heat":{{"target":{{"high":{value}}}}}}}}}',
        detail,
    )


def test_a_sent_command_must_be_concluded(short_run: RecordedRun) -> None:
    """A command sent but never concluded as verified or failed is reported at the end."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    row = _command(1000.0, "queued")
    check.command(row)
    check.publish(1000.0, row.topic or "", row.payload or "", 1, False, guard, "3.9-sim")
    check.command(_command(1000.0, "sent"))
    check.finish(5000.0, 30.0)
    assert check.counts["explained"] == 1


def test_publish_without_the_guard(short_run: RecordedRun) -> None:
    """A publish while the guard refuses, or too soon after the last one, is a violation."""
    check = checker(short_run)
    settings = short_run.run.settings.model_copy(update={"control_mode": "shadow"})
    refusing = PublishGuard.from_settings(settings)
    assert refusing.mode is Mode.SHADOW
    topic = "panasonic_heat_pump/commands/SetCurves"
    check.publish(1000.0, topic, "{}", 1, False, refusing, "3.9-sim")
    check.publish(1002.0, topic, "{}", 1, True, short_run.run.system.loop.guard, "3.9")
    assert check.counts["guard"] == 3
    assert check.counts["spacing"] == 1


@pytest.mark.parametrize("extra", [0, 1])
def test_daily_budget(short_run: RecordedRun, extra: int) -> None:
    """Writes within the daily budget are clean; one more is a violation."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    budget = check.adapter.daily_budget
    for n in range(budget + extra):
        ts = 1_794_000_000.0 + 10.0 * n
        value = 25 + n % 10
        check.command(_command(ts, "queued", value))
        check.publish(
            ts, "panasonic_heat_pump/commands/SetCurves", "{}", 1, False, guard, "3.9-sim"
        )
        check.command(_command(ts, "sent", value))
        check.command(_command(ts + 5.0, "verified", value))
    assert check.counts["budget"] == extra


def test_independent_envelope_formula(short_run: RecordedRun) -> None:
    """The independent envelope formula also flags a setpoint above the maximum."""
    index = controlled(short_run)[-1]

    def above(record: dict[str, Any]) -> None:
        """Raise the setpoint one degree above the safety maximum."""
        high = record["controller_state"]["safety_high_c"]
        record["setpoint"] = int(high) + 1
        intent(record, "water_setpoint")["value"] = int(high) + 1

    check = feed(checker(short_run), [mutate(short_run.decisions[index], above)])
    assert check.counts["envelope_independent"] == 1


def test_envelope_bounds_are_written_out() -> None:
    """The envelope bounds follow the curve and margins for several outside temperatures."""
    points = [(-10.0, 39.0), (0.0, 34.0), (15.0, 25.0)]
    assert envelope_bounds(points, 6.0, 5.0, 25.0, 40.0, 0.0) == (28, 39)
    assert envelope_bounds(points, 6.0, 5.0, 25.0, 40.0, -20.0) == (33, 40)
    assert envelope_bounds(points, 6.0, 5.0, 25.0, 40.0, 7.5) == (25, 34)
    assert envelope_bounds(points, 6.0, 5.0, 25.0, 40.0, 30.0) == (25, 30)


def test_sent_value_must_be_the_latest_intent(short_run: RecordedRun) -> None:
    """A sent value that is not the latest decided intent is a violation."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    row = short_run.decisions[controlled(short_run)[-1]]
    wanted = json.loads(row.record)["setpoint"]
    check.decision(row)
    for value, ts in ((wanted, 2000.0), (wanted + 1, 2100.0)):
        queued = _command(ts, "queued", value)
        check.command(queued)
        check.publish(ts, queued.topic or "", queued.payload or "", 1, False, guard, "3.9-sim")
        check.command(_command(ts, "sent", value))
        check.command(_command(ts + 5.0, "verified", value))
    assert check.counts["intent_match"] == 1


def test_queued_value_must_match_its_decision(short_run: RecordedRun) -> None:
    """A queued value that differs from its decision's intent is a violation."""
    check = checker(short_run)
    row = short_run.decisions[controlled(short_run)[-1]]
    wanted = json.loads(row.record)["setpoint"]
    check.command(_command(row.ts, "queued", wanted + 2))
    check.decision(row)
    assert check.counts["intent_match"] == 1
    check.command(_command(row.ts + 60.0, "queued", wanted))
    check.decision(dataclasses.replace(row, ts=row.ts))
    assert check.counts["intent_match"] == 1


def test_no_pump_duty_in_defrost(short_run: RecordedRun) -> None:
    """A pump duty command or decision during a defrost is a violation."""
    rows = short_run.decisions
    index = next(i for i in controlled(short_run) if '"max_pump_duty"' in rows[i].record)

    def defrosting(record: dict[str, Any]) -> None:
        """Report a defrost in the decision's inputs."""
        ref(record, "main/Defrosting_State")["value"] = 1
        ref(record, "main/Defrosting_State")["fresh"] = True

    check = feed(checker(short_run), [mutate(rows[index], defrosting)])
    assert check.counts["duty_in_defrost"] == 1
    plant = {"defrost": True}
    run = short_run.run
    commands = InvariantChecker(
        controller_config(run.settings),
        run.system.adapter.config,
        defrosting=lambda: plant["defrost"],
    )
    duty = CommandRow(5000.0, "max_pump_duty", 159, "queued", 0, None, None, "queued")
    commands.command(duty)
    plant["defrost"] = False
    commands.command(dataclasses.replace(duty, ts=5100.0))
    assert commands.counts["duty_in_defrost"] == 1
    assert commands.observations[DUTY_IN_DEFROST] == 1


def test_integrator_and_ramp_cap_frozen_in_defrost(short_run: RecordedRun) -> None:
    """The integrator changing during a defrost is a violation."""
    first, second = _change_pair(short_run)

    def defrosting(record: dict[str, Any]) -> None:
        """Report a defrost, move the integrator and drop the pump duty intent."""
        ref(record, "main/Defrosting_State")["value"] = 1
        ref(record, "main/Defrosting_State")["fresh"] = True
        record["controller_state"]["integral_k"] = (
            json.loads(first.record)["controller_state"]["integral_k"] + 0.1
        )
        record["intents"] = [i for i in record["intents"] if i["kind"] != "max_pump_duty"]

    check = feed(checker(short_run), [first, mutate(second, defrosting)])
    assert check.counts["freeze"] >= 1
    assert any("integrator" in v.detail for v in check.violations)


def test_cycling_floor_binding_outside_the_window(short_run: RecordedRun) -> None:
    """The cycling-floor binding outside the minimum-run window is a violation."""
    rows = short_run.decisions
    index = next(
        i
        for i in controlled(short_run)
        if json.loads(rows[i].record)["controller_state"].get("run_started_at") is None
    )

    def floor(record: dict[str, Any]) -> None:
        """Bind the decision to the cycling floor."""
        record["binding"] = "cycling_floor"

    check = feed(checker(short_run), [mutate(rows[index], floor)])
    assert check.counts["binding"] == 1
    assert "minimum-run window" in check.violations[0].detail


def test_safety_binding_away_from_the_bound(short_run: RecordedRun) -> None:
    """A safety binding while the setpoint is away from the bound is a violation."""
    rows = short_run.decisions
    index = controlled(short_run)[-1]

    def bound(record: dict[str, Any]) -> None:
        """Bind the decision to the envelope maximum with the setpoint two degrees below it."""
        record["binding"] = "envelope_max"
        record["setpoint"] = int(record["controller_state"]["safety_high_c"]) - 2
        intent(record, "water_setpoint")["value"] = record["setpoint"]

    check = feed(checker(short_run), [mutate(rows[index], bound)])
    assert check.counts["binding"] >= 1


def _reading(ts: float, **values: Any) -> PlantReading:
    """Return a plant reading at ``ts`` with ``values`` overriding an idle pump at 30 °C.

    Parameters
    ----------
    ts
        Time of the reading in unix seconds.
    **values
        Fields of the reading to override.

    Returns
    -------
    PlantReading
        The reading.
    """
    base: dict[str, Any] = {
        "setpoint_register": 30,
        "max_pump_duty": 102,
        "outlet_c": 30.0,
        "running": False,
        "defrosting": False,
        "commands_blocked": False,
    }
    base.update(values)
    return PlantReading(ts, **base)


def test_plant_register_outlet_and_duty(short_run: RecordedRun) -> None:
    """Plant register, outlet temperature and pump duty deviations are counted once each."""
    check = checker(short_run)
    check.plant(_reading(0.0))
    for k in range(1, 40):
        check.plant(_reading(5.0 * k, setpoint_register=45, running=True, max_pump_duty=159))
    assert check.counts["plant_register"] == 1
    check.plant(_reading(300.0, outlet_c=47.0))
    check.plant(_reading(305.0, outlet_c=47.5))
    assert check.counts["plant_outlet"] == 1
    check.plant(_reading(400.0))
    for k in range(1, 25):
        check.plant(_reading(400.0 + 5.0 * k, running=True))
    assert check.counts["plant_duty"] == 1
    check.plant(_reading(600.0))
    for k in range(1, 25):
        check.plant(_reading(600.0 + 5.0 * k, running=True, commands_blocked=k == 3))
    assert check.counts["plant_duty"] == 1
    assert check.observations["plant_starts_excused"] == 1


def test_plant_duty_waits_out_a_defrost_after_the_start(short_run: RecordedRun) -> None:
    """The plant duty check waits out a defrost after a compressor start, then applies."""
    check = checker(short_run)
    check.plant(_reading(0.0))
    check.plant(_reading(5.0, running=True))
    for k in range(2, 60):
        check.plant(_reading(5.0 * k, running=True, defrosting=True))
    assert check.counts["plant_duty"] == 0
    assert check.observations["plant_starts_into_defrost"] == 1
    for k in range(60, 77):
        check.plant(_reading(5.0 * k, running=True))
    assert check.counts["plant_duty"] == 0
    for k in range(77, 80):
        check.plant(_reading(5.0 * k, running=True))
    assert check.counts["plant_duty"] == 1
    assert check.observations["plant_defrost_ends_checked"] == 1


def _setting(
    ts: float, status: str, value: int, detail: str = "operator: admin: test"
) -> CommandRow:
    """Return a ``heat_delta`` command row of ``status`` at ``ts``.

    Parameters
    ----------
    ts
        Time of the event in unix seconds.
    status
        Command status (``queued``, ``sent``, ``verified``).
    value
        Delta-T in K.
    detail
        Free-text detail of the event.

    Returns
    -------
    CommandRow
        The row, attempt 0 when queued.
    """
    return CommandRow(
        ts=ts,
        kind="heat_delta",
        value=value,
        status=status,
        attempt=0 if status == "queued" else 1,
        topic="panasonic_heat_pump/commands/SetFloorHeatDelta",
        payload=str(value),
        detail=detail,
    )


def test_an_operator_write_is_clean(short_run: RecordedRun) -> None:
    """A named operator write that is sent outside a defrost raises no violation."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    check.command(_setting(3000.0, "queued", 6))
    check.publish(
        3000.0, "panasonic_heat_pump/commands/SetFloorHeatDelta", "6", 1, False, guard, "3.9-sim"
    )
    check.command(_setting(3000.0, "sent", 6))
    check.command(_setting(3010.0, "verified", 6))
    assert check.total == 0, check.summary()
    assert check.observations["pump_setting_commands_sent"] == 1


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("panasonic_heat_pump/commands/SetFloorHeatDelta", "11"),
        ("panasonic_heat_pump/commands/SetFloorHeatDelta", "4.5"),
        ("panasonic_heat_pump/commands/SetPumpFlowrateMode", "2"),
        ("panasonic_heat_pump/commands/SetHeatingOffOutdoorTemp", "9"),
    ],
)
def test_pump_setting_publishes_stay_in_their_clamp(
    short_run: RecordedRun, topic: str, payload: str
) -> None:
    """A pump setting publish outside its permitted clamp is a violation."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    check.publish(4000.0, topic, payload, 1, False, guard, "3.9-sim")
    assert check.counts["pump_setting"] == 1


def test_only_the_three_settings_are_allowlisted(short_run: RecordedRun) -> None:
    """Only the three pump settings are allowlisted; any other setting is a guard violation."""
    check = checker(short_run)
    guard = short_run.run.system.loop.guard
    for name in ("SetHeaterOnOutdoorTemp", "SetHeatpump", "SetQuietModePriority"):
        check.publish(
            5000.0, f"panasonic_heat_pump/commands/{name}", "1", 1, False, guard, "3.9-sim"
        )
    assert check.counts["guard"] == 3
    assert len(check.adapter.topics()) == 6


def test_operator_writes_must_name_the_operator_and_avoid_defrost(short_run: RecordedRun) -> None:
    """An operator write without the operator's name, or during a defrost, is a violation."""
    run = short_run.run
    check = InvariantChecker(
        controller_config(run.settings), run.system.adapter.config, defrosting=lambda: True
    )
    check.command(_setting(6000.0, "queued", 6, detail="queued"))
    check.command(_setting(6000.0, "sent", 6))
    assert check.counts["pump_setting"] == 2


def test_a_held_setpoint_must_stay_within_the_bounds(short_run: RecordedRun) -> None:
    """A held setpoint above the safety bounds is a violation of the envelope and ladder rules."""
    index = controlled(short_run)[-1]

    def held_above(record: dict[str, Any]) -> None:
        """Hold the setpoint three degrees above the safety maximum."""
        value = int(record["controller_state"]["safety_high_c"]) + 3
        record["ladder"] = "hold"
        record["reason"] = "inputs_missing"
        record["setpoint"] = value
        record["pre_round"] = None
        record["binding"] = None
        record["terms"] = []
        record["controller_state"]["setpoint"] = value
        record["intents"] = [{"kind": "water_setpoint", "value": value, "reason": "inputs_missing"}]

    row = mutate(short_run.decisions[index], held_above)
    row = dataclasses.replace(row, ladder="hold", reason="inputs_missing")
    check = feed(checker(short_run), [*short_run.decisions[:index], row])
    assert check.counts["envelope"] >= 1
    assert check.counts["ladder"] >= 1
