from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.ha import EntityState
from ovenbird.runtime import Runtime
from ovenbird.signals import (
    MIRROR_MIN_SIGNALS,
    MIRROR_TOLERANCE,
    pump_mirror_devices,
    pump_values,
    signal_candidates,
)
from ovenbird.testing import FakeClock
from ovenbird_core import Reading, SourceKind

PUMP: dict[str, Any] = {
    "main/Main_Outlet_Temp": 34.5,
    "main/Main_Inlet_Temp": 30.25,
    "main/Outside_Temp": 7,
    "main/Pump_Flow": 14.7,
    "main/Compressor_Freq": 38,
    "main/Defrosting_State": 0,
    "main/Quiet_Mode_Level": 0,
    "main/Holiday_Mode_State": 0,
    "main/Force_Heater_State": 0,
    "main/Operating_Mode_State": "heat",
}
MIRROR_DEVICE = "heishamon-in-ha"


def sensor(value: str, unit: str = "°C", name: str | None = None) -> EntityState:
    """Build an entity state with the given value, unit and optional friendly name."""
    attributes: dict[str, Any] = {"unit_of_measurement": unit}
    if name is not None:
        attributes["friendly_name"] = name
    return EntityState(value, attributes)


class FakeHa:
    """Minimal Home Assistant stand-in with an entity index, devices and temperature unit."""

    def __init__(self, index: dict[str, EntityState], devices: dict[str, str]) -> None:
        """Store the entity index and the entity-to-device mapping."""
        self.index = index
        self.devices = devices
        self.temperature_unit: str | None = "°C"

    def area_of(self, entity_id: str) -> str | None:
        """Return no area, as the fake knows none."""
        return None

    def device_of(self, entity_id: str) -> str | None:
        """Return the device an entity belongs to, if any."""
        return self.devices.get(entity_id)


def runtime_with(values: dict[str, Any]) -> Runtime:
    """Build a runtime whose store holds the given HeishaMon values at the fake clock time."""
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    for signal, value in values.items():
        runtime.apply(Reading(signal, value, None, clock(), SourceKind.HEISHAMON))
    return runtime


def mirrors(
    index: dict[str, EntityState], devices: dict[str, str], values: dict[str, Any] = PUMP
) -> frozenset[str]:
    """Return the devices whose entities copy at least a few of the given pump values."""
    runtime = runtime_with(values)
    return pump_mirror_devices(
        index, devices.get, pump_values(runtime.store.snapshot(runtime.clock()))
    )


def test_a_device_copying_three_pump_values_is_a_mirror() -> None:
    """A device with three entities copying pump values is flagged as a mirror."""
    index = {
        "sensor.hp_outlet": sensor("34.5"),
        "sensor.hp_inlet": sensor("30.3"),
        "climate.hp_zone1": EntityState("heat", {"current_temperature": 7.0}),
        "sensor.hp_room": sensor("21.0"),
    }
    devices = dict.fromkeys(index, MIRROR_DEVICE)
    assert mirrors(index, devices) == {MIRROR_DEVICE}


def test_two_copied_values_are_below_the_threshold() -> None:
    """Two copied pump values stay below the mirror threshold."""
    assert MIRROR_MIN_SIGNALS == 3
    index = {
        "sensor.hp_outlet": sensor("34.5"),
        "sensor.hp_inlet": sensor("30.25"),
        "sensor.hp_room": sensor("21.0"),
    }
    assert mirrors(index, dict.fromkeys(index, MIRROR_DEVICE)) == frozenset()


def test_a_value_just_outside_the_tolerance_does_not_count() -> None:
    """A value off by more than the tolerance is not counted as a copy."""
    off = 30.25 + MIRROR_TOLERANCE + 0.01
    index = {
        "sensor.hp_outlet": sensor("34.5"),
        "sensor.hp_inlet": sensor(f"{off:.2f}"),
        "sensor.hp_flow": sensor("14.7", "L/min"),
    }
    assert mirrors(index, dict.fromkeys(index, MIRROR_DEVICE)) == frozenset()


def test_entities_matching_the_same_pump_signal_count_once() -> None:
    """Several entities matching the same pump signal count only once."""
    same = {"sensor.a": sensor("34.5"), "sensor.b": sensor("34.52"), "sensor.c": sensor("34.48")}
    assert mirrors(same, dict.fromkeys(same, MIRROR_DEVICE)) == frozenset()
    two = {"sensor.a": sensor("34.46"), "sensor.b": sensor("34.54"), "sensor.c": sensor("30.25")}
    assert mirrors(two, dict.fromkeys(two, MIRROR_DEVICE)) == frozenset()
    two["sensor.d"] = sensor("14.7", "L/min")
    assert mirrors(two, dict.fromkeys(two, MIRROR_DEVICE)) == {MIRROR_DEVICE}


def test_values_that_many_pump_signals_share_prove_nothing() -> None:
    """Devices with values that many pump signals share, such as zeros, are not flagged."""
    index = {
        "sensor.plug_power": sensor("0", "W"),
        "sensor.plug_current": sensor("0.0", "A"),
        "sensor.plug_energy": sensor("0.00", "kWh"),
        "sensor.plug_outlet_copy": sensor("34.5"),
    }
    assert mirrors(index, dict.fromkeys(index, "plug")) == frozenset()


def test_entities_without_a_device_are_never_flagged() -> None:
    """Entities without a device, or spread over different devices, are never flagged."""
    index = {
        "sensor.hp_outlet": sensor("34.5"),
        "sensor.hp_inlet": sensor("30.25"),
        "sensor.hp_flow": sensor("14.7", "L/min"),
    }
    assert mirrors(index, {}) == frozenset()
    spread = {"sensor.hp_outlet": "a", "sensor.hp_inlet": "b", "sensor.hp_flow": "c"}
    assert mirrors(index, spread) == frozenset()


def test_without_heishamon_values_nothing_is_flagged() -> None:
    """Without HeishaMon values, or with only Home Assistant values, nothing is flagged."""
    index = {
        "sensor.hp_outlet": sensor("34.5"),
        "sensor.hp_inlet": sensor("30.25"),
        "sensor.hp_flow": sensor("14.7", "L/min"),
    }
    devices = dict.fromkeys(index, MIRROR_DEVICE)
    assert mirrors(index, devices, {}) == frozenset()
    ha_only = {f"ha/{entity}": float(state.state) for entity, state in index.items()}
    assert mirrors(index, devices, ha_only) == frozenset()


@pytest.fixture
def candidates(make_settings: Callable[..., Settings]) -> dict[str, Any]:
    """Build candidate lists from a fake Home Assistant that has one pump-mirror device."""
    index = {
        "sensor.panasonic_heat_pump_main_outlet_temp": sensor("34.5", name="HP outlet"),
        "sensor.panasonic_heat_pump_main_inlet_temp": sensor("30.25", name="HP inlet"),
        "sensor.panasonic_heat_pump_main_pump_flow": sensor("14.7", "L/min"),
        "climate.panasonic_heat_pump_main_z1_temp": EntityState(
            "heat", {"current_temperature": 7.0}
        ),
        "sensor.living_room_temperature": sensor("21.4", name="Living room"),
        "sensor.hallway_temperature": sensor("34.5", name="Hallway"),
    }
    devices = {entity: MIRROR_DEVICE for entity in index if "panasonic" in entity}
    devices["sensor.living_room_temperature"] = "room-sensor"
    ha = FakeHa(index, devices)
    return signal_candidates(make_settings(), runtime_with(PUMP), ha)  # type: ignore[arg-type]


def test_signal_candidates_flag_every_entity_of_a_mirror_device(
    candidates: dict[str, Any],
) -> None:
    """Every entity of a mirror device is flagged as pump_mirror in all candidate lists."""
    room = {item["signal"]: item["pump_mirror"] for item in candidates["room"]}
    assert room == {
        "ha/climate.panasonic_heat_pump_main_z1_temp#current_temperature": True,
        "ha/sensor.hallway_temperature": False,
        "ha/sensor.living_room_temperature": False,
        "ha/sensor.panasonic_heat_pump_main_inlet_temp": True,
        "ha/sensor.panasonic_heat_pump_main_outlet_temp": True,
    }
    liveness = {item["signal"]: item["pump_mirror"] for item in candidates["liveness"]}
    assert liveness["ha/sensor.panasonic_heat_pump_main_pump_flow"] is True
    crosscheck = {item["signal"]: item["pump_mirror"] for item in candidates["crosscheck"]}
    assert crosscheck["main/Room_Thermostat_Temp"] is False
    assert crosscheck["ha/sensor.panasonic_heat_pump_main_outlet_temp"] is True
