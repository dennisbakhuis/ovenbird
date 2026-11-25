"""Service settings of a harness run, isolated from the caller's environment."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ovenbird.config import Settings, load_settings
from ovenbird_core.inputs import ha_signal
from ovenbird_sim import local

HARNESS_BROKER: Final = "localhost"
ROOM_ENTITY: Final = "sensor.living_room_temperature"
HUMIDITY_ENTITY: Final = "sensor.living_room_humidity"
MQTT_ROOM_TOPIC: Final = "sim/room_temperature"
MQTT_ROOM_SIGNAL: Final = "room_temperature"
HA_URL: Final = "http://localhost:8123"
HA_TOKEN: Final = "harness-fake-home-assistant"  # noqa: S105
ISOLATED_PREFIXES: Final = ("OVENBIRD_", "SUPERVISOR_TOKEN")
EXAMPLE_COMFORT_C: Final = local.EXAMPLE_COMFORT_C
EXAMPLE_MIN_SETPOINT_C: Final = local.EXAMPLE_MIN_SETPOINT_C
EXAMPLE_CROSSCHECK: Final = "main/Room_Thermostat_Temp"


@dataclass(frozen=True, slots=True)
class Profile:
    """The user-facing settings of a run (defaults: the example installation in ``docs/design.md``).

    Parameters
    ----------
    comfort_c
        Comfort room temperature.
    min_setpoint_c
        Minimum water setpoint.
    emitter
        Emitter preset.
    pump_duty_heat, pump_duty_idle
        Max pump duty while heating and idle; ``None`` disables the pump-duty intent.
    room_via
        ``ha``: the room temperature reaches the service through the fake Home
        Assistant (the example install's path); ``mqtt``: through the board's MQTT room topic
        (the path of the service end-to-end tests).
    room_profile
        Room sensor profile (``on_change``: a send-on-delta sensor, with the
        humidity entity as liveness signal on the HA path; ``periodic``).
    room_crosscheck
        Plausibility cross-check signal (the example install's: the pump's integer
        ``main/Room_Thermostat_Temp``, which the simulated board publishes); ``None``
        disables the check.
    """

    comfort_c: float = EXAMPLE_COMFORT_C
    min_setpoint_c: float | None = EXAMPLE_MIN_SETPOINT_C
    emitter: str = "mixed"
    pump_duty_heat: int | None = local.EXAMPLE_PUMP_DUTY_HEAT
    pump_duty_idle: int = local.EXAMPLE_PUMP_DUTY_IDLE
    room_via: str = "ha"
    room_profile: str = "on_change"
    room_crosscheck: str | None = EXAMPLE_CROSSCHECK

    @property
    def room_signal(self) -> str:
        """Signal id the controller reads the room temperature from."""
        return ha_signal(ROOM_ENTITY) if self.room_via == "ha" else MQTT_ROOM_SIGNAL


@contextlib.contextmanager
def isolated_environment(options_file: Path) -> Iterator[None]:
    """Hide ``OVENBIRD_*`` variables and the Supervisor token while settings are built.

    Parameters
    ----------
    options_file
        A path that does not exist, used as ``OVENBIRD_OPTIONS_FILE``.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith(ISOLATED_PREFIXES)}
    for name in saved:
        del os.environ[name]
    os.environ["OVENBIRD_OPTIONS_FILE"] = str(options_file)
    try:
        yield
    finally:
        os.environ.pop("OVENBIRD_OPTIONS_FILE", None)
        os.environ.update(saved)


def harness_settings(data_dir: Path, profile: Profile | None = None, **overrides: Any) -> Settings:
    """Return validated settings for a stepped run in simulation mode.

    The broker is a loopback name that is never connected to; Home Assistant is a
    loopback URL that is never connected to either (the fake feeds the HA input).

    Parameters
    ----------
    data_dir
        Directory of ``history.db``.
    profile
        Owner-facing settings.
    **overrides
        Further settings fields.

    Returns
    -------
    Settings
        Settings with commands permitted (simulation mode, loopback broker) and
        history retention off, so the run's database keeps the whole span.
    """
    chosen = profile or Profile()
    values: dict[str, Any] = {
        "data_dir": data_dir,
        "ui_dir": data_dir / "ui",
        "http_port": 0,
        "mqtt_host": HARNESS_BROKER,
        "control_mode": "auto",
        "allow_commands": True,
        "command_brokers": (HARNESS_BROKER,),
        "simulation": True,
        "control_emitter": chosen.emitter,
        "control_room_signal": chosen.room_signal,
        "control_comfort_c": chosen.comfort_c,
        "control_min_setpoint_c": chosen.min_setpoint_c,
        "control_pump_duty": chosen.pump_duty_heat is not None,
        "history_snapshot_hours": None,
        "history_raw_days": None,
        "history_1m_days": None,
        "history_decision_days": None,
        "control_room_profile": chosen.room_profile,
        "control_room_crosscheck_signal": chosen.room_crosscheck,
    }
    if chosen.pump_duty_heat is not None:
        values["control_pump_duty_heat"] = chosen.pump_duty_heat
        values["control_pump_duty_idle"] = chosen.pump_duty_idle
    if chosen.room_via == "ha":
        values["ha_url"] = HA_URL
        values["ha_token"] = HA_TOKEN
        values["ha_entities"] = (ROOM_ENTITY,)
        if chosen.room_profile == "on_change":
            values["control_room_liveness_signals"] = (ha_signal(HUMIDITY_ENTITY),)
        else:
            values["ha_entities"] = (ROOM_ENTITY, HUMIDITY_ENTITY)
    else:
        values["mqtt_inputs"] = [
            {"topic": MQTT_ROOM_TOPIC, "signal": MQTT_ROOM_SIGNAL, "unit": "°C"}
        ]
    values.update(overrides)
    with isolated_environment(data_dir / "no-options.json"):
        return load_settings(**values)
