from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from pydantic import SecretStr

from ovenbird.clock import iso_z
from ovenbird.config import DefrostLowFlowMode, Settings
from ovenbird.control.alarms import AlarmBoard, AlarmCode, AlarmEventKind, Severity
from ovenbird.control.monitors import (
    DEICE_MARGIN_S,
    LOGGED_AS_ALARM,
    LOGGED_ONLY,
    DeiceOnset,
    Finding,
    MonitorConfig,
    MonitorStatus,
    SafetyMonitor,
    evaluate,
    monitor_config,
    room_floor,
    setpoint_excess,
)
from ovenbird.ha import CONFIG_ID, SUBSCRIBE_ID, HaInput
from ovenbird.mqtt import MqttIngest
from ovenbird.notify.notifier import CLEAR_HOLD_S, Notifier
from ovenbird.notify.transport import HttpRequest
from ovenbird.runtime import Runtime
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird_core import Instant, Snapshot
from ovenbird_core.control import IntentKind
from ovenbird_core.pumpmodel import PROFILES

ROOM_TOPIC = "sim/room"
KNOWN_MODEL = "32 D4 0B 88 84 73 90 0C 85 84"
UNKNOWN_MODEL = "C2 D3 0B 33 65 B2 D3 0B 94 65"
PROFILE = PROFILES[KNOWN_MODEL]
MODE2_DEFROST = {
    "Defrosting_State": "1",
    "Compressor_Freq": "86",
    "Pump_Flow": "0.10",
    "Main_Inlet_Temp": "25.50",
}
MODE2_MESSAGE = (
    "deice mode 2 (hot-gas defrost): the heat pump stops its water pump by design because "
    "the return water was 25.5 °C (below 27 °C); Pump_Flow 0.1 l/min, compressor 86 Hz"
)
MODE1_DEFROST = {
    "Defrosting_State": "1",
    "Compressor_Freq": "42",
    "Pump_Flow": "3.00",
    "Main_Inlet_Temp": "30.00",
}
MODE1_MESSAGE = (
    "low water flow during a defrost (deice mode 1, the pump should run): Pump_Flow 3.0 l/min "
    "with the compressor at 42 Hz (minimum 8.0 l/min)"
)
GENERIC_MESSAGE = (
    "low water flow during a defrost: Pump_Flow 0.1 l/min with the compressor at 86 Hz "
    "(minimum 8.0 l/min); the heat pump slowed or stopped its water pump while defrosting"
)
MODE2 = DeiceOnset(PROFILE, 25.5, 3.0)
HEALTHY: dict[str, str] = {
    "Pump_Flow": "25.00",
    "Error": "No error",
    "Room_Heater_State": "0",
    "Internal_Heater_State": "0",
    "External_Heater_State": "0",
    "Heating_Off_Outdoor_Temp": "20",
    "Z1_Heat_Request_Temp": "30",
}
CONFIG = MonitorConfig(
    max_supply_c=40.0,
    outlet_margin_k=5.0,
    outlet_sustain_s=600.0,
    min_flow_lpm=8.0,
    flow_sustain_s=120.0,
    defrost_max_s=1200.0,
    room_signal="room_temperature",
    room_floor_c=20.3,
    room_floor_sustain_s=1800.0,
)
ALARM = replace(CONFIG, defrost_low_flow="alarm")
LOG = replace(CONFIG, defrost_low_flow="log")


class Plant:
    """A simulated plant: a fake clock, MQTT ingest and mutable topic values fed into monitors."""

    def __init__(self, make_settings: Callable[..., Settings]) -> None:
        """Create the runtime, ingest and healthy pump topics with a 21 degC room."""
        settings = make_settings(
            mqtt_inputs=[{"topic": ROOM_TOPIC, "signal": "room_temperature", "unit": "°C"}]
        )
        self.clock = FakeClock()
        self.runtime = Runtime(clock=self.clock)
        self.ingest = MqttIngest(settings, self.runtime)
        self.topics: dict[str, str] = dict(HEALTHY)
        self.room = "21.0"
        self.since: dict[AlarmCode, Instant] = {}

    def feed(self) -> None:
        """Ingest the current pump topics and room value as MQTT messages."""
        for message in pump_messages(**self.topics):
            self.ingest.ingest(message)
        self.ingest.ingest(inbound(ROOM_TOPIC, self.room))

    def snapshot(self) -> Snapshot:
        """Feed the plant and return the store snapshot at the current time."""
        self.feed()
        return self.runtime.store.snapshot(self.clock())

    def run(
        self, seconds: float = 0.0, step: float = 30.0, **kwargs: Any
    ) -> dict[AlarmCode, Finding]:
        """Evaluate every step seconds for the given duration; return findings by code."""
        elapsed = 0.0
        while True:
            self.since, findings = evaluate(CONFIG, self.snapshot(), self.since, **kwargs)
            if elapsed >= seconds:
                return {finding.code: finding for finding in findings}
            self.clock.advance(step)
            elapsed += step


@pytest.fixture
def plant(make_settings: Callable[..., Settings]) -> Plant:
    """Provide a plant with healthy defaults."""
    return Plant(make_settings)


def test_a_healthy_pump_is_all_ok(plant: Plant) -> None:
    """A healthy pump reports every monitor OK and leaves no pending timers."""
    findings = plant.run()
    assert set(findings) == {
        AlarmCode.SETPOINT_ABOVE_MAX,
        AlarmCode.OUTLET_OVERSHOOT,
        AlarmCode.LOW_FLOW,
        AlarmCode.LOW_FLOW_DEFROST,
        AlarmCode.PUMP_ERROR,
        AlarmCode.BACKUP_HEATER,
        AlarmCode.BACKUP_HEATER_ALLOWED,
        AlarmCode.HEATING_OFF_OUTDOOR,
        AlarmCode.DEFROST_STUCK,
        AlarmCode.ROOM_BELOW_FLOOR,
    }
    assert {f.status for f in findings.values()} == {MonitorStatus.OK}
    assert plant.since == {}


def test_wrapped_setpoint_alarms_immediately(plant: Plant) -> None:
    """A water target above the maximum supply alarms immediately as critical."""
    plant.topics["Z1_Water_Target_Temp"] = "44"
    finding = plant.run()[AlarmCode.SETPOINT_ABOVE_MAX]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.severity is Severity.CRITICAL
    assert finding.value == 44
    assert "Z1_Water_Target_Temp is 44 °C, above the maximum supply of 40 °C" in finding.message


def test_heat_request_counts_only_in_direct_mode(plant: Plant) -> None:
    """The heat request temperature counts for the setpoint check only in direct mode."""
    plant.topics["Z1_Heat_Request_Temp"] = "41"
    assert plant.run()[AlarmCode.SETPOINT_ABOVE_MAX].status is MonitorStatus.ACTIVE
    plant.topics["Heating_Mode"] = "0"
    plant.topics["Z1_Heat_Request_Temp"] = "5"
    assert plant.run()[AlarmCode.SETPOINT_ABOVE_MAX].status is MonitorStatus.OK


def test_controller_setpoint_is_checked_too(plant: Plant) -> None:
    """The controller's own desired setpoint is checked against the maximum as well."""
    finding = plant.run(desired_setpoint=41)[AlarmCode.SETPOINT_ABOVE_MAX]
    assert finding.status is MonitorStatus.ACTIVE
    assert "controller setpoint" in finding.message


def test_setpoint_excess_helper(plant: Plant) -> None:
    """The setpoint excess helper returns the first signal above the limit, or none."""
    plant.topics["Z1_Water_Target_Temp"] = "44"
    plant.snapshot()
    now = plant.clock()
    read = lambda signal: plant.runtime.store.view(signal, now)  # noqa: E731
    assert setpoint_excess(read, 40) == ("main/Z1_Water_Target_Temp", 44)
    assert setpoint_excess(read, 44) is None


def test_outlet_overshoot_needs_the_sustain_time_and_skips_dhw(plant: Plant) -> None:
    """Outlet overshoot is pending for the sustain time and ignored while heating hot water."""
    plant.topics["Main_Outlet_Temp"] = "46.50"
    first = plant.run()[AlarmCode.OUTLET_OVERSHOOT]
    assert first.status is MonitorStatus.PENDING
    assert plant.run(600.0)[AlarmCode.OUTLET_OVERSHOOT].status is MonitorStatus.ACTIVE
    plant.topics["ThreeWay_Valve_State"] = "1"
    finding = plant.run()[AlarmCode.OUTLET_OVERSHOOT]
    assert finding.status is MonitorStatus.OK
    assert "DHW" in finding.message
    plant.topics["ThreeWay_Valve_State"] = "0"
    assert plant.run()[AlarmCode.OUTLET_OVERSHOOT].status is MonitorStatus.PENDING


def test_low_flow_only_while_the_compressor_runs(plant: Plant) -> None:
    """Low flow is pending, then active, only while the compressor runs."""
    plant.topics["Pump_Flow"] = "4.00"
    assert plant.run()[AlarmCode.LOW_FLOW].status is MonitorStatus.PENDING
    finding = plant.run(120.0)[AlarmCode.LOW_FLOW]
    assert finding.status is MonitorStatus.ACTIVE
    assert "4.0 l/min" in finding.message
    plant.topics["Compressor_Freq"] = "0"
    assert plant.run()[AlarmCode.LOW_FLOW].status is MonitorStatus.OK


def test_a_defrost_suspends_low_flow_and_low_flow_defrost_takes_over(plant: Plant) -> None:
    """A defrost suspends low flow, and low-flow-defrost takes over after its sustain time."""
    plant.topics.update(MODE2_DEFROST)
    findings = plant.run(deice=MODE2)
    assert findings[AlarmCode.LOW_FLOW].status is MonitorStatus.OK
    assert findings[AlarmCode.LOW_FLOW].message == (
        "suspended during a defrost (see low_flow_defrost)"
    )
    assert findings[AlarmCode.LOW_FLOW].value == pytest.approx(0.1)
    assert findings[AlarmCode.LOW_FLOW_DEFROST].status is MonitorStatus.PENDING
    findings = plant.run(120.0, deice=MODE2)
    finding = findings[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.severity is Severity.WARNING
    assert finding.message == MODE2_MESSAGE
    assert finding.value == pytest.approx(0.1)
    assert (finding.limit, finding.unit, finding.direction) == (8.0, "l/min", "below")
    assert findings[AlarmCode.LOW_FLOW].status is MonitorStatus.OK
    assert AlarmCode.LOW_FLOW not in plant.since


def test_low_flow_in_deice_mode_1_says_the_pump_should_run(plant: Plant) -> None:
    """Low flow during deice mode 1 says that the pump should be running."""
    plant.topics.update(MODE1_DEFROST)
    finding = plant.run(120.0, deice=DeiceOnset(PROFILE, 30.0, 3.0))[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.message == MODE1_MESSAGE


@pytest.mark.parametrize("deice", [None, DeiceOnset(None, 25.5, 3.0)])
def test_an_unknown_model_only_describes_what_is_seen(
    plant: Plant, deice: DeiceOnset | None
) -> None:
    """Without a known pump profile the message only describes the observed values."""
    plant.topics.update(MODE2_DEFROST)
    finding = plant.run(120.0, deice=deice)[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.message == GENERIC_MESSAGE
    assert "design" not in finding.message
    assert "mode" not in finding.message


def test_low_flow_defrost_is_ok_outside_a_defrost_or_with_enough_flow(plant: Plant) -> None:
    """Low-flow-defrost is OK outside a defrost or with enough flow, and unknown when stale."""
    finding = plant.run()[AlarmCode.LOW_FLOW_DEFROST]
    assert (finding.status, finding.message) == (MonitorStatus.OK, "no defrost running")
    plant.topics["Defrosting_State"] = "1"
    finding = plant.run()[AlarmCode.LOW_FLOW_DEFROST]
    assert (finding.status, finding.message) == (
        MonitorStatus.OK,
        "Pump_Flow 25.0 l/min during the defrost",
    )
    finding = plant.run(deice=DeiceOnset(PROFILE, 30.0, 3.0))[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.message == "Pump_Flow 25.0 l/min during the defrost (deice mode 1)"
    plant.topics.update(Compressor_Freq="0", Pump_Flow="0.10")
    assert plant.run()[AlarmCode.LOW_FLOW_DEFROST].status is MonitorStatus.OK
    plant.clock.advance(3600.0)
    _, findings = evaluate(CONFIG, plant.runtime.store.snapshot(plant.clock()), {})
    stale = {f.code: f for f in findings}[AlarmCode.LOW_FLOW_DEFROST]
    assert stale.status is MonitorStatus.UNKNOWN
    assert stale.message == "Defrosting_State unknown or stale"


def test_the_cold_outdoor_rule_explains_itself(plant: Plant) -> None:
    """The cold-outdoor deice rule explains in the message why the pump stops."""
    plant.topics.update(MODE2_DEFROST)
    onset = DeiceOnset(PROFILE, 45.0, -12.0)
    assert onset.mode == 2
    message = plant.run(120.0, deice=onset)[AlarmCode.LOW_FLOW_DEFROST].message
    assert "because the outdoor air was -12.0 °C (below -10 °C) with return water 45.0 °C" in (
        message
    )


def test_defrost_stuck_allows_a_mode_2_defrost_its_designed_length(plant: Plant) -> None:
    """A mode 2 defrost is allowed its designed length before the defrost is stuck."""
    plant.topics["Defrosting_State"] = "1"
    finding = plant.run(1200.0, deice=MODE2)[AlarmCode.DEFROST_STUCK]
    assert finding.status is MonitorStatus.PENDING
    assert finding.limit == 2100.0
    assert finding.message == "defrost running (limit 35 min)"
    assert plant.run(900.0, deice=MODE2)[AlarmCode.DEFROST_STUCK].status is MonitorStatus.ACTIVE
    longer = replace(CONFIG, defrost_max_s=3600.0)
    _, findings = evaluate(longer, plant.snapshot(), {}, deice=MODE2)
    assert {f.code: f for f in findings}[AlarmCode.DEFROST_STUCK].limit == 3600.0
    for other in (DeiceOnset(PROFILE, 30.0, 3.0), DeiceOnset(None, 25.5, 3.0)):
        _, findings = evaluate(CONFIG, plant.snapshot(), {}, deice=other)
        assert {f.code: f for f in findings}[AlarmCode.DEFROST_STUCK].limit == 1200.0


def test_low_flow_that_outlasts_the_defrost_raises_low_flow_after_the_sustain_time(
    plant: Plant,
) -> None:
    """Low flow that outlasts the defrost raises low flow only after its own sustain time."""
    plant.topics.update(MODE2_DEFROST)
    plant.run(900.0, deice=MODE2)
    plant.topics["Defrosting_State"] = "0"
    findings = plant.run()
    assert findings[AlarmCode.LOW_FLOW_DEFROST].status is MonitorStatus.OK
    assert findings[AlarmCode.LOW_FLOW].status is MonitorStatus.PENDING
    assert plant.run(90.0)[AlarmCode.LOW_FLOW].status is MonitorStatus.PENDING
    finding = plant.run(30.0)[AlarmCode.LOW_FLOW]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.severity is Severity.CRITICAL


def test_pump_error_and_backup_heaters(plant: Plant) -> None:
    """A pump error and backup heaters raise their alarms with the matching severities."""
    plant.topics.update(Error="H62", Internal_Heater_State="1", Room_Heater_State="1")
    findings = plant.run()
    assert findings[AlarmCode.PUMP_ERROR].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.PUMP_ERROR].value == "H62"
    assert findings[AlarmCode.BACKUP_HEATER].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.BACKUP_HEATER].severity is Severity.WARNING
    assert findings[AlarmCode.BACKUP_HEATER_ALLOWED].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.BACKUP_HEATER_ALLOWED].severity is Severity.INFO


def test_heating_off_cutoff_has_hysteresis(plant: Plant) -> None:
    """The heating-off outdoor cutoff applies a hysteresis around the threshold."""
    plant.topics.update(Heating_Off_Outdoor_Temp="15", Outside_Temp="15")
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.ACTIVE
    plant.topics["Outside_Temp"] = "14"
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.ACTIVE
    plant.topics["Outside_Temp"] = "13"
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.OK


def test_defrost_stuck_after_the_limit(plant: Plant) -> None:
    """A defrost running past the limit becomes stuck, after being pending."""
    plant.topics["Defrosting_State"] = "1"
    assert plant.run(600.0)[AlarmCode.DEFROST_STUCK].status is MonitorStatus.PENDING
    assert plant.run(600.0)[AlarmCode.DEFROST_STUCK].status is MonitorStatus.ACTIVE


def test_room_below_floor_after_the_sustain_time(plant: Plant) -> None:
    """The room below the comfort floor is pending, then active after the sustain time."""
    plant.room = "20.1"
    assert plant.run(1770.0)[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.PENDING
    assert plant.run(30.0)[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.ACTIVE
    plant.room = "20.5"
    assert plant.run()[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.OK


def test_a_night_set_back_lowers_the_floor_by_the_set_back(plant: Plant) -> None:
    """A night set-back lowers the comfort floor by the size of the set-back."""
    plant.room = "19.6"
    assert plant.run(1800.0)[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.ACTIVE
    plant.since = {}
    floor = plant.run(3600.0, room_shift_k=-1.0)[AlarmCode.ROOM_BELOW_FLOOR]
    assert floor.status is MonitorStatus.OK
    assert floor.limit == pytest.approx(19.3)


def test_a_room_really_too_cold_still_alarms_during_a_set_back(plant: Plant) -> None:
    """A room colder than the lowered floor still alarms during a set-back."""
    plant.room = "19.1"
    assert plant.run(1770.0, room_shift_k=-1.0)[AlarmCode.ROOM_BELOW_FLOOR].status is (
        MonitorStatus.PENDING
    )
    floor = plant.run(30.0, room_shift_k=-1.0)[AlarmCode.ROOM_BELOW_FLOOR]
    assert floor.status is MonitorStatus.ACTIVE
    assert floor.message == (
        "room 19.1 °C against a comfort floor of 19.3 °C (20.3 °C lowered by the 1.0 K set-back)"
    )


def test_the_floor_never_follows_a_set_back_beyond_its_bound(plant: Plant) -> None:
    """The floor does not follow a set-back beyond its configured bound."""
    assert room_floor(CONFIG, -3.0) == pytest.approx(19.3)
    assert room_floor(replace(CONFIG, room_setback_max_k=0.5), -1.0) == pytest.approx(19.8)
    plant.room = "19.2"
    floor = plant.run(1800.0, room_shift_k=-3.0)[AlarmCode.ROOM_BELOW_FLOOR]
    assert floor.status is MonitorStatus.ACTIVE
    assert floor.limit == pytest.approx(19.3)


def test_a_raised_target_or_no_shift_keeps_the_static_floor(plant: Plant) -> None:
    """A raised target or a missing shift keeps the static comfort floor."""
    assert room_floor(CONFIG, 1.0) == CONFIG.room_floor_c
    assert room_floor(CONFIG, None) == CONFIG.room_floor_c
    assert room_floor(CONFIG, float("nan")) == CONFIG.room_floor_c
    assert room_floor(MonitorConfig(max_supply_c=40.0), -1.0) is None
    plant.room = "20.1"
    floor = plant.run(1800.0, room_shift_k=1.0)[AlarmCode.ROOM_BELOW_FLOOR]
    assert floor.status is MonitorStatus.ACTIVE
    assert floor.message == "room 20.1 °C against a comfort floor of 20.3 °C"


def test_the_safety_monitor_reads_the_room_shift(plant: Plant) -> None:
    """The safety monitor reads the room shift to lower or restore the floor."""
    shift: list[float | None] = [-1.0]
    alarms = AlarmBoard()
    monitor = SafetyMonitor(CONFIG, alarms, plant.runtime, room_shift=lambda: shift[0])
    plant.room = "19.6"
    plant.feed()
    monitor.check()
    plant.clock.advance(1800.0)
    plant.feed()
    monitor.check()
    assert not alarms.is_active(AlarmCode.ROOM_BELOW_FLOOR)
    shift[0] = None
    monitor.check()
    plant.clock.advance(1800.0)
    plant.feed()
    monitor.check()
    assert alarms.is_active(AlarmCode.ROOM_BELOW_FLOOR)


def test_room_floor_is_optional(plant: Plant) -> None:
    """Without a configured room floor, no room-below-floor finding is produced."""
    plant.feed()
    _, findings = evaluate(
        MonitorConfig(max_supply_c=40.0), plant.runtime.store.snapshot(plant.clock()), {}
    )
    assert AlarmCode.ROOM_BELOW_FLOOR not in {f.code for f in findings}


def test_unknown_inputs_keep_the_first_seen_time(plant: Plant) -> None:
    """Monitors with unknown inputs keep the time they were first seen."""
    plant.topics["Pump_Flow"] = "4.00"
    plant.run()
    first = plant.since[AlarmCode.LOW_FLOW]
    plant.clock.advance(3600.0)
    _, findings = evaluate(CONFIG, plant.runtime.store.snapshot(plant.clock()), plant.since)
    flow = {f.code: f for f in findings}[AlarmCode.LOW_FLOW]
    assert flow.status is MonitorStatus.UNKNOWN
    since, _ = evaluate(CONFIG, plant.runtime.store.snapshot(plant.clock()), plant.since)
    assert since[AlarmCode.LOW_FLOW] == first


class Adapter:
    """Adapter stand-in that records the alarm codes pushed by the safety monitor."""

    def __init__(self) -> None:
        """Start with no recorded updates."""
        self.updates: list[frozenset[AlarmCode]] = []

    def safety_update(self, codes: frozenset[AlarmCode], now: Instant) -> None:
        """Record the set of active safety alarm codes."""
        self.updates.append(codes)


def test_safety_monitor_raises_and_clears_only_when_the_condition_is_gone(plant: Plant) -> None:
    """The safety monitor raises alarms, pushes them to the adapter and clears when resolved."""
    events: list[Any] = []
    alarms = AlarmBoard(journal=events.append)
    adapter = Adapter()
    monitor = SafetyMonitor(CONFIG, alarms, plant.runtime, adapter=adapter, desired=lambda: 31)
    assert monitor.status()["level"] == "starting"
    plant.topics.update(Error="H62", Z1_Water_Target_Temp="44")
    plant.feed()
    monitor.check()
    assert alarms.is_active(AlarmCode.PUMP_ERROR)
    assert alarms.is_active(AlarmCode.SETPOINT_ABOVE_MAX)
    assert adapter.updates[-1] == {AlarmCode.PUMP_ERROR, AlarmCode.SETPOINT_ABOVE_MAX}
    assert plant.runtime.alarm_level == "critical"
    assert plant.runtime.health()["ready"] is False
    plant.clock.advance(3600.0)
    monitor.check()
    assert alarms.is_active(AlarmCode.PUMP_ERROR)
    plant.topics.update(Error="No error", Z1_Water_Target_Temp="30")
    plant.feed()
    monitor.check()
    assert alarms.active() == ()
    assert plant.runtime.alarm_level == "ok"
    kinds = [(e.code, e.event) for e in events]
    assert (AlarmCode.PUMP_ERROR.value, AlarmEventKind.RAISED) in kinds
    assert (AlarmCode.PUMP_ERROR.value, AlarmEventKind.CLEARED) in kinds
    status = monitor.status()
    assert status["level"] == "ok"
    assert {m["code"] for m in status["monitors"]} >= {"low_flow", "pump_error"}
    assert IntentKind.WATER_SETPOINT.value == "water_setpoint"


async def test_safety_monitor_run_needs_sleep(plant: Plant) -> None:
    """The safety monitor's run loop requires a sleep function."""
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    with pytest.raises(RuntimeError, match="sleep"):
        await monitor.run()


def test_room_value_refused_for_its_unit_alarms(plant: Plant) -> None:
    """A room value refused for its unit raises an alarm until Home Assistant reports Celsius."""
    signal = "ha/sensor.room"
    config = MonitorConfig(max_supply_c=40.0, room_signal=signal)
    ha = HaInput(
        "http://ha",
        SecretStr("t"),
        ("sensor.room",),
        plant.runtime,
        temperature=frozenset({signal}),
    )
    ha.open_session()
    ha.handle({"id": CONFIG_ID, "type": "result", "success": True, "result": {}})
    state = {"s": "70.1", "a": {}, "lc": 1.0, "lu": 1.0, "lr": 1.0}
    ha.handle({"id": SUBSCRIBE_ID, "type": "event", "event": {"a": {"sensor.room": state}}})
    plant.feed()
    _, findings = evaluate(config, plant.runtime.store.snapshot(plant.clock()), {})
    found = {f.code: f for f in findings}[AlarmCode.ROOM_UNIT_REFUSED]
    assert found.status is MonitorStatus.ACTIVE
    assert found.message.startswith("room value refused: no temperature unit")
    ha.handle(
        {
            "id": CONFIG_ID,
            "type": "result",
            "success": True,
            "result": {"unit_system": {"temperature": "°C"}},
        }
    )
    _, findings = evaluate(config, plant.runtime.store.snapshot(plant.clock()), {})
    assert {f.code: f for f in findings}[AlarmCode.ROOM_UNIT_REFUSED].status is MonitorStatus.OK
    _, findings = evaluate(CONFIG, plant.runtime.store.snapshot(plant.clock()), {})
    assert AlarmCode.ROOM_UNIT_REFUSED not in {f.code for f in findings}


def check_for(plant: Plant, monitor: SafetyMonitor, seconds: float, step: float = 30.0) -> None:
    """Feed the plant and run the monitor every step seconds for the given duration."""
    elapsed = 0.0
    while True:
        plant.feed()
        monitor.check()
        if elapsed >= seconds:
            return
        plant.clock.advance(step)
        elapsed += step


def journal_of(events: list[Any], code: AlarmCode) -> list[Any]:
    """Return the journal events of one alarm code."""
    return [event for event in events if event.code == code.value]


def test_the_defrost_start_is_latched_and_the_profile_read_from_the_model(
    plant: Plant,
) -> None:
    """The defrost start is latched, with the pump profile read from the reported model."""
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    plant.topics["Heat_Pump_Model"] = KNOWN_MODEL
    check_for(plant, monitor, 0.0)
    assert monitor.profile == PROFILE
    assert monitor.deice is None
    plant.topics.update(MODE2_DEFROST)
    check_for(plant, monitor, 0.0)
    assert monitor.deice == MODE2
    plant.topics["Main_Inlet_Temp"] = "31.00"
    check_for(plant, monitor, 600.0)
    assert monitor.deice == MODE2
    found = {finding.code: finding for finding in monitor.findings}
    assert found[AlarmCode.LOW_FLOW_DEFROST].message == MODE2_MESSAGE
    plant.topics["Defrosting_State"] = "0"
    check_for(plant, monitor, 30.0)
    plant.topics["Defrosting_State"] = "1"
    check_for(plant, monitor, 0.0)
    assert monitor.deice == DeiceOnset(PROFILE, 31.0, 3.0)
    assert monitor.deice.mode == 1


def test_a_model_reported_after_the_start_selects_its_profile(plant: Plant) -> None:
    """A model reported after the defrost started selects its profile from then on."""
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    plant.topics.update(MODE2_DEFROST)
    check_for(plant, monitor, 0.0)
    assert monitor.profile is None
    assert monitor.deice == DeiceOnset(None, 25.5, 3.0)
    plant.topics.update(Heat_Pump_Model=UNKNOWN_MODEL, Main_Inlet_Temp="31.00")
    check_for(plant, monitor, 0.0)
    assert monitor.profile is None
    plant.topics["Heat_Pump_Model"] = KNOWN_MODEL
    check_for(plant, monitor, 120.0)
    assert monitor.profile == PROFILE
    assert monitor.deice == MODE2
    found = {finding.code: finding for finding in monitor.findings}
    assert found[AlarmCode.LOW_FLOW_DEFROST].message == MODE2_MESSAGE


def test_the_snapshot_shows_the_latched_defrost_and_its_mode(plant: Plant) -> None:
    """The runtime snapshot shows the latched defrost with its mode, start values and time limit."""
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    plant.runtime.defrost = monitor.defrost_state
    plant.topics["Heat_Pump_Model"] = KNOWN_MODEL
    check_for(plant, monitor, 0.0)
    idle = plant.runtime.snapshot()["defrost"]
    assert idle == {
        "active": False,
        "mode": None,
        "since": None,
        "inlet_at_start_c": None,
        "outside_at_start_c": None,
        "max_s": None,
    }
    plant.topics.update(MODE2_DEFROST)
    plant.feed()
    assert plant.runtime.snapshot()["defrost"] == {**idle, "active": True, "max_s": 1200.0}
    start = plant.clock().wall
    check_for(plant, monitor, 60.0)
    assert plant.runtime.snapshot()["defrost"] == {
        "active": True,
        "mode": 2,
        "since": iso_z(start),
        "inlet_at_start_c": 25.5,
        "outside_at_start_c": 3.0,
        "max_s": 1800.0 + DEICE_MARGIN_S,
    }
    plant.topics["Defrosting_State"] = "0"
    check_for(plant, monitor, 30.0)
    assert plant.runtime.snapshot()["defrost"] == idle


def test_the_snapshot_defrost_has_no_mode_for_an_unknown_model(plant: Plant) -> None:
    """The snapshot defrost has no mode for an unknown pump model."""
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    plant.runtime.defrost = monitor.defrost_state
    plant.topics.update(Heat_Pump_Model=UNKNOWN_MODEL, **MODE2_DEFROST)
    check_for(plant, monitor, 0.0)
    defrost = plant.runtime.snapshot()["defrost"]
    assert defrost["active"] is True
    assert defrost["mode"] is None
    assert defrost["inlet_at_start_c"] == 25.5
    assert defrost["max_s"] == 1200.0


def test_the_snapshot_defrost_without_a_monitor_follows_the_flag(plant: Plant) -> None:
    """Without a monitor the snapshot defrost only follows the defrosting flag."""
    plant.topics.update(MODE2_DEFROST)
    plant.feed()
    defrost = plant.runtime.snapshot()["defrost"]
    assert defrost == {
        "active": True,
        "mode": None,
        "since": None,
        "inlet_at_start_c": None,
        "outside_at_start_c": None,
        "max_s": None,
    }


@pytest.mark.parametrize(
    ("setting", "model", "topics", "journal_only"),
    [
        ("auto", KNOWN_MODEL, MODE2_DEFROST, True),
        ("auto", KNOWN_MODEL, MODE1_DEFROST, False),
        ("auto", UNKNOWN_MODEL, MODE2_DEFROST, False),
        ("alarm", KNOWN_MODEL, MODE2_DEFROST, False),
        ("alarm", KNOWN_MODEL, MODE1_DEFROST, False),
        ("alarm", UNKNOWN_MODEL, MODE2_DEFROST, False),
        ("log", KNOWN_MODEL, MODE2_DEFROST, True),
        ("log", KNOWN_MODEL, MODE1_DEFROST, False),
        ("log", UNKNOWN_MODEL, MODE2_DEFROST, True),
    ],
)
def test_the_setting_decides_between_alarm_and_journal(
    plant: Plant,
    setting: DefrostLowFlowMode,
    model: str,
    topics: dict[str, str],
    journal_only: bool,
) -> None:
    """The defrost low-flow setting and model decide between a raised alarm and a journal entry."""
    events: list[Any] = []
    alarms = AlarmBoard(journal=events.append)
    config = replace(CONFIG, defrost_low_flow=setting)
    monitor = SafetyMonitor(config, alarms, plant.runtime)
    plant.topics.update(topics, Heat_Pump_Model=model)
    check_for(plant, monitor, 120.0)
    kinds = [event.event for event in journal_of(events, AlarmCode.LOW_FLOW_DEFROST)]
    assert alarms.is_active(AlarmCode.LOW_FLOW_DEFROST) is not journal_only
    assert kinds == [AlarmEventKind.STARTED if journal_only else AlarmEventKind.RAISED]


def test_a_journalled_low_flow_defrost_carries_the_profile_and_start_values(
    plant: Plant,
) -> None:
    """A journalled low-flow defrost carries the pump profile and start values, and no alarm."""
    events: list[Any] = []
    alarms = AlarmBoard(journal=events.append)
    adapter = Adapter()
    monitor = SafetyMonitor(CONFIG, alarms, plant.runtime, adapter=adapter)
    plant.topics.update(MODE2_DEFROST, Heat_Pump_Model=KNOWN_MODEL)
    check_for(plant, monitor, 600.0)
    assert alarms.active() == ()
    assert plant.runtime.alarm_level == "ok"
    rows = {row["code"]: row for row in monitor.status()["monitors"]}
    assert rows["low_flow_defrost"]["status"] == "active"
    plant.topics.update(Defrosting_State="0", Pump_Flow="25.00")
    check_for(plant, monitor, 0.0)
    logged = journal_of(events, AlarmCode.LOW_FLOW_DEFROST)
    assert [event.event for event in logged] == [AlarmEventKind.STARTED, AlarmEventKind.CLEARED]
    started, cleared = logged
    deice = {
        "profile": "WH-MXC12J9E8",
        "deice_mode": 2,
        "inlet_at_start_c": 25.5,
        "outside_at_start_c": 3.0,
    }
    assert started.severity is Severity.INFO
    assert started.message == MODE2_MESSAGE
    assert started.detail == {"logged_only": True, "flow_lpm": pytest.approx(0.1), **deice}
    assert cleared.severity is Severity.INFO
    assert cleared.message == "no defrost running"
    assert cleared.detail == {"logged_only": True, **deice}
    assert all(event.event is not AlarmEventKind.RAISED for event in events)
    assert all(update == frozenset() for update in adapter.updates)


def test_an_unknown_model_in_log_mode_is_journalled_without_a_profile(plant: Plant) -> None:
    """An unknown model in log mode is journalled with a generic message and no profile."""
    events: list[Any] = []
    monitor = SafetyMonitor(LOG, AlarmBoard(journal=events.append), plant.runtime)
    plant.topics.update(MODE2_DEFROST)
    check_for(plant, monitor, 120.0)
    (started,) = journal_of(events, AlarmCode.LOW_FLOW_DEFROST)
    assert started.message == GENERIC_MESSAGE
    assert started.detail["profile"] is None
    assert started.detail["deice_mode"] is None


def test_a_raised_low_flow_defrost_is_a_warning(plant: Plant) -> None:
    """A raised low-flow defrost is a warning that does not push a safety alarm."""
    alarms = AlarmBoard()
    adapter = Adapter()
    monitor = SafetyMonitor(ALARM, alarms, plant.runtime, adapter=adapter)
    plant.topics.update(MODE2_DEFROST, Heat_Pump_Model=KNOWN_MODEL)
    check_for(plant, monitor, 120.0)
    alarm = alarms.get(AlarmCode.LOW_FLOW_DEFROST)
    assert alarm is not None
    assert alarm.message == MODE2_MESSAGE
    assert adapter.updates[-1] == frozenset()
    assert plant.runtime.alarm_level == "warning"


def test_switching_the_setting_while_active_moves_the_alarm_to_the_journal_and_back(
    plant: Plant,
) -> None:
    """Changing the setting while active moves the alarm to the journal and back again."""
    events: list[Any] = []
    alarms = AlarmBoard(journal=events.append)
    monitor = SafetyMonitor(ALARM, alarms, plant.runtime)
    plant.topics.update(MODE2_DEFROST, Heat_Pump_Model=KNOWN_MODEL)
    check_for(plant, monitor, 120.0)
    assert alarms.is_active(AlarmCode.LOW_FLOW_DEFROST)
    monitor.config = CONFIG
    check_for(plant, monitor, 30.0)
    assert not alarms.is_active(AlarmCode.LOW_FLOW_DEFROST)
    monitor.config = ALARM
    check_for(plant, monitor, 0.0)
    assert alarms.is_active(AlarmCode.LOW_FLOW_DEFROST)
    logged = [
        (event.event, event.severity, event.message)
        for event in journal_of(events, AlarmCode.LOW_FLOW_DEFROST)
    ]
    assert logged == [
        (AlarmEventKind.RAISED, Severity.WARNING, MODE2_MESSAGE),
        (AlarmEventKind.CLEARED, Severity.WARNING, LOGGED_ONLY),
        (AlarmEventKind.STARTED, Severity.INFO, MODE2_MESSAGE),
        (AlarmEventKind.CLEARED, Severity.INFO, LOGGED_AS_ALARM),
        (AlarmEventKind.RAISED, Severity.WARNING, MODE2_MESSAGE),
    ]


@pytest.mark.parametrize(
    ("mode", "titles"),
    [
        ("auto", []),
        (
            "alarm",
            ["ovenbird · No flow during defrost", "ovenbird · No flow during defrost: resolved"],
        ),
    ],
)
def test_log_mode_events_are_never_notified(
    plant: Plant, make_settings: Callable[..., Settings], mode: str, titles: list[str]
) -> None:
    """Journal-only low-flow events are never notified, while raised alarms are."""
    sent: list[HttpRequest] = []

    def transport(request: HttpRequest) -> int:
        """Record the request and report success."""
        sent.append(request)
        return 200

    ticks = [0.0]
    settings = make_settings(
        notify_ntfy_url="https://ntfy.example.test/",
        notify_ntfy_topic="ovenbird-topic",
        notify_min_severity="info",
        safety_defrost_low_flow=mode,
    )
    notifier = Notifier(
        settings, plant.clock, Facts(), transport=transport, monotonic=lambda: ticks[0]
    )
    alarms = AlarmBoard()
    notifier.attach(alarms)
    monitor = SafetyMonitor(monitor_config(settings, 40.0), alarms, plant.runtime)
    plant.topics.update(MODE2_DEFROST, Heat_Pump_Model=KNOWN_MODEL)
    check_for(plant, monitor, 600.0)
    asyncio.run(notifier.flush())
    plant.topics.update(Defrosting_State="0", Pump_Flow="25.00")
    check_for(plant, monitor, 30.0)
    ticks[0] = CLEAR_HOLD_S * 2
    asyncio.run(notifier.flush())
    assert [json.loads(request.body or b"{}")["title"] for request in sent] == titles
