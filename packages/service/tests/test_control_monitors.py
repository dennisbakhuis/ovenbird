from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import SecretStr

from ovenbird.config import Settings
from ovenbird.control.alarms import AlarmBoard, AlarmCode, AlarmEventKind, Severity
from ovenbird.control.monitors import (
    Finding,
    MonitorConfig,
    MonitorStatus,
    SafetyMonitor,
    evaluate,
    setpoint_excess,
)
from ovenbird.ha import CONFIG_ID, SUBSCRIBE_ID, HaInput
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird_core import Instant, Snapshot
from ovenbird_core.control import IntentKind

ROOM_TOPIC = "sim/room"
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
