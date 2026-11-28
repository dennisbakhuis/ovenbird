"""The operator's pump settings in the command adapter: the second closed allowlist."""

from __future__ import annotations

from typing import Any

import pytest

from ovenbird.control.adapter import (
    AdapterConfig,
    CommandAdapter,
    CommandEvent,
    CommandStatus,
    RestoredAdapter,
    SettingRefusedError,
)
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.control.guard import ModeHold, PublishGuard
from ovenbird.testing import FakeClock
from ovenbird_core import PUMP_SETTINGS, HeishaSignal, Instant, PumpSetting, SignalView, SourceKind
from ovenbird_core.control import CommandIntent, IntentKind, Mode, ReasonCode

BASE = "panasonic_heat_pump"
ACTOR = "admin from 192.168.1.20"


def guard(mode: Mode = Mode.AUTO, hold: ModeHold | None = None) -> PublishGuard:
    """Build a publish guard in the given mode and hold that permits publishing."""
    return PublishGuard(
        mode, True, "mosquitto", 1883, frozenset({"mosquitto"}), hold=hold or ModeHold()
    )


class Pump:
    """Fake heat pump holding reported setting values with observation times."""

    def __init__(self, clock: FakeClock) -> None:
        """Start with healthy default values, all observed now and none stale."""
        self.clock = clock
        self.values: dict[str, int] = {
            HeishaSignal.HEATING_MODE: 1,
            HeishaSignal.OPERATING_MODE_STATE: 0,
            HeishaSignal.Z1_WATER_TARGET_TEMP: 30,
            HeishaSignal.MAX_PUMP_DUTY: 159,
            HeishaSignal.QUIET_MODE_LEVEL: 0,
            HeishaSignal.DEFROSTING_STATE: 0,
            HeishaSignal.THREEWAY_VALVE_STATE: 0,
            HeishaSignal.HEAT_DELTA: 5,
            HeishaSignal.PUMP_FLOWRATE_MODE: 0,
            HeishaSignal.HEATING_OFF_OUTDOOR_TEMP: 18,
        }
        self.observed: dict[str, Instant] = dict.fromkeys(self.values, clock())
        self.stale: set[str] = set()

    def report(self, signal: str, value: int) -> None:
        """Report a new value for the signal half a second later."""
        self.clock.advance(0.5)
        self.values[signal] = value
        self.observed[signal] = self.clock()

    def read(self, signal: str) -> SignalView | None:
        """Return a view of the signal, stale if marked so, or None if unreported."""
        if signal not in self.values:
            return None
        return SignalView(
            signal=signal,
            value=self.values[signal],
            unit=None,
            source=SourceKind.HEISHAMON,
            observed=self.observed[signal],
            age=1.0,
            max_age=330.0,
            fresh=signal not in self.stale,
            retained=False,
            source_timestamp=None,
        )


class Rig:
    """Command adapter on a fake pump, clock and alarm board with a journal of events."""

    def __init__(self, publish: PublishGuard | None = None, **overrides: Any) -> None:
        """Build the adapter with test limits, overriding the config values given."""
        values: dict[str, Any] = {
            "base": BASE,
            "setpoint_register": "setcurves_target_high",
            "setpoint_range": (20, 40),
            "pump_duty_range": (80, 200),
            "max_retries": 2,
            "daily_budget": 50,
            "hold_s": 600.0,
        }
        values.update(overrides)
        self.clock = FakeClock()
        self.pump = Pump(self.clock)
        self.alarms = AlarmBoard()
        self.events: list[CommandEvent] = []
        self.adapter = CommandAdapter(
            AdapterConfig(**values),
            publish or guard(),
            self.alarms,
            journal=self.events.append,
        )

    def request(
        self, setting: PumpSetting, value: Any, expect: Any = None, actor: str = ACTOR
    ) -> CommandEvent:
        """Request an operator write, defaulting the expected value to the reported one."""
        current = self.pump.values.get(PUMP_SETTINGS[setting].signal)
        return self.adapter.request_setting(
            setting,
            value,
            current if expect is None else expect,
            actor,
            self.clock(),
            self.pump.read,
        )

    def tick(self, advance: float = 0.0) -> Any:
        """Advance the clock, tick the adapter and mark any command as published."""
        self.clock.advance(advance)
        command = self.adapter.tick(self.clock(), self.pump.read)
        if command is not None:
            self.adapter.published(command, self.clock())
        return command

    def refusal(self, setting: PumpSetting, value: Any, expect: Any = None) -> SettingRefusedError:
        """Request a write that must be refused and return the refusal."""
        with pytest.raises(SettingRefusedError) as caught:
            self.request(setting, value, expect)
        return caught.value


def test_the_second_allowlist_is_exactly_three_settings() -> None:
    """The operator allowlist holds three settings with their topics, clamp ranges and payloads."""
    config = AdapterConfig(BASE, "setcurves_target_high", (20, 40), (80, 200))
    assert config.setting_topics() == {
        f"{BASE}/commands/SetFloorHeatDelta",
        f"{BASE}/commands/SetPumpFlowrateMode",
        f"{BASE}/commands/SetHeatingOffOutdoorTemp",
    }
    assert len(config.topics()) == 6
    assert config.clamp_range(PumpSetting.HEAT_DELTA) == (3, 10)
    assert config.clamp_range(PumpSetting.PUMP_FLOWRATE_MODE) == (0, 1)
    assert config.clamp_range(PumpSetting.HEATING_OFF_OUTDOOR) == (10, 35)
    assert config.payload(PumpSetting.HEAT_DELTA, 4) == "4"


@pytest.mark.parametrize("setting", list(PumpSetting))
def test_each_setting_is_written_and_verified(setting: PumpSetting) -> None:
    """Each setting is queued, sent and verified, journalled and counted against the budget."""
    rig = Rig()
    spec = PUMP_SETTINGS[setting]
    current = rig.pump.values[spec.signal]
    value = spec.high if current != spec.high else spec.low
    queued = rig.request(setting, value)
    assert queued.status is CommandStatus.QUEUED
    assert queued.detail.startswith(f"operator: {ACTOR}: ")
    command = rig.tick()
    assert command.kind is setting
    assert command.topic == f"{BASE}/commands/{spec.command}"
    assert command.payload == str(value)
    rig.pump.report(spec.signal, value)
    rig.tick(1.0)
    statuses = [event.status for event in rig.events]
    assert statuses == [CommandStatus.QUEUED, CommandStatus.SENT, CommandStatus.VERIFIED]
    assert all(event.detail.startswith(f"operator: {ACTOR}") for event in rig.events)
    write = rig.adapter.operator_writes[setting]
    assert (write.from_value, write.to, write.status) == (current, value, CommandStatus.VERIFIED)
    assert write.to_json()["by"] == ACTOR
    assert rig.adapter.status()["budget"]["used"] == 1
    assert rig.alarms.active() == ()


@pytest.mark.parametrize(
    ("setting", "value", "code"),
    [
        (PumpSetting.HEAT_DELTA, 2, "out_of_range"),
        (PumpSetting.HEAT_DELTA, 11, "out_of_range"),
        (PumpSetting.HEAT_DELTA, 4.0, "not_an_integer"),
        (PumpSetting.HEAT_DELTA, "4", "not_an_integer"),
        (PumpSetting.HEAT_DELTA, True, "not_an_integer"),
        (PumpSetting.PUMP_FLOWRATE_MODE, 2, "out_of_range"),
        (PumpSetting.PUMP_FLOWRATE_MODE, -1, "out_of_range"),
        (PumpSetting.HEATING_OFF_OUTDOOR, 9, "out_of_range"),
        (PumpSetting.HEATING_OFF_OUTDOOR, 36, "out_of_range"),
    ],
)
def test_values_are_refused_not_clamped(setting: PumpSetting, value: Any, code: str) -> None:
    """Out-of-range and non-integer values are refused with 422 instead of clamped."""
    rig = Rig()
    refused = rig.refusal(setting, value)
    assert (refused.status, refused.code) == (422, code)
    assert rig.events == []
    assert rig.tick() is None


def test_compare_and_set_on_the_reported_value() -> None:
    """A write needs the expected value to match the reported fresh value and to change it."""
    rig = Rig()
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 4, expect=6)
    assert (refused.status, refused.code, refused.params) == (409, "value_changed", {"reported": 5})
    assert rig.refusal(PumpSetting.HEAT_DELTA, 5).code == "unchanged"
    assert rig.refusal(PumpSetting.HEAT_DELTA, 4, expect="5").code == "expect_required"
    rig.pump.stale.add(HeishaSignal.HEAT_DELTA)
    assert rig.refusal(PumpSetting.HEAT_DELTA, 4).code == "not_fresh"
    del rig.pump.values[HeishaSignal.PUMP_FLOWRATE_MODE]
    refused = rig.refusal(PumpSetting.PUMP_FLOWRATE_MODE, 1, expect=0)
    assert (refused.status, refused.code) == (409, "not_fresh")


@pytest.mark.parametrize(
    ("signal", "code"),
    [(HeishaSignal.DEFROSTING_STATE, "defrost"), (HeishaSignal.THREEWAY_VALVE_STATE, "dhw")],
)
def test_refused_during_a_defrost_or_a_dhw_run(signal: str, code: str) -> None:
    """Writes are refused during a defrost or a hot-water run, or when that state is unknown."""
    rig = Rig()
    rig.pump.report(signal, 1)
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 4)
    assert (refused.status, refused.code) == (409, code)
    rig.pump.stale.add(signal)
    assert rig.refusal(PumpSetting.HEAT_DELTA, 4).code == "state_unknown"


def test_a_queued_write_is_dropped_when_a_defrost_starts() -> None:
    """A queued write is dropped when a defrost starts before it is sent."""
    rig = Rig()
    rig.request(PumpSetting.HEAT_DELTA, 4)
    rig.pump.report(HeishaSignal.DEFROSTING_STATE, 1)
    assert rig.tick() is None
    assert rig.events[-1].status is CommandStatus.DROPPED
    assert "defrost" in rig.events[-1].detail
    assert rig.adapter.operator_writes[PumpSetting.HEAT_DELTA].status is CommandStatus.DROPPED


@pytest.mark.parametrize(
    "publish",
    [guard(Mode.SHADOW), guard(Mode.AUTO, ModeHold(paused=True))],
    ids=["shadow", "paused"],
)
def test_refused_in_shadow(publish: PublishGuard) -> None:
    """Writes are refused with 409 when the guard is in shadow mode or paused."""
    rig = Rig(publish)
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 4)
    assert (refused.status, refused.code) == (409, "not_publishing")


def test_refused_during_a_hold_and_a_safety_hold() -> None:
    """Writes are refused during a foreign-writer hold and a safety hold."""
    rig = Rig()
    rig.adapter.submit(
        [CommandIntent(IntentKind.WATER_SETPOINT, 31, ReasonCode.CURVE)], rig.clock()
    )
    rig.tick()
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 35)
    rig.tick(1.0)
    assert rig.adapter.hold_reason == "foreign writer"
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 4)
    assert (refused.status, refused.code) == (409, "hold")
    other = Rig()
    other.adapter.safety_update(frozenset({AlarmCode.LOW_FLOW}), other.clock())
    assert other.refusal(PumpSetting.HEAT_DELTA, 4).code == "hold"


def test_one_write_at_a_time() -> None:
    """A second write is refused while one is queued or in flight."""
    rig = Rig()
    rig.request(PumpSetting.HEAT_DELTA, 4)
    refused = rig.refusal(PumpSetting.PUMP_FLOWRATE_MODE, 1)
    assert (refused.status, refused.code) == (409, "in_flight")
    rig.tick()
    assert rig.refusal(PumpSetting.PUMP_FLOWRATE_MODE, 1).code == "in_flight"


def test_a_write_behind_ovenbird_s_own_command_waits_and_is_sent_once() -> None:
    """A write behind a queued command of ovenbird waits for it and is sent once."""
    rig = Rig()
    (own,) = rig.adapter.submit(
        [CommandIntent(IntentKind.WATER_SETPOINT, 31, ReasonCode.CURVE)], rig.clock()
    )
    assert own.status is CommandStatus.QUEUED
    assert rig.tick().kind is IntentKind.WATER_SETPOINT
    queued = rig.request(PumpSetting.HEAT_DELTA, 4)
    assert queued.status is CommandStatus.QUEUED
    assert rig.tick(1.0) is None
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    sent = rig.tick(7.0)
    assert sent is not None
    assert sent.kind is PumpSetting.HEAT_DELTA
    rig.pump.report(HeishaSignal.HEAT_DELTA, 4)
    for _ in range(5):
        assert rig.tick(7.0) is None
    statuses = [e.status for e in rig.events if e.kind is PumpSetting.HEAT_DELTA]
    assert statuses == [CommandStatus.QUEUED, CommandStatus.SENT, CommandStatus.VERIFIED]
    write = rig.adapter.operator_writes[PumpSetting.HEAT_DELTA]
    assert (write.to, write.status) == (4, CommandStatus.VERIFIED)


def test_a_failed_verification_alarms_without_holding_setpoint_control() -> None:
    """A write whose verification fails raises an alarm without holding setpoint control."""
    rig = Rig()
    rig.request(PumpSetting.HEAT_DELTA, 4)
    assert rig.tick() is not None
    for _ in range(2):
        assert rig.tick(29.0) is None
        assert rig.tick(1.0) is not None
    assert rig.tick(30.0) is None
    statuses = [event.status.value for event in rig.events]
    assert statuses.count("retry") == 2
    assert statuses[-1] == "failed"
    assert rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)
    assert "not supported by this model?" in rig.alarms.active()[0].message
    assert rig.adapter.hold_reason is None
    (queued,) = rig.adapter.submit(
        [CommandIntent(IntentKind.WATER_SETPOINT, 31, ReasonCode.CURVE)], rig.clock()
    )
    assert queued.status is CommandStatus.QUEUED
    assert rig.tick(7.0).kind is IntentKind.WATER_SETPOINT
    rig.pump.report(HeishaSignal.Z1_WATER_TARGET_TEMP, 31)
    rig.tick(1.0)
    assert rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)
    rig.pump.report(HeishaSignal.HEAT_DELTA, 4)
    rig.tick(1.0)
    assert not rig.alarms.is_active(AlarmCode.VERIFICATION_FAILED)


def _write(rig: Rig, setting: PumpSetting) -> None:
    """Write a new low value for the setting and verify it, leaving it counted."""
    spec = PUMP_SETTINGS[setting]
    current = rig.pump.values[spec.signal]
    value = spec.low if current != spec.low else spec.low + 1
    rig.request(setting, value)
    rig.tick(7.0)
    rig.pump.report(spec.signal, value)
    rig.tick(1.0)


def test_rate_limits_per_setting_and_per_day() -> None:
    """Writes are limited per setting and per day."""
    rig = Rig()
    for setting in PumpSetting:
        _write(rig, setting)
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 9)
    assert (refused.status, refused.code) == (429, "rate_limited")
    assert 0 < refused.params["retry_after"] <= 600
    rig.clock.advance(600.0)
    for setting in PumpSetting:
        _write(rig, setting)
    rig.clock.advance(600.0)
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 9)
    assert (refused.status, refused.code) == (429, "day_limit")
    rig.clock.advance(86_400.0)
    assert rig.request(PumpSetting.HEAT_DELTA, 9).status is CommandStatus.QUEUED


def test_the_write_budget_is_shared_and_counted() -> None:
    """The daily write budget counts operator writes and refuses beyond it."""
    rig = Rig(daily_budget=1)
    rig.request(PumpSetting.HEAT_DELTA, 4)
    rig.tick()
    rig.pump.report(HeishaSignal.HEAT_DELTA, 4)
    rig.tick(1.0)
    assert rig.adapter.status()["budget"]["used"] == 1
    rig.clock.advance(600.0)
    refused = rig.refusal(PumpSetting.HEAT_DELTA, 5)
    assert (refused.status, refused.code) == (429, "write_budget")


def test_restored_requests_keep_the_rate_limit() -> None:
    """Operator requests restored from the journal keep their rate limit."""
    rig = Rig()
    stamp = rig.clock().wall.timestamp()
    rig.adapter.restore(
        RestoredAdapter(operator_requests=((stamp - 60.0, PumpSetting.HEAT_DELTA),)), rig.clock()
    )
    assert rig.refusal(PumpSetting.HEAT_DELTA, 4).code == "rate_limited"
    assert rig.request(PumpSetting.PUMP_FLOWRATE_MODE, 1).status is CommandStatus.QUEUED


def test_a_remote_change_is_an_info_alarm_not_a_hold() -> None:
    """A change by someone else is an info alarm that clears later, not a hold."""
    rig = Rig()
    rig.tick()
    rig.pump.report(HeishaSignal.HEAT_DELTA, 7)
    rig.tick(1.0)
    assert rig.alarms.is_active(AlarmCode.PUMP_SETTING_CHANGED)
    assert "Heat_Delta changed from 5 to 7" in rig.alarms.active()[0].message
    assert rig.adapter.hold_reason is None
    rig.tick(86_400.0)
    assert not rig.alarms.is_active(AlarmCode.PUMP_SETTING_CHANGED)


def test_ovenbird_s_own_write_is_not_a_remote_change() -> None:
    """A verified write by ovenbird itself does not raise the remote-change alarm."""
    rig = Rig()
    rig.tick()
    rig.request(PumpSetting.HEAT_DELTA, 4)
    rig.tick()
    rig.pump.report(HeishaSignal.HEAT_DELTA, 4)
    rig.tick(1.0)
    rig.tick(60.0)
    assert not rig.alarms.is_active(AlarmCode.PUMP_SETTING_CHANGED)


def test_operator_commands_stay_out_of_the_arbiter_and_reconcile() -> None:
    """Operator commands do not appear in the arbiter's view or reconcile, only in the status."""
    rig = Rig()
    rig.request(PumpSetting.HEAT_DELTA, 4)
    view = rig.adapter.view()
    assert view.queued == {}
    assert rig.adapter.reconcile([], rig.clock()) == ()
    command = rig.tick()
    assert command.kind is PumpSetting.HEAT_DELTA
    assert rig.adapter.view().in_flight == {}
    assert rig.adapter.status()["in_flight"]["kind"] == "heat_delta"


def test_the_controller_cannot_write_a_pump_setting() -> None:
    """The controller cannot submit a pump setting as an intent."""
    rig = Rig()
    intent = CommandIntent(PumpSetting.HEAT_DELTA, 4, ReasonCode.CURVE)  # type: ignore[arg-type]
    (event,) = rig.adapter.submit([intent], rig.clock())
    assert event.status is CommandStatus.REFUSED
    assert "not an allowed setting" in event.detail
