"""Typed catalogue of the HeishaMon ``main/*`` topics the controller reads.

Units, value types and enum meanings follow HeishaMon's published topic
documentation and recorded payloads. Ranges are plausibility bounds: a payload
outside them is rejected, which keeps the "sensor absent" values HeishaMon
publishes (``-128``, ``-78``, ``-200``) out of the state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from ovenbird_core.readings import SignalId

MAIN_PREFIX: Final = "main/"


class ValueKind(StrEnum):
    """How a payload is decoded."""

    FLOAT = "float"
    INT = "int"
    ENUM = "enum"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class TopicSpec:
    """Definition of one ``main/*`` topic.

    Parameters
    ----------
    name
        Topic name below ``main/``, e.g. ``Main_Outlet_Temp``.
    kind
        Decoding of the payload.
    description
        Short human description.
    unit
        Unit of the decoded value; ``None`` for enums and text.
    minimum, maximum
        Inclusive plausibility range for numeric kinds.
    meanings
        Enum labels indexed by code (codes are ``0 .. len - 1``).
    pattern
        Regular expression a text payload must fully match.
    """

    name: str
    kind: ValueKind
    description: str
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    meanings: tuple[str, ...] = ()
    pattern: str | None = None

    @property
    def signal(self) -> SignalId:
        """Signal id of this topic (``main/<name>``)."""
        return MAIN_PREFIX + self.name

    def meaning(self, code: int) -> str | None:
        """Return the label of enum ``code``, or ``None`` when it has none."""
        return self.meanings[code] if 0 <= code < len(self.meanings) else None

    def matches(self, text: str) -> bool:
        """Whether ``text`` fully matches :attr:`pattern` (always true without one)."""
        return self.pattern is None or re.fullmatch(self.pattern, text) is not None


class HeishaSignal(StrEnum):
    """Signal ids of the catalogued HeishaMon topics."""

    OUTSIDE_TEMP = "main/Outside_Temp"
    INLET_TEMP = "main/Main_Inlet_Temp"
    OUTLET_TEMP = "main/Main_Outlet_Temp"
    MAIN_TARGET_TEMP = "main/Main_Target_Temp"
    HEX_OUTLET_TEMP = "main/Main_Hex_Outlet_Temp"
    Z1_WATER_TARGET_TEMP = "main/Z1_Water_Target_Temp"
    Z1_HEAT_REQUEST_TEMP = "main/Z1_Heat_Request_Temp"
    ROOM_THERMOSTAT_TEMP = "main/Room_Thermostat_Temp"
    DISCHARGE_TEMP = "main/Discharge_Temp"
    DEFROST_TEMP = "main/Defrost_Temp"
    OUTSIDE_PIPE_TEMP = "main/Outside_Pipe_Temp"
    INSIDE_PIPE_TEMP = "main/Inside_Pipe_Temp"
    EVA_OUTLET_TEMP = "main/Eva_Outlet_Temp"
    COMPRESSOR_FREQ = "main/Compressor_Freq"
    COMPRESSOR_CURRENT = "main/Compressor_Current"
    PUMP_FLOW = "main/Pump_Flow"
    PUMP_SPEED = "main/Pump_Speed"
    PUMP_DUTY = "main/Pump_Duty"
    MAX_PUMP_DUTY = "main/Max_Pump_Duty"
    HEAT_POWER_PRODUCTION = "main/Heat_Power_Production"
    HEAT_POWER_CONSUMPTION = "main/Heat_Power_Consumption"
    DHW_POWER_PRODUCTION = "main/DHW_Power_Production"
    DHW_POWER_CONSUMPTION = "main/DHW_Power_Consumption"
    HEATPUMP_STATE = "main/Heatpump_State"
    OPERATING_MODE_STATE = "main/Operating_Mode_State"
    HEATING_MODE = "main/Heating_Mode"
    DEFROSTING_STATE = "main/Defrosting_State"
    THREEWAY_VALVE_STATE = "main/ThreeWay_Valve_State"
    FORCE_DHW_STATE = "main/Force_DHW_State"
    QUIET_MODE_LEVEL = "main/Quiet_Mode_Level"
    HOLIDAY_MODE_STATE = "main/Holiday_Mode_State"
    ERROR = "main/Error"
    ROOM_HEATER_STATE = "main/Room_Heater_State"
    INTERNAL_HEATER_STATE = "main/Internal_Heater_State"
    EXTERNAL_HEATER_STATE = "main/External_Heater_State"
    HEATING_OFF_OUTDOOR_TEMP = "main/Heating_Off_Outdoor_Temp"
    HEATER_ON_OUTDOOR_TEMP = "main/Heater_On_Outdoor_Temp"
    HEAT_PUMP_MODEL = "main/Heat_Pump_Model"
    Z1_CURVE_TARGET_HIGH_TEMP = "main/Z1_Heat_Curve_Target_High_Temp"
    Z1_CURVE_TARGET_LOW_TEMP = "main/Z1_Heat_Curve_Target_Low_Temp"
    Z1_CURVE_OUTSIDE_HIGH_TEMP = "main/Z1_Heat_Curve_Outside_High_Temp"
    Z1_CURVE_OUTSIDE_LOW_TEMP = "main/Z1_Heat_Curve_Outside_Low_Temp"
    ZONES_STATE = "main/Zones_State"
    Z1_SENSOR_SETTINGS = "main/Z1_Sensor_Settings"
    BUFFER_INSTALLED = "main/Buffer_Installed"
    DHW_INSTALLED = "main/DHW_Installed"
    OPERATIONS_HOURS = "main/Operations_Hours"
    OPERATIONS_COUNTER = "main/Operations_Counter"
    HEAT_DELTA = "main/Heat_Delta"
    PUMP_FLOWRATE_MODE = "main/Pump_Flowrate_Mode"
    QUIET_MODE_PRIORITY = "main/Quiet_Mode_Priority"
    POWERFUL_MODE_TIME = "main/Powerful_Mode_Time"
    HEATING_CONTROL = "main/Heating_Control"
    HEATER_DELAY_TIME = "main/Heater_Delay_Time"
    HEATER_START_DELTA = "main/Heater_Start_Delta"
    HEATER_STOP_DELTA = "main/Heater_Stop_Delta"


CELSIUS: Final = "°C"
KELVIN: Final = "K"
WATT: Final = "W"
SWITCH_STATES: Final = ("off", "on")
RUNNING_STATES: Final = ("inactive", "active")
INSTALLED_STATES: Final = ("disabled", "enabled")
ERROR_PATTERN: Final = r"No error|[HF][0-9A-F]{2,8}"
MODEL_PATTERN: Final = r"(?:[0-9A-F]{2} ){9}[0-9A-F]{2}"


def _temp(
    name: str, description: str, low: float, high: float, *, fractional: bool = False
) -> TopicSpec:
    """Return a temperature topic spec in °C (whole degrees unless ``fractional``).

    Parameters
    ----------
    name
        HeishaMon topic name.
    description
        What the topic reports.
    low
        Lowest plausible value in °C.
    high
        Highest plausible value in °C.
    fractional
        Whether the topic carries decimals instead of whole degrees.
    """
    kind = ValueKind.FLOAT if fractional else ValueKind.INT
    return TopicSpec(name, kind, description, CELSIUS, low, high)


def _int(name: str, description: str, unit: str | None, low: float, high: float) -> TopicSpec:
    """Return an integer topic spec with the plausible range ``low`` to ``high``.

    Parameters
    ----------
    name
        HeishaMon topic name.
    description
        What the topic reports.
    unit
        Unit of the value, ``None`` for a dimensionless topic.
    low
        Lowest plausible value, in ``unit``.
    high
        Highest plausible value, in ``unit``.
    """
    return TopicSpec(name, ValueKind.INT, description, unit, low, high)


def _float(name: str, description: str, unit: str | None, low: float, high: float) -> TopicSpec:
    """Return a decimal topic spec with the plausible range ``low`` to ``high``.

    Parameters
    ----------
    name
        HeishaMon topic name.
    description
        What the topic reports.
    unit
        Unit of the value, ``None`` for a dimensionless topic.
    low
        Lowest plausible value, in ``unit``.
    high
        Highest plausible value, in ``unit``.
    """
    return TopicSpec(name, ValueKind.FLOAT, description, unit, low, high)


def _enum(name: str, description: str, meanings: tuple[str, ...]) -> TopicSpec:
    """Return an enumerated topic spec described by its ``meanings``."""
    return TopicSpec(name, ValueKind.ENUM, description, meanings=meanings)


def _text(name: str, description: str, pattern: str) -> TopicSpec:
    """Return a text topic spec whose payload must match the regex ``pattern``."""
    return TopicSpec(name, ValueKind.TEXT, description, pattern=pattern)


_SPECS: Final[tuple[TopicSpec, ...]] = (
    _temp("Outside_Temp", "Outside ambient temperature (integer)", -40, 50),
    _temp("Main_Inlet_Temp", "Water inlet (return) temperature", -20, 90, fractional=True),
    _temp("Main_Outlet_Temp", "Water outlet (supply) temperature", -20, 90, fractional=True),
    _temp("Main_Target_Temp", "Outlet water target temperature", -10, 90),
    _temp("Main_Hex_Outlet_Temp", "Water temperature after the heat exchanger", -20, 90),
    _temp("Z1_Water_Target_Temp", "Zone 1 water target temperature", -10, 90),
    _temp("Z1_Heat_Request_Temp", "Zone 1 heat request: shift (-5..5) or direct target", -5, 90),
    _temp("Room_Thermostat_Temp", "Remote control thermostat temperature", -30, 60),
    _temp("Discharge_Temp", "Compressor discharge temperature", -40, 150),
    _temp("Defrost_Temp", "Defrost sensor temperature", -50, 80),
    _temp("Outside_Pipe_Temp", "Outdoor coil pipe temperature", -50, 80),
    _temp("Inside_Pipe_Temp", "Indoor refrigerant pipe temperature", -50, 120),
    _temp("Eva_Outlet_Temp", "Evaporator outlet temperature", -50, 80),
    _int("Compressor_Freq", "Compressor frequency", "Hz", 0, 150),
    _float("Compressor_Current", "Outdoor unit current", "A", 0, 60),
    _float("Pump_Flow", "Water pump flow", "l/min", 0, 100),
    _int("Pump_Speed", "Water pump rotation speed", "r/min", 0, 12700),
    _int("Pump_Duty", "Water pump duty", None, 0, 254),
    _int("Max_Pump_Duty", "Configured maximum water pump duty", None, 0, 254),
    _int("Heat_Power_Production", "Pump estimate of heating heat output", WATT, 0, 50800),
    _int("Heat_Power_Consumption", "Pump estimate of heating electrical input", WATT, 0, 50800),
    _int("DHW_Power_Production", "Pump estimate of DHW heat output", WATT, 0, 50800),
    _int("DHW_Power_Consumption", "Pump estimate of DHW electrical input", WATT, 0, 50800),
    _enum("Heatpump_State", "Heat pump on/off", SWITCH_STATES),
    _enum(
        "Operating_Mode_State",
        "Operating mode",
        (
            "heat",
            "cool",
            "auto_heat",
            "dhw",
            "heat_dhw",
            "cool_dhw",
            "auto_heat_dhw",
            "auto_cool",
            "auto_cool_dhw",
        ),
    ),
    _enum("Heating_Mode", "Heating setpoint mode", ("compensation_curve", "direct")),
    _enum("Defrosting_State", "Defrost running", SWITCH_STATES),
    _enum("ThreeWay_Valve_State", "Three-way valve position", ("room", "dhw")),
    _enum("Force_DHW_State", "Forced DHW", SWITCH_STATES),
    _enum("Quiet_Mode_Level", "Quiet mode level", ("off", "level_1", "level_2", "level_3")),
    _enum("Holiday_Mode_State", "Holiday mode", ("off", "scheduled", "active")),
    _text("Error", "Last active pump error code", ERROR_PATTERN),
    _enum("Room_Heater_State", "Backup heater allowed for room heating", ("blocked", "free")),
    _enum("Internal_Heater_State", "Internal backup heater running", RUNNING_STATES),
    _enum("External_Heater_State", "External backup heater running", RUNNING_STATES),
    _temp("Heating_Off_Outdoor_Temp", "Outdoor temperature above which heating stops", 5, 35),
    _temp("Heater_On_Outdoor_Temp", "Outdoor temperature below which the heater may run", -20, 25),
    _text("Heat_Pump_Model", "Model identification bytes", MODEL_PATTERN),
    _temp("Z1_Heat_Curve_Target_High_Temp", "Zone 1 curve water target at the cold end", -10, 90),
    _temp("Z1_Heat_Curve_Target_Low_Temp", "Zone 1 curve water target at the warm end", -10, 90),
    _temp("Z1_Heat_Curve_Outside_High_Temp", "Zone 1 curve outside temperature, cold end", -30, 40),
    _temp("Z1_Heat_Curve_Outside_Low_Temp", "Zone 1 curve outside temperature, warm end", -30, 40),
    _enum("Zones_State", "Active zones", ("zone1", "zone2", "zone1_and_zone2")),
    _enum(
        "Z1_Sensor_Settings",
        "Zone 1 control sensor",
        ("water_temperature", "external_thermostat", "internal_thermostat", "thermistor"),
    ),
    _enum("Buffer_Installed", "Buffer tank installed", INSTALLED_STATES),
    _enum("DHW_Installed", "DHW tank installed", INSTALLED_STATES),
    _int("Operations_Hours", "Compressor operating hours", "h", 0, 1_000_000),
    _int("Operations_Counter", "Compressor starts", None, 0, 100_000_000),
    _int("Heat_Delta", "Heating delta T setting", KELVIN, -20, 20),
    _enum("Pump_Flowrate_Mode", "Water pump flow-rate mode", ("delta_t", "max_flow")),
    _enum("Quiet_Mode_Priority", "Quiet mode priority", ("sound", "capacity")),
    _enum("Powerful_Mode_Time", "Powerful mode duration", ("off", "30_min", "60_min", "90_min")),
    _enum("Heating_Control", "Heating control priority", ("comfort", "efficiency")),
    _int("Heater_Delay_Time", "Backup heater start delay", "min", 0, 254),
    _int("Heater_Start_Delta", "Backup heater start delta", KELVIN, -20, 20),
    _int("Heater_Stop_Delta", "Backup heater stop delta", KELVIN, -20, 20),
)

CATALOGUE: Final[MappingProxyType[SignalId, TopicSpec]] = MappingProxyType(
    {spec.signal: spec for spec in _SPECS}
)
