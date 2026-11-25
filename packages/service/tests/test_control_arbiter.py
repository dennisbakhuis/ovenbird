from __future__ import annotations

from ovenbird.control.arbiter import Action, AdapterView, arbitrate
from ovenbird_core.control import ActualValue, CommandIntent, IntentKind, PumpActual, ReasonCode

SETPOINT = CommandIntent(IntentKind.WATER_SETPOINT, 31, ReasonCode.CURVE)
DUTY = CommandIntent(IntentKind.MAX_PUMP_DUTY, 102, ReasonCode.PUMP_DUTY_IDLE)
QUIET = CommandIntent(IntentKind.QUIET_MODE, 1, ReasonCode.QUIET_SCHEDULE)


def actual(value: int, *, fresh: bool = True, signal: str = "main/x") -> ActualValue:
    return ActualValue(value, 3.0, fresh, signal)


def pump(water: int | None = 30, duty: int | None = 159, quiet: int | None = 0) -> PumpActual:
    return PumpActual(
        water_target=None if water is None else actual(water),
        max_pump_duty=None if duty is None else actual(duty),
        quiet_mode=None if quiet is None else actual(quiet),
    )


def test_send_when_the_pump_reports_another_value() -> None:
    (decision,) = arbitrate([SETPOINT], pump(water=30))
    assert decision.action is Action.SEND
    assert decision.actual == 30
    assert decision.to_json() == {
        "kind": "water_setpoint",
        "intent": 31,
        "actual": 30,
        "action": "send",
        "reason": "pump reports 30",
    }


def test_nothing_when_already_applied() -> None:
    decisions = arbitrate([SETPOINT, DUTY, QUIET], pump(water=31, duty=102, quiet=1))
    assert [d.action for d in decisions] == [Action.NONE] * 3
    assert {d.reason for d in decisions} == {"already applied"}


def test_never_write_blind() -> None:
    stale = PumpActual(water_target=actual(30, fresh=False))
    assert arbitrate([SETPOINT], stale)[0].action is Action.SKIP
    assert arbitrate([SETPOINT], pump(water=None))[0].action is Action.SKIP


def test_in_flight_and_queued_are_not_repeated() -> None:
    in_flight = AdapterView(in_flight={IntentKind.WATER_SETPOINT: 31})
    assert arbitrate([SETPOINT], pump(), in_flight)[0].reason == "in flight"
    queued = AdapterView(queued={IntentKind.WATER_SETPOINT: 31})
    assert arbitrate([SETPOINT], pump(), queued)[0].action is Action.NONE
    other = AdapterView(in_flight={IntentKind.WATER_SETPOINT: 29})
    assert arbitrate([SETPOINT], pump(), other)[0].action is Action.SEND


def test_hold_skips_writes_but_not_applied_values() -> None:
    view = AdapterView(hold="foreign writer")
    decisions = arbitrate([SETPOINT, DUTY], pump(water=30, duty=102), view)
    assert decisions[0].action is Action.SKIP
    assert decisions[0].reason == "hold: foreign writer"
    assert decisions[1].action is Action.NONE


def test_arbiter_is_pure_and_ordered() -> None:
    first = arbitrate([DUTY, SETPOINT], pump())
    assert first == arbitrate([DUTY, SETPOINT], pump())
    assert [d.intent.kind for d in first] == [IntentKind.MAX_PUMP_DUTY, IntentKind.WATER_SETPOINT]
    assert arbitrate([], pump()) == ()
