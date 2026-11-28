from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import pytest

from ovenbird.clock import iso_z
from ovenbird.control.adapter import (
    AdapterConfig,
    CommandAdapter,
    CommandEvent,
    CommandStatus,
    HoldRecord,
    RestoredAdapter,
)
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.control.guard import PublishGuard
from ovenbird.testing import FakeClock
from ovenbird_core import HeishaMonStatus, HeishaSignal, Instant, SignalView, SourceKind
from ovenbird_core.control import (
    CommandIntent,
    HeatingCurve,
    IntentKind,
    Mode,
    ReasonCode,
    SafetyLimits,
)

BASE = "panasonic_heat_pump"
PERMIT = PublishGuard(Mode.AUTO, True, "mosquitto", 1883, frozenset({"mosquitto"}))


def config(**overrides: Any) -> AdapterConfig:
    """Build an adapter config with test defaults, overridable per field."""
    values: dict[str, Any] = {
        "base": BASE,
        "setpoint_register": "setcurves_target_high",
        "setpoint_range": (20, 40),
        "pump_duty_range": (80, 200),
        "min_spacing_s": 7.0,
        "verify_timeout_s": 30.0,
        "max_retries": 2,
        "daily_budget": 50,
        "hold_s": 600.0,
    }
    values.update(overrides)
    return AdapterConfig(**values)


class Pump:
    """Fake heat pump whose signal values, freshness and observation times tests control."""

    def __init__(self, clock: FakeClock) -> None:
        """Start with heating on, no operating mode, 30 degC target and 159 duty."""
        self.clock = clock
        self.values: dict[str, int] = {
            HeishaSignal.HEATING_MODE: 1,
            HeishaSignal.OPERATING_MODE_STATE: 0,
            HeishaSignal.Z1_WATER_TARGET_TEMP: 30,
            HeishaSignal.MAX_PUMP_DUTY: 159,
            HeishaSignal.QUIET_MODE_LEVEL: 0,
        }
        self.observed: dict[str, Instant] = dict.fromkeys(self.values, clock())
        self.stale: set[str] = set()

    def report(self, signal: str, value: int) -> None:
        """Set a signal to a new value observed half a second later."""
        self.clock.advance(0.5)
        self.values[signal] = value
        self.observed[signal] = self.clock()

    def read(self, signal: str) -> SignalView | None:
        """Return the current view of a signal, or None when it is unknown."""
        if signal not in self.values:
            return None
        fresh = signal not in self.stale
        return SignalView(
            signal=signal,
            value=self.values[signal],
            unit=None,
            source=SourceKind.HEISHAMON,
            observed=self.observed[signal],
            age=1.0,
            max_age=330.0,
            fresh=fresh,
            retained=False,
            source_timestamp=None,
        )


class Rig:
    """Command adapter wired to a fake clock, fake pump and alarm board."""

    def __init__(self, guard: PublishGuard = PERMIT, **overrides: Any) -> None:
        """Build the rig with a publish guard and adapter config overrides."""
        self.clock = FakeClock()
        self.pump = Pump(self.clock)
        self.alarms = AlarmBoard()
        self.events: list[CommandEvent] = []
        self.adapter = CommandAdapter(
            config(**overrides), guard, self.alarms, journal=self.events.append
        )

    def submit(self, kind: IntentKind, value: Any) -> tuple[CommandEvent, ...]:
        """Submit one curve-driven intent and return the resulting command events."""
        return self.adapter.submit([CommandIntent(kind, value, ReasonCode.CURVE)], self.clock())

    def tick(self, advance: float = 0.0) -> Any:
        """Advance the clock, tick the adapter and mark any returned command as published."""
        self.clock.advance(advance)
        command = self.adapter.tick(self.clock(), self.pump.read)
        if command is not None:
            self.adapter.published(command, self.clock())
        return command

    def statuses(self) -> list[str]:
        """Return the status values of all journalled command events, in order."""
        return [event.status.value for event in self.events]


def test_allowlist_topics_and_payloads() -> None:
    """The adapter allows exactly six command topics and builds the expected payloads."""
    cfg = config()
    assert cfg.topics() == {
        f"{BASE}/commands/SetCurves",
        f"{BASE}/commands/SetMaxPumpDuty",
        f"{BASE}/commands/SetQuietMode",
        f"{BASE}/commands/SetFloorHeatDelta",
        f"{BASE}/commands/SetPumpFlowrateMode",
        f"{BASE}/commands/SetHeatingOffOutdoorTemp",
    }
    assert len(cfg.topics()) == 6
    assert json.loads(cfg.payload(IntentKind.WATER_SETPOINT, 31)) == {
        "zone1": {"heat": {"target": {"high": 31}}}
    }
    alt = config(setpoint_register="z1_heat_request_temperature")
    assert alt.topic(IntentKind.WATER_SETPOINT) == f"{BASE}/commands/SetZ1HeatRequestTemperature"
    assert alt.payload(IntentKind.WATER_SETPOINT, 31) == "31"
    assert cfg.payload(IntentKind.MAX_PUMP_DUTY, 102) == "102"
    with pytest.raises(ValueError, match="register"):
        config(setpoint_register="SetHeatpump")


@pytest.mark.parametrize(
    ("kind", "value", "sent"),
    [
        (IntentKind.WATER_SETPOINT, 55, 40),
        (IntentKind.WATER_SETPOINT, 5, 20),
        (IntentKind.WATER_SETPOINT, 31, 31),
        (IntentKind.MAX_PUMP_DUTY, 300, 200),
        (IntentKind.MAX_PUMP_DUTY, 10, 80),
        (IntentKind.QUIET_MODE, 9, 3),
        (IntentKind.QUIET_MODE, -1, 0),
    ],
)
def test_integer_clamps(kind: IntentKind, value: int, sent: int) -> None:
    """Integer commands are clamped into their configured range before sending."""
    rig = Rig()
    (event,) = rig.submit(kind, value)
    assert event.status is CommandStatus.QUEUED
    command = rig.tick()
    assert command.value == sent
    assert command.payload.endswith(str(sent)) or str(sent) in command.payload
    assert rig.adapter.counters.clamped == (value != sent)


@pytest.mark.parametrize("value", [31.5, "31", True, None])
def test_non_integers_are_refused(value: Any) -> None:
    """Non-integer values are refused and nothing is sent."""
    rig = Rig()
    (event,) = rig.submit(IntentKind.WATER_SETPOINT, value)
    assert event.status is CommandStatus.REFUSED
    assert rig.tick() is None


def test_refuses_everything_without_the_guard() -> None:
    """A closed publish guard refuses every command with the reason."""
    guard = PublishGuard(Mode.SHADOW, True, "mosquitto", 1883, frozenset({"mosquitto"}))
    rig = Rig(guard)
    (event,) = rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert event.status is CommandStatus.REFUSED
    assert "control mode is shadow" in event.detail
    assert rig.tick() is None
    assert rig.adapter.counters.sent == 0


def test_serial_queue_with_spacing_and_verification() -> None:
    """Commands go out one at a time with minimum spacing, each verified by read-back."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    first = rig.tick()
    assert (first.kind, first.value, first.topic) == (
        IntentKind.WATER_SETPOINT,
        31,
        f"{BASE}/commands/SetCurves",
    )
    assert rig.tick(5.0) is None
    assert rig.adapter.view().in_flight == {IntentKind.WATER_SETPOINT: 31}
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    assert rig.tick(1.0) is None
    assert rig.adapter.view().in_flight == {}
    assert rig.tick(0.0) is None
    second = rig.tick(1.0)
    assert (second.kind, second.value) == (IntentKind.MAX_PUMP_DUTY, 102)
    rig.pump.report(HeishaSignal.MAX_PUMP_DUTY, 102)
    rig.tick(5.0)
    assert rig.statuses() == ["queued", "queued", "sent", "verified", "sent", "verified"]
    assert rig.alarms.active() == ()


def test_newest_value_replaces_a_queued_one() -> None:
    """A newer value replaces a queued one and repeating the same value is ignored."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.submit(IntentKind.WATER_SETPOINT, 32)
    assert rig.submit(IntentKind.WATER_SETPOINT, 32) == ()
    assert rig.tick().value == 32
    assert rig.submit(IntentKind.WATER_SETPOINT, 32) == ()


def test_verification_needs_a_reading_after_the_publish() -> None:
    """A matching value observed before the publish does not verify the command."""
    rig = Rig()
    rig.pump.values[HeishaSignal.Z1_WATER_TARGET_TEMP] = 31
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick()
    rig.tick(10.0)
    assert rig.adapter.view().in_flight == {IntentKind.WATER_SETPOINT: 31}
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    assert rig.adapter.view().in_flight == {}


def test_a_value_already_in_effect_is_verified_when_no_change_follows() -> None:
    """A command whose value already holds is verified at timeout when no change arrives."""
    rig = Rig()
    rig.pump.values[HeishaSignal.Z1_WATER_TARGET_TEMP] = 31
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick()
    rig.tick(29.0)
    assert rig.adapter.view().in_flight == {IntentKind.WATER_SETPOINT: 31}
    rig.tick(1.0)
    assert rig.adapter.view().in_flight == {}
    assert rig.statuses() == ["queued", "sent", "verified"]
    assert "already in effect" in rig.events[-1].detail
    assert rig.alarms.active() == ()


def test_a_stale_matching_value_is_not_verified() -> None:
    """A matching but stale reading does not verify, so the command is retried."""
    rig = Rig()
    rig.pump.values[HeishaSignal.Z1_WATER_TARGET_TEMP] = 31
    rig.pump.stale.add(HeishaSignal.Z1_WATER_TARGET_TEMP)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick()
    rig.tick(30.0)
    assert rig.statuses() == ["queued", "sent", "retry", "sent"]


def test_retries_then_alarm_and_hold() -> None:
    """Unverified commands are retried, then fail with an alarm and a hold that later expires."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick() is not None
    attempts = 1
    for _ in range(2):
        assert rig.tick(29.0) is None
        assert rig.tick(1.0) is not None
        attempts += 1
    assert attempts == 3
    assert rig.tick(30.0) is None
    assert rig.statuses().count("retry") == 2
    assert rig.statuses()[-1] == "failed"
    assert rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)
    assert rig.adapter.hold_reason == "verification failed"
    (refused,) = rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert refused.status is CommandStatus.REFUSED
    assert rig.adapter.view().hold == "verification failed"
    rig.tick(600.0)
    assert rig.adapter.hold_reason is None
    assert rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick() is not None
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    assert not rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)


def test_mode_gating_on_a_fresh_direct_heating_mode() -> None:
    """Writes are dropped with an alarm unless a fresh Heating_Mode shows direct control."""
    rig = Rig()
    rig.pump.report(HeishaSignal.HEATING_MODE, 0)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick() is None
    assert rig.alarms.is_active(AlarmCode.MODE_MISMATCH)
    assert rig.adapter.view().queued == {}
    assert rig.statuses()[-1] == "dropped"
    (refused,) = rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert "Heating_Mode is 0" in refused.detail
    rig.pump.report(HeishaSignal.HEATING_MODE, 1)
    rig.pump.stale.add(HeishaSignal.HEATING_MODE)
    rig.tick(1.0)
    assert rig.alarms.is_active(AlarmCode.MODE_MISMATCH)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick(1.0) is None
    rig.pump.stale.clear()
    assert rig.tick(1.0) is None
    assert not rig.alarms.is_active(AlarmCode.MODE_MISMATCH)
    assert rig.adapter.hold_reason is None
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick(1.0) is not None


def test_operating_mode_must_be_heat() -> None:
    """A non-heating operating mode blocks writes and is named in the alarm."""
    rig = Rig()
    rig.pump.report(HeishaSignal.OPERATING_MODE_STATE, 3)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick() is None
    assert "Operating_Mode_State is 3" in rig.alarms.active()[0].message


def test_daily_budget_alarm_and_reset() -> None:
    """Exhausting the daily write budget raises an alarm and the budget resets after a day."""
    rig = Rig(daily_budget=2, min_spacing_s=1.0, verify_timeout_s=5.0, max_retries=0)
    for value in (31, 32):
        rig.submit(IntentKind.WATER_SETPOINT, value)
        assert rig.tick(2.0) is not None
        rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, value)
        rig.tick(1.0)
    rig.submit(IntentKind.WATER_SETPOINT, 33)
    assert rig.tick(2.0) is None
    assert rig.alarms.is_active(AlarmCode.WRITE_BUDGET)
    assert rig.adapter.status()["budget"]["used"] == 2
    assert rig.adapter.view().queued == {IntentKind.WATER_SETPOINT: 33}
    assert rig.tick(86_400.0).value == 33
    assert not rig.alarms.is_active(AlarmCode.WRITE_BUDGET)
    assert rig.adapter.status()["budget"]["used"] == 1


def test_foreign_writer_is_detected_by_read_back() -> None:
    """A changed read-back after a verified write raises a foreign-writer alarm and hold."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick()
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(5.0)
    rig.tick(60.0)
    assert rig.alarms.active() == ()
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 34)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    assert rig.tick(5.0) is None
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    alarm = rig.alarms.active()[0]
    assert "changed to 34 after ovenbird set 31" in alarm.message
    assert alarm.detail["register"] == "setcurves_target_high"
    assert alarm.detail["signal"] == "main/Z1_Water_Target_Temp"
    assert alarm.detail["ovenbird_value"] == 31
    assert alarm.detail["seen_value"] == 34
    assert alarm.detail["seen_since"] is not None
    assert alarm.detail["at_hold_end"] == "write_again"
    assert alarm.detail["hold_until"] is not None
    assert alarm.to_json()["detail"] == alarm.detail
    assert rig.adapter.hold_reason == "foreign writer"
    assert rig.adapter.view().queued == {}
    assert rig.adapter.counters.foreign == 1


def test_publish_failure_requeues_the_command() -> None:
    """A failed publish puts the command back on the queue to be sent again."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    command = rig.adapter.tick(rig.clock(), rig.pump.read)
    assert command is not None
    rig.adapter.publish_failed(command, rig.clock(), "MqttError")
    assert rig.adapter.view().queued == {IntentKind.WATER_SETPOINT: 31}
    assert rig.tick(7.0) == command


def test_status_shape() -> None:
    """The status report exposes the in-flight command, register, counters and budget."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick()
    status = rig.adapter.status()
    assert status["in_flight"]["value"] == 31
    assert status["setpoint_register"] == "setcurves_target_high"
    assert status["counters"]["sent"] == 1
    assert status["budget"]["limit"] == 50


SAFETY = "safety_correction"


def own(rig: Rig, value: int = 31) -> None:
    """Send a setpoint and verify it so the adapter knows ovenbird's own value."""
    rig.submit(IntentKind.WATER_SETPOINT, value)
    rig.tick(7.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, value)
    rig.tick(1.0)
    assert rig.adapter.status()["verified"]["water_setpoint"] == value


def board(*, alive: bool = True, uptime: float = 1000.0, version: str = "3.9") -> HeishaMonStatus:
    """Build a HeishaMon board status with the given liveness, uptime and version."""
    return HeishaMonStatus(
        alive=alive,
        heartbeat_age=1.0,
        lwt_online=True,
        version=version,
        uptime_s=uptime,
        window_s=30.0,
    )


def test_wrapped_setpoint_is_corrected_even_during_a_foreign_writer_hold() -> None:
    """A target above the safety maximum is corrected even during a foreign-writer hold."""
    rig = Rig()
    own(rig)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    command = rig.tick(8.0)
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.adapter.hold_reason == "foreign writer"
    assert command is not None
    assert (command.reason, command.value) == (SAFETY, 31)
    assert rig.adapter.status()["in_flight"]["corrective"] is True
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    assert rig.tick(1.0) is None
    assert rig.statuses()[-1] == "verified"
    assert "safety correction applied" in rig.events[-1].detail
    assert rig.adapter.hold_reason == "foreign writer"
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.adapter.counters.corrections == 1


def test_correction_prefers_the_controllers_current_intent() -> None:
    """The safety correction uses the controller's clamped current intent."""
    rig = Rig()
    rig.adapter.reconcile(
        [CommandIntent(IntentKind.WATER_SETPOINT, 55, ReasonCode.CURVE)], rig.clock()
    )
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    command = rig.tick()
    assert command is not None
    assert (command.reason, command.value) == (SAFETY, 40)


def test_correction_without_any_history_uses_the_safety_minimum() -> None:
    """With no known value the correction falls back to the lowest allowed setpoint."""
    rig = Rig()
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    command = rig.tick()
    assert command is not None
    assert command.value == 20


def test_no_correction_in_compensation_mode() -> None:
    """No safety correction is written while the pump is in compensation heating mode."""
    rig = Rig()
    rig.pump.report(HeishaSignal.HEATING_MODE, 0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    assert rig.tick() is None
    assert rig.alarms.is_active(AlarmCode.MODE_MISMATCH)
    assert rig.adapter.counters.corrections == 0


def test_no_correction_while_the_guard_refuses() -> None:
    """No safety correction is written while the publish guard is closed."""
    rig = Rig(guard=PublishGuard(Mode.SHADOW, True, "mosquitto", 1883, frozenset({"mosquitto"})))
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    assert rig.tick() is None


def test_corrections_are_limited_then_correction_failed_holds() -> None:
    """Safety corrections are capped, then a correction-failed alarm holds writes."""
    rig = Rig()
    own(rig)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    sent = []
    for _ in range(12):
        command = rig.tick(10.0)
        if command is not None:
            sent.append(command)
    assert [c.reason for c in sent] == [SAFETY] * 3
    assert rig.alarms.is_active(AlarmCode.CORRECTION_FAILED)
    assert "after 3 safety corrections" in rig.alarms.active()[-1].message
    assert AlarmCode.CORRECTION_FAILED in rig.adapter.safety_hold
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    assert not rig.alarms.is_active(AlarmCode.CORRECTION_FAILED)


def test_the_correction_limit_holds_until_its_window_slides() -> None:
    """After the correction limit the hold lasts until the oldest correction leaves the window."""
    rig = Rig(max_corrections=2, correction_window_s=600.0)
    own(rig)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    sent: list[float] = []
    for _ in range(60):
        command = rig.tick(10.0)
        if command is not None and command.reason == SAFETY:
            sent.append(rig.clock().monotonic)
    assert len(sent) == 2
    alarm = rig.alarms.get(AlarmCode.CORRECTION_FAILED)
    assert alarm is not None
    assert "after 2 safety corrections within 10 min; holding" in alarm.message
    assert AlarmCode.CORRECTION_FAILED in rig.adapter.safety_hold
    assert rig.adapter.status()["safety_hold"] == [AlarmCode.CORRECTION_FAILED.value]
    while rig.clock().monotonic < sent[0] + 600.0:
        command = rig.tick(10.0)
        assert command is None or command.reason != SAFETY
    third = rig.tick(10.0)
    assert third is not None
    assert (third.reason, third.value) == (SAFETY, 31)
    assert rig.adapter.counters.corrections == 3
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    assert not rig.alarms.is_active(AlarmCode.CORRECTION_FAILED)
    assert AlarmCode.CORRECTION_FAILED not in rig.adapter.safety_hold


def test_a_failing_listener_is_logged_and_the_others_still_hear(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A listener that raises is logged and does not stop other listeners."""
    rig = Rig()
    heard: list[CommandEvent] = []

    def broken(event: CommandEvent) -> None:
        """Listener that always raises."""
        raise RuntimeError("listener broke")

    rig.adapter.listeners.extend([broken, heard.append])
    with caplog.at_level(logging.ERROR, logger="ovenbird.control.adapter"):
        events = rig.submit(IntentKind.WATER_SETPOINT, 31)
        command = rig.tick(7.0)
    assert command is not None
    assert [e.status.value for e in heard] == ["queued", "sent"]
    assert heard == rig.events
    assert events == (rig.events[0],)
    failures = [r for r in caplog.records if r.getMessage() == "command event listener failed"]
    assert len(failures) == 2
    assert all(r.exc_info is not None for r in failures)


def test_correction_may_use_the_safety_reserve_beyond_the_budget() -> None:
    """Safety corrections may exceed the daily write budget."""
    rig = Rig(daily_budget=1)
    own(rig)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    assert rig.tick(8.0) is None
    assert rig.alarms.is_active(AlarmCode.WRITE_BUDGET)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    command = rig.tick(8.0)
    assert command is not None
    assert command.reason == SAFETY


def test_safety_hold_releases_only_setpoint_decreases() -> None:
    """While a safety hold is active only setpoint decreases are released."""
    rig = Rig()
    rig.adapter.safety_update(
        frozenset({AlarmCode.LOW_FLOW, AlarmCode.SETPOINT_ABOVE_MAX}), rig.clock()
    )
    assert rig.adapter.safety_hold == {AlarmCode.LOW_FLOW}
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    rig.submit(IntentKind.WATER_SETPOINT, 33)
    assert rig.tick() is None
    rig.submit(IntentKind.WATER_SETPOINT, 28)
    command = rig.tick(1.0)
    assert command is not None
    assert (command.kind, command.value) == (IntentKind.WATER_SETPOINT, 28)
    assert rig.adapter.view().queued == {IntentKind.MAX_PUMP_DUTY: 102}
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 28)
    rig.tick(1.0)
    rig.adapter.safety_update(frozenset(), rig.clock())
    command = rig.tick(8.0)
    assert command is not None
    assert command.kind is IntentKind.MAX_PUMP_DUTY


def foreign_incident(rig: Rig, value: int) -> None:
    """Adopt the current setpoint, then simulate a foreign write of the given value and tick."""
    rig.adapter.adopt(
        IntentKind.WATER_SETPOINT, rig.pump.values[HeishaSignal.Z1_WATER_TARGET_TEMP], rig.clock()
    )
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, value)
    rig.tick(1.0)
    assert rig.adapter.hold is not None


def test_repeated_holds_escalate_then_latch_until_released() -> None:
    """Repeated foreign writes lengthen the hold, then latch it until an operator releases it."""
    rig = Rig(hold_s=600.0, escalation_factor=4.0, latch_after=3)
    own(rig)
    foreign_incident(rig, 33)
    first = rig.adapter.hold
    assert first is not None
    assert (first.incident, first.latched) == (1, False)
    assert first.until is not None
    assert (first.until - rig.clock().wall).total_seconds() == pytest.approx(600.0)
    status = rig.adapter.status(rig.clock())
    assert status["hold_until"].endswith("Z")
    assert status["hold_incidents"] == 1
    rig.tick(600.0)
    assert rig.adapter.hold is None
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    foreign_incident(rig, 34)
    second = rig.adapter.hold
    assert second is not None
    assert second.until is not None
    assert (second.until - rig.clock().wall).total_seconds() == pytest.approx(2400.0)
    rig.tick(2400.0)
    assert rig.adapter.hold is None
    foreign_incident(rig, 35)
    third = rig.adapter.hold
    assert third is not None
    assert third.latched
    assert third.until is None
    assert rig.alarms.is_active(AlarmCode.HOLD_LATCHED)
    rig.tick(86_400.0 * 3)
    assert rig.adapter.hold_reason == "foreign writer"
    assert rig.adapter.status()["hold_latched"] is True
    released = rig.adapter.release_hold(rig.clock(), "admin")
    assert released == third
    assert rig.adapter.hold_reason is None
    assert not rig.alarms.is_active(AlarmCode.HOLD_LATCHED)
    assert rig.adapter.release_hold(rig.clock(), "admin") is None
    foreign_incident(rig, 36)
    again = rig.adapter.hold
    assert again is not None
    assert again.incident == 1
    hold_events = [e for e in rig.alarms.history if e.code == "command_hold"]
    assert [e.event.value for e in hold_events] == [
        "started",
        "expired",
        "started",
        "expired",
        "started",
        "released",
        "started",
    ]


def test_old_incidents_fall_out_of_the_window() -> None:
    """Incidents older than the escalation window do not count towards escalation."""
    rig = Rig(hold_s=600.0, escalation_window_s=3600.0)
    own(rig)
    foreign_incident(rig, 33)
    rig.tick(7200.0)
    foreign_incident(rig, 34)
    hold = rig.adapter.hold
    assert hold is not None
    assert hold.incident == 1


def test_foreign_writer_alarm_clears_once_ovenbirds_value_is_back() -> None:
    """The foreign-writer alarm clears once ovenbird's value is adopted after the hold."""
    rig = Rig(hold_s=600.0)
    own(rig)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 33)
    rig.tick(1.0)
    rig.adapter.adopt(IntentKind.WATER_SETPOINT, 33, rig.clock())
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    rig.tick(600.0)
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    rig.adapter.adopt(IntentKind.WATER_SETPOINT, 33, rig.clock())
    assert not rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.adapter.status()["verified"]["water_setpoint"] == 33
    cleared = [e for e in rig.alarms.history if e.code == "foreign_writer"]
    assert [e.event.value for e in cleared] == ["raised", "cleared"]


def test_reconcile_drops_values_the_controller_no_longer_wants() -> None:
    """Reconcile drops queued values the controller changed or stopped asking for."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    now = rig.clock()
    events = rig.adapter.reconcile(
        [CommandIntent(IntentKind.WATER_SETPOINT, 30, ReasonCode.CURVE)], now
    )
    assert [(e.kind, e.status) for e in events] == [
        (IntentKind.WATER_SETPOINT, CommandStatus.DROPPED),
        (IntentKind.MAX_PUMP_DUTY, CommandStatus.DROPPED),
    ]
    assert "now wants 30" in events[0].detail
    assert "no longer asks" in events[1].detail
    assert rig.adapter.view().queued == {}
    assert rig.adapter.counters.superseded == 2
    rig.submit(IntentKind.WATER_SETPOINT, 32)
    assert (
        rig.adapter.reconcile([CommandIntent(IntentKind.WATER_SETPOINT, 32, ReasonCode.CURVE)], now)
        == ()
    )


def test_heishamon_restart_is_not_a_foreign_writer() -> None:
    """A HeishaMon restart raises a restart alarm and resets state, not a foreign-writer hold."""
    rig = Rig()
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.adapter.tick(rig.clock(), rig.pump.read, board())
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.clock.advance(1.0)
    rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=1001.0))
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 30)
    rig.clock.advance(1.0)
    rig.adapter.tick(rig.clock(), rig.pump.read, board(alive=False, uptime=1001.0))
    assert rig.alarms.active() == ()
    rig.clock.advance(60.0)
    rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=3.0))
    assert not rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.alarms.is_active(AlarmCode.HEISHAMON_RESTARTED)
    assert rig.adapter.hold is None
    assert rig.adapter.counters.restarts == 1
    assert rig.adapter.status()["verified"] == {}
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.clock.advance(8.0)
    assert rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=11.0)) is not None


def test_a_mismatch_long_after_a_restart_is_foreign() -> None:
    """A mismatch after the restart grace period counts as a foreign writer."""
    rig = Rig(restart_grace_s=60.0)
    own(rig)
    rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=1000.0))
    rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=2.0))
    rig.clock.advance(120.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 34)
    rig.adapter.tick(rig.clock(), rig.pump.read, board(uptime=122.0))
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)


def test_simulation_mode_needs_a_simulated_board() -> None:
    """With simulation required, writes are held unless the board reports a simulator version."""
    rig = Rig(require_simulated_board=True)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.adapter.tick(rig.clock(), rig.pump.read, board(version="3.9")) is None
    assert rig.adapter.hold_reason is not None
    assert "not a simulator" in rig.adapter.hold_reason
    assert rig.adapter.view().queued == {}
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 44)
    assert rig.adapter.tick(rig.clock(), rig.pump.read, None) is None
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 30)
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.adapter.tick(rig.clock(), rig.pump.read, board(version="3.9-sim")) is None
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.adapter.tick(rig.clock(), rig.pump.read, board(version="3.9-sim")) is not None


def test_restore_budget_and_latched_hold() -> None:
    """Restoring state brings back the day's used budget and a latched hold."""
    rig = Rig(daily_budget=3)
    now = rig.clock()
    latched = HoldRecord("foreign writer", None, True, 3)
    rig.adapter.restore(
        RestoredAdapter(
            day=now.wall.date(), sent_today=2, incidents=(now.wall.timestamp() - 60,), hold=latched
        ),
        now,
    )
    assert rig.adapter.hold == latched
    assert rig.alarms.is_active(AlarmCode.HOLD_LATCHED)
    assert rig.adapter.status()["budget"]["used"] == 2
    rig.adapter.release_hold(rig.clock(), "admin")
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick() is not None
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    assert rig.tick(31.0) is None
    assert rig.alarms.is_active(AlarmCode.WRITE_BUDGET)


def test_restore_timed_hold_and_ignore_an_expired_one() -> None:
    """A restored timed hold runs to its end; expired holds and stale budgets are ignored."""
    rig = Rig()
    now = rig.clock()
    until = now.wall + timedelta(seconds=300)
    rig.adapter.restore(
        RestoredAdapter(hold=HoldRecord("verification failed", until, False, 1)), now
    )
    assert rig.adapter.hold_reason == "verification failed"
    assert rig.adapter.status()["hold_until"] == iso_z(until)
    rig.tick(301.0)
    assert rig.adapter.hold is None
    other = Rig()
    past = other.clock().wall - timedelta(seconds=1)
    other.adapter.restore(RestoredAdapter(hold=HoldRecord("x", past, False, 1)), other.clock())
    assert other.adapter.hold is None
    stale_day = Rig()
    stale_day.adapter.restore(
        RestoredAdapter(day=date(2000, 1, 1), sent_today=99), stale_day.clock()
    )
    assert stale_day.adapter.status()["budget"]["used"] == 0


def test_a_mode_change_is_not_a_foreign_writer() -> None:
    """A target change caused by a heating mode change raises a mode alarm only."""
    rig = Rig()
    own(rig)
    rig.pump.report(HeishaSignal.HEATING_MODE, 0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 33)
    rig.tick(1.0)
    assert rig.alarms.is_active(AlarmCode.MODE_MISMATCH)
    assert not rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    rig.pump.report(HeishaSignal.HEATING_MODE, 1)
    rig.tick(1.0)
    assert not rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.adapter.hold is None
    assert rig.adapter.status()["verified"] == {}


def test_queued_pump_duty_is_dropped_during_a_defrost() -> None:
    """Pump duty commands are dropped during a defrost and accepted afterwards."""
    rig = Rig()
    rig.pump.values[HeishaSignal.DEFROSTING_STATE] = 1
    rig.pump.observed[HeishaSignal.DEFROSTING_STATE] = rig.clock()
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    assert rig.tick() is None
    dropped = rig.events[-1]
    assert dropped.status is CommandStatus.DROPPED
    assert dropped.detail == "defrost: the pump sets its own duty; not sent"
    assert rig.adapter.view().queued == {}
    rig.pump.report(HeishaSignal.DEFROSTING_STATE, 0)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    command = rig.tick(1.0)
    assert command is not None
    assert command.value == 102


def test_setpoint_is_released_during_a_defrost() -> None:
    """Setpoint commands are still sent during a defrost."""
    rig = Rig()
    rig.pump.values[HeishaSignal.DEFROSTING_STATE] = 1
    rig.pump.observed[HeishaSignal.DEFROSTING_STATE] = rig.clock()
    rig.submit(IntentKind.WATER_SETPOINT, 33)
    command = rig.tick()
    assert command is not None
    assert command.kind is IntentKind.WATER_SETPOINT


def test_foreign_writer_alarm_waits_for_the_overwritten_setting() -> None:
    """The foreign-writer alarm persists until the overwritten setting itself is adopted."""
    rig = Rig(hold_s=600.0)
    own(rig)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 33)
    rig.tick(1.0)
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    rig.tick(600.0)
    rig.submit(IntentKind.MAX_PUMP_DUTY, 102)
    command = rig.tick(10.0)
    assert command is not None
    assert command.kind is IntentKind.MAX_PUMP_DUTY
    rig.pump.report(HeishaSignal.MAX_PUMP_DUTY, 102)
    rig.tick(1.0)
    assert rig.adapter.status()["verified"]["max_pump_duty"] == 102
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    rig.adapter.adopt(IntentKind.WATER_SETPOINT, 33, rig.clock())
    assert not rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)


ENVELOPE = SafetyLimits(max_supply_c=40.0, envelope=HeatingCurve.of((0, 34), (10, 29)))


def envelope_rig(*, declared: bool = True, outside: int = 0, own: int = 38) -> Rig:
    """Build a rig with a verified setpoint, with or without the envelope rule declared."""
    rig = Rig(envelope_rule=ENVELOPE if declared else None)
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, outside)
    rig.submit(IntentKind.WATER_SETPOINT, own)
    rig.tick()
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, own)
    rig.tick(5.0)
    assert rig.adapter.status()["verified"] == {"water_setpoint": own}
    return rig


def journalled(rig: Rig, code: str) -> list[Any]:
    """Return the journalled alarm events with the given code."""
    return [event for event in rig.alarms.history if event.code == code]


def test_the_envelope_rule_correcting_ovenbirds_value_is_adopted_without_a_hold() -> None:
    """A pump-side envelope correction of ovenbird's value is adopted and counted without a hold."""
    rig = envelope_rig()
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, 10)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 29)
    assert rig.tick(5.0) is None
    assert rig.adapter.hold_reason is None
    assert rig.alarms.active() == ()
    assert rig.adapter.counters.foreign == 0
    assert rig.adapter.counters.envelope_corrections == 1
    assert rig.adapter.status()["counters"]["envelope_corrections"] == 1
    assert rig.adapter.status()["verified"] == {"water_setpoint": 29}
    (event,) = journalled(rig, "envelope_correction")
    assert event.severity.value == "info"
    assert event.event.value == "recognised"
    assert event.detail["ovenbird_value"] == 38
    assert event.detail["seen_value"] == 29
    assert event.detail["outside_c"] == 10.0
    assert event.detail["set_outside_band"] is False
    rig.tick(60.0)
    assert rig.adapter.counters.envelope_corrections == 1
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    assert rig.tick(10.0).value == 31


def test_the_rules_rounding_is_accepted() -> None:
    """Either rounding of the envelope rule's fallback value is recognised."""
    rig = envelope_rig()
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, 9)
    assert ENVELOPE.fallback_values(9) == {29, 30}
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 30)
    rig.tick(5.0)
    assert rig.adapter.hold_reason is None
    assert rig.adapter.counters.envelope_corrections == 1


@pytest.mark.parametrize(
    ("own", "seen"),
    [(30, 32), (30, 29), (38, 31)],
    ids=["inside-the-band", "own-value-inside-the-band", "not-the-rules-value"],
)
def test_a_write_the_rule_does_not_explain_is_a_foreign_writer(own: int, seen: int) -> None:
    """A change that the envelope rule cannot explain is treated as a foreign writer."""
    rig = envelope_rig(own=own)
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, 10)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, seen)
    rig.tick(5.0)
    assert rig.adapter.hold_reason == "foreign writer"
    assert rig.alarms.is_active(AlarmCode.FOREIGN_WRITER)
    assert rig.adapter.counters.envelope_corrections == 0
    assert journalled(rig, "envelope_correction") == []


def test_a_rule_correction_is_a_foreign_writer_when_the_rule_is_not_declared() -> None:
    """Without the rule declared an envelope-like change is a foreign writer."""
    rig = envelope_rig(declared=False)
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, 10)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 29)
    rig.tick(5.0)
    assert rig.adapter.hold_reason == "foreign writer"
    assert rig.adapter.counters.envelope_corrections == 0
    rig.adapter.release_hold(rig.clock(), "test")
    rig.submit(IntentKind.WATER_SETPOINT, 38)
    assert rig.tick(10.0).value == 38


def test_a_rule_correction_is_a_foreign_writer_without_a_fresh_outside_temperature() -> None:
    """Without a fresh outside temperature an envelope-like change is a foreign writer."""
    rig = envelope_rig()
    rig.pump.report(HeishaSignal.OUTSIDE_TEMP, 10)
    rig.pump.stale.add(HeishaSignal.OUTSIDE_TEMP)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 29)
    rig.tick(5.0)
    assert rig.adapter.hold_reason == "foreign writer"


def test_an_own_value_outside_the_envelope_raises_envelope_mismatch_once() -> None:
    """An own value outside the envelope raises one mismatch alarm until a valid value is set."""
    rig = envelope_rig(outside=10, own=30)
    rig.adapter.adopt(IntentKind.WATER_SETPOINT, 38, rig.clock())
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 38)
    rig.tick(5.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 29)
    rig.tick(5.0)
    assert rig.adapter.hold_reason is None
    assert rig.adapter.counters.envelope_corrections == 1
    alarm = rig.alarms.get(AlarmCode.ENVELOPE_MISMATCH)
    assert alarm is not None
    assert alarm.severity.value == "warning"
    assert alarm.detail["set_outside_band"] is True
    rig.adapter.adopt(IntentKind.WATER_SETPOINT, 38, rig.clock())
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 38)
    rig.tick(5.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 29)
    rig.tick(5.0)
    assert rig.adapter.counters.envelope_corrections == 2
    raised = [e for e in rig.alarms.history if e.code == "envelope_mismatch"]
    assert [e.event.value for e in raised] == ["raised"]
    rig.submit(IntentKind.WATER_SETPOINT, 31)
    rig.tick(10.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(5.0)
    assert not rig.alarms.is_active(AlarmCode.ENVELOPE_MISMATCH)


def test_the_rule_is_declared_through_the_settings(make_settings: Any) -> None:
    """The envelope rule is only active when the settings declare it installed."""
    declared = AdapterConfig.from_settings(make_settings(envelope_rule_installed=True), ENVELOPE)
    assert declared.envelope_rule is ENVELOPE
    assert AdapterConfig.from_settings(make_settings(), ENVELOPE).envelope_rule is None
