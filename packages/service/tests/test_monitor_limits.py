from __future__ import annotations

from collections.abc import Callable

from ovenbird.config import Settings
from ovenbird.control.alarms import AlarmBoard
from ovenbird.control.monitors import MonitorConfig, MonitorStatus, SafetyMonitor, evaluate
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird_core.control.types import RoomProfile

ROOM_TOPIC = "sim/room"
CONFIG = MonitorConfig(
    max_supply_c=40.0,
    outlet_margin_k=5.0,
    min_flow_lpm=8.0,
    defrost_max_s=1200.0,
    room_signal="room_temperature",
    room_floor_c=20.3,
    room_profile=RoomProfile.ON_CHANGE,
    room_silence_limit_s=86_400.0,
    ha_enabled=True,
)
EXPECTED = {
    "setpoint_above_max": (40.0, "°C", "above"),
    "outlet_overshoot": (45.0, "°C", "above"),
    "low_flow": (8.0, "l/min", "below"),
    "low_flow_defrost": (8.0, "l/min", "below"),
    "pump_error": (None, None, None),
    "backup_heater": (None, None, None),
    "backup_heater_allowed": (None, None, None),
    "heating_off_outdoor": (20.0, "°C", "above"),
    "defrost_stuck": (1200.0, "s", "above"),
    "room_below_floor": (20.3, "°C", "below"),
    "room_sensor_silent": (86_400.0, "s", "above"),
    "ha_link_down": (None, None, None),
}


def runtime(make_settings: Callable[..., Settings], **topics: str) -> Runtime:
    """Build a runtime fed healthy pump readings and a room reading, with topic overrides."""
    settings = make_settings(
        mqtt_inputs=[{"topic": ROOM_TOPIC, "signal": "room_temperature", "unit": "°C"}]
    )
    state = Runtime(clock=FakeClock())
    ingest = MqttIngest(settings, state)
    healthy = {
        "Pump_Flow": "25.00",
        "Error": "No error",
        "Room_Heater_State": "0",
        "Internal_Heater_State": "0",
        "External_Heater_State": "0",
        "Heating_Off_Outdoor_Temp": "20",
    }
    for message in pump_messages(**{**healthy, **topics}):
        ingest.ingest(message)
    ingest.ingest(inbound(ROOM_TOPIC, "21.0"))
    return state


def test_every_monitor_reports_its_limit_unit_and_direction(
    make_settings: Callable[..., Settings],
) -> None:
    """Every safety monitor reports its limit, unit and direction when evaluated."""
    state = runtime(make_settings)
    _since, findings = evaluate(CONFIG, state.store.snapshot(state.clock()), {})
    found = {
        finding.code.value: (finding.limit, finding.unit, finding.direction) for finding in findings
    }
    assert found == EXPECTED


def test_limits_survive_unknown_inputs_and_reach_the_api_form(
    make_settings: Callable[..., Settings],
) -> None:
    """Limits stay None for unknown inputs and all appear in the API status form."""
    state = runtime(make_settings, Heating_Off_Outdoor_Temp="-1000", Pump_Flow="nan")
    monitor = SafetyMonitor(CONFIG, AlarmBoard(), state)
    monitor.check()
    rows = {row["code"]: row for row in monitor.status()["monitors"]}
    assert rows["heating_off_outdoor"]["status"] == MonitorStatus.UNKNOWN
    assert rows["heating_off_outdoor"]["limit"] is None
    assert rows["heating_off_outdoor"]["unit"] == "°C"
    assert rows["low_flow"]["limit"] == 8.0
    assert rows["low_flow"]["direction"] == "below"
    assert rows["pump_error"]["limit"] is None
    assert rows["pump_error"]["direction"] is None
    assert all({"limit", "unit", "direction"} <= set(row) for row in rows.values())
