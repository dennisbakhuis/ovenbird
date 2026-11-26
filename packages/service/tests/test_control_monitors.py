from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from pydantic import SecretStr

from ovenbird.config import DefrostLowFlowMode, Settings
from ovenbird.control.alarms import AlarmBoard, AlarmCode, AlarmEventKind, Severity
from ovenbird.control.monitors import (
    LOGGED_AS_ALARM,
    LOGGED_ONLY,
    DeiceOnset,
    Finding,
    MonitorConfig,
    MonitorStatus,
    SafetyMonitor,
    evaluate,
    monitor_config,
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
    def __init__(self, make_settings: Callable[..., Settings]) -> None:
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
        for message in pump_messages(**self.topics):
            self.ingest.ingest(message)
        self.ingest.ingest(inbound(ROOM_TOPIC, self.room))

    def snapshot(self) -> Snapshot:
        self.feed()
        return self.runtime.store.snapshot(self.clock())

    def run(
        self, seconds: float = 0.0, step: float = 30.0, **kwargs: Any
    ) -> dict[AlarmCode, Finding]:
        elapsed = 0.0
        while True:
            self.since, findings = evaluate(CONFIG, self.snapshot(), self.since, **kwargs)
            if elapsed >= seconds:
                return {finding.code: finding for finding in findings}
            self.clock.advance(step)
            elapsed += step


@pytest.fixture
def plant(make_settings: Callable[..., Settings]) -> Plant:
    return Plant(make_settings)


def test_a_healthy_pump_is_all_ok(plant: Plant) -> None:
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
    plant.topics["Z1_Water_Target_Temp"] = "44"
    finding = plant.run()[AlarmCode.SETPOINT_ABOVE_MAX]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.severity is Severity.CRITICAL
    assert finding.value == 44
    assert "Z1_Water_Target_Temp is 44 °C, above the maximum supply of 40 °C" in finding.message


def test_heat_request_counts_only_in_direct_mode(plant: Plant) -> None:
    plant.topics["Z1_Heat_Request_Temp"] = "41"
    assert plant.run()[AlarmCode.SETPOINT_ABOVE_MAX].status is MonitorStatus.ACTIVE
    plant.topics["Heating_Mode"] = "0"
    plant.topics["Z1_Heat_Request_Temp"] = "5"
    assert plant.run()[AlarmCode.SETPOINT_ABOVE_MAX].status is MonitorStatus.OK


def test_controller_setpoint_is_checked_too(plant: Plant) -> None:
    finding = plant.run(desired_setpoint=41)[AlarmCode.SETPOINT_ABOVE_MAX]
    assert finding.status is MonitorStatus.ACTIVE
    assert "controller setpoint" in finding.message


def test_setpoint_excess_helper(plant: Plant) -> None:
    plant.topics["Z1_Water_Target_Temp"] = "44"
    plant.snapshot()
    now = plant.clock()
    read = lambda signal: plant.runtime.store.view(signal, now)  # noqa: E731
    assert setpoint_excess(read, 40) == ("main/Z1_Water_Target_Temp", 44)
    assert setpoint_excess(read, 44) is None


def test_outlet_overshoot_needs_the_sustain_time_and_skips_dhw(plant: Plant) -> None:
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
    plant.topics["Pump_Flow"] = "4.00"
    assert plant.run()[AlarmCode.LOW_FLOW].status is MonitorStatus.PENDING
    finding = plant.run(120.0)[AlarmCode.LOW_FLOW]
    assert finding.status is MonitorStatus.ACTIVE
    assert "4.0 l/min" in finding.message
    plant.topics["Compressor_Freq"] = "0"
    assert plant.run()[AlarmCode.LOW_FLOW].status is MonitorStatus.OK


def test_a_defrost_suspends_low_flow_and_low_flow_defrost_takes_over(plant: Plant) -> None:
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
    plant.topics.update(MODE1_DEFROST)
    finding = plant.run(120.0, deice=DeiceOnset(PROFILE, 30.0, 3.0))[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.message == MODE1_MESSAGE


@pytest.mark.parametrize("deice", [None, DeiceOnset(None, 25.5, 3.0)])
def test_an_unknown_model_only_describes_what_is_seen(
    plant: Plant, deice: DeiceOnset | None
) -> None:
    plant.topics.update(MODE2_DEFROST)
    finding = plant.run(120.0, deice=deice)[AlarmCode.LOW_FLOW_DEFROST]
    assert finding.status is MonitorStatus.ACTIVE
    assert finding.message == GENERIC_MESSAGE
    assert "design" not in finding.message
    assert "mode" not in finding.message


def test_low_flow_defrost_is_ok_outside_a_defrost_or_with_enough_flow(plant: Plant) -> None:
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
    plant.topics.update(MODE2_DEFROST)
    onset = DeiceOnset(PROFILE, 45.0, -12.0)
    assert onset.mode == 2
    message = plant.run(120.0, deice=onset)[AlarmCode.LOW_FLOW_DEFROST].message
    assert "because the outdoor air was -12.0 °C (below -10 °C) with return water 45.0 °C" in (
        message
    )


def test_defrost_stuck_allows_a_mode_2_defrost_its_designed_length(plant: Plant) -> None:
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
    plant.topics.update(Error="H62", Internal_Heater_State="1", Room_Heater_State="1")
    findings = plant.run()
    assert findings[AlarmCode.PUMP_ERROR].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.PUMP_ERROR].value == "H62"
    assert findings[AlarmCode.BACKUP_HEATER].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.BACKUP_HEATER].severity is Severity.WARNING
    assert findings[AlarmCode.BACKUP_HEATER_ALLOWED].status is MonitorStatus.ACTIVE
    assert findings[AlarmCode.BACKUP_HEATER_ALLOWED].severity is Severity.INFO


def test_heating_off_cutoff_has_hysteresis(plant: Plant) -> None:
    plant.topics.update(Heating_Off_Outdoor_Temp="15", Outside_Temp="15")
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.ACTIVE
    plant.topics["Outside_Temp"] = "14"
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.ACTIVE
    plant.topics["Outside_Temp"] = "13"
    assert plant.run()[AlarmCode.HEATING_OFF_OUTDOOR].status is MonitorStatus.OK


def test_defrost_stuck_after_the_limit(plant: Plant) -> None:
    plant.topics["Defrosting_State"] = "1"
    assert plant.run(600.0)[AlarmCode.DEFROST_STUCK].status is MonitorStatus.PENDING
    assert plant.run(600.0)[AlarmCode.DEFROST_STUCK].status is MonitorStatus.ACTIVE


def test_room_below_floor_after_the_sustain_time(plant: Plant) -> None:
    plant.room = "20.1"
    assert plant.run(1770.0)[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.PENDING
    assert plant.run(30.0)[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.ACTIVE
    plant.room = "20.5"
    assert plant.run()[AlarmCode.ROOM_BELOW_FLOOR].status is MonitorStatus.OK


def test_room_floor_is_optional(plant: Plant) -> None:
    plant.feed()
    _, findings = evaluate(
        MonitorConfig(max_supply_c=40.0), plant.runtime.store.snapshot(plant.clock()), {}
    )
    assert AlarmCode.ROOM_BELOW_FLOOR not in {f.code for f in findings}


def test_unknown_inputs_keep_the_first_seen_time(plant: Plant) -> None:
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
    def __init__(self) -> None:
        self.updates: list[frozenset[AlarmCode]] = []

    def safety_update(self, codes: frozenset[AlarmCode], now: Instant) -> None:
        self.updates.append(codes)


def test_safety_monitor_raises_and_clears_only_when_the_condition_is_gone(plant: Plant) -> None:
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
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), plant.runtime)
    with pytest.raises(RuntimeError, match="sleep"):
        await monitor.run()


def test_room_value_refused_for_its_unit_alarms(plant: Plant) -> None:
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
    elapsed = 0.0
    while True:
        plant.feed()
        monitor.check()
        if elapsed >= seconds:
            return
        plant.clock.advance(step)
        elapsed += step


def journal_of(events: list[Any], code: AlarmCode) -> list[Any]:
    return [event for event in events if event.code == code.value]


def test_the_defrost_start_is_latched_and_the_profile_read_from_the_model(
    plant: Plant,
) -> None:
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
    events: list[Any] = []
    monitor = SafetyMonitor(LOG, AlarmBoard(journal=events.append), plant.runtime)
    plant.topics.update(MODE2_DEFROST)
    check_for(plant, monitor, 120.0)
    (started,) = journal_of(events, AlarmCode.LOW_FLOW_DEFROST)
    assert started.message == GENERIC_MESSAGE
    assert started.detail["profile"] is None
    assert started.detail["deice_mode"] is None


def test_a_raised_low_flow_defrost_is_a_warning(plant: Plant) -> None:
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
    sent: list[HttpRequest] = []

    def transport(request: HttpRequest) -> int:
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
