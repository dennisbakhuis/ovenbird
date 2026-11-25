"""Pump registers behind a simulated HeishaMon and how commands change them.

HeishaMon forwards commands to the pump without any range check: a payload is
read as an integer (``SetCurves`` takes the integer value of each JSON number)
and the pump reports the stored value at the next query. Each value is stored
in one signed or offset byte, so an out-of-range value wraps around; the
simulator models that wrap per command:

- temperatures (``SetZ1HeatRequestTemperature``, ``SetCurves``, ``SetFloorHeatDelta``,
  ``SetHeatingOffOutdoorTemp``): one signed byte, -128..127;
- ``SetMaxPumpDuty``: one byte, -1..254;
- ``SetQuietMode``: five bits, -1..30;
- ``SetFloorHeatDelta`` and ``SetHeatingOffOutdoorTemp`` (reported as ``Heat_Delta``
  and ``Heating_Off_Outdoor_Temp``): a value of -128 changes nothing;
- ``SetPumpFlowrateMode``: ``1`` selects Max flow, any other number DeltaT
  (reported as ``Pump_Flowrate_Mode`` 1 / 0).

What the pump itself does with a nonsensical value is unknown; the simulator
applies the decoded value as is.

Setpoint semantics (an assumption until the phase-3 spike settles it): in Direct
mode (``Heating_Mode`` = 1) the pump keeps one direct water setpoint. ``SetCurves``
``zone1.heat.target.high`` and ``SetZ1HeatRequestTemperature`` both write it (the
former also stores the curve register). In compensation mode the request is a
shift of -5..5 K added to the stored curve.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
from typing import Any, Final

from climate_manager_capture.heishamon import to_int

BYTE: Final = 0xFF
DIRECT_MODE: Final = 1
COMPENSATION_MODE: Final = 0
HEAT_OPERATING_MODE: Final = 0
INT32_MIN: Final = -(2**31)
INT32_MAX: Final = 2**31 - 1
STATE_SCHEMA: Final = 1


class Command(StrEnum):
    """Commands the simulator implements (the rest are ignored)."""

    SET_CURVES = "SetCurves"
    SET_Z1_HEAT_REQUEST_TEMPERATURE = "SetZ1HeatRequestTemperature"
    SET_MAX_PUMP_DUTY = "SetMaxPumpDuty"
    SET_QUIET_MODE = "SetQuietMode"
    SET_FLOOR_HEAT_DELTA = "SetFloorHeatDelta"
    SET_PUMP_FLOWRATE_MODE = "SetPumpFlowrateMode"
    SET_HEATING_OFF_OUTDOOR_TEMP = "SetHeatingOffOutdoorTemp"


def temperature_byte(value: int) -> int:
    """Wrap a temperature into one signed byte."""
    return ((value + 128) & BYTE) - 128


def kept_temperature_byte(value: int, current: int) -> int:
    """Wrap a setting into one signed byte; -128 leaves ``current`` unchanged."""
    if (value + 128) & BYTE == 0:
        return current
    return temperature_byte(value)


def flowrate_mode(value: int) -> int:
    """Map ``SetPumpFlowrateMode``: ``1`` is Max flow (1), anything else DeltaT (0)."""
    return 1 if value == 1 else 0


def duty_byte(value: int) -> int:
    """Wrap a pump duty into one byte, -1..254."""
    return ((value + 1) & BYTE) - 1


def quiet_byte(value: int) -> int:
    """Wrap a quiet level into five bits, -1..30."""
    return ((value + 1) & 0b11111) - 1


def json_int(node: Any) -> int:
    """Integer value of a JSON node: numbers truncate, numeric strings parse, else 0."""
    if isinstance(node, bool):
        return int(node)
    if isinstance(node, int):
        return node if INT32_MIN <= node <= INT32_MAX else 0
    if isinstance(node, float):
        return int(node) if math.isfinite(node) and INT32_MIN <= node <= INT32_MAX else 0
    if isinstance(node, str):
        return to_int(node)
    return 0


def _path(document: Any, *keys: str) -> Any:
    node = document
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def parse_curves(payload: str) -> dict[str, int]:
    """Return the zone 1 heat curve fields a ``SetCurves`` payload sets.

    Parameters
    ----------
    payload
        JSON text such as ``{"zone1":{"heat":{"target":{"high":31}}}}``.

    Returns
    -------
    dict
        ``target_high``, ``target_low``, ``outside_high`` and ``outside_low`` when
        present (``null`` counts as absent), decoded through the frame byte; empty
        for invalid JSON.
    """
    try:
        document = json.loads(payload)
    except ValueError, RecursionError:
        return {}
    fields: dict[str, int] = {}
    for name, keys in (
        ("target_high", ("target", "high")),
        ("target_low", ("target", "low")),
        ("outside_high", ("outside", "high")),
        ("outside_low", ("outside", "low")),
    ):
        node = _path(document, "zone1", "heat", *keys)
        if node is not None:
            fields[name] = temperature_byte(json_int(node))
    return fields


@dataclass(frozen=True, slots=True)
class Registers:
    """Pump settings as the pump stores them.

    Parameters
    ----------
    heating_mode
        0 compensation curve, 1 direct.
    operating_mode
        ``Operating_Mode_State`` (0 heat).
    direct_setpoint
        Direct-mode water setpoint.
    request_shift
        Compensation-mode shift in K.
    curve_target_high, curve_target_low
        Water temperature at the cold and the warm end of the stored curve.
    curve_outside_low, curve_outside_high
        Outside temperature of the cold and the warm end of the stored curve.
    max_pump_duty
        Maximum water pump duty.
    quiet_level
        Quiet mode level.
    heat_delta
        Heating delta-T in K (``Heat_Delta``).
    pump_flowrate_mode
        0 DeltaT, 1 Max flow (``Pump_Flowrate_Mode``).
    heating_off_outdoor
        Outdoor temperature above which heating stops (``Heating_Off_Outdoor_Temp``).
    """

    heating_mode: int = DIRECT_MODE
    operating_mode: int = HEAT_OPERATING_MODE
    direct_setpoint: int = 30
    request_shift: int = 0
    curve_target_high: int = 34
    curve_target_low: int = 25
    curve_outside_low: int = -7
    curve_outside_high: int = 15
    max_pump_duty: int = 159
    quiet_level: int = 0
    heat_delta: int = 4
    pump_flowrate_mode: int = 1
    heating_off_outdoor: int = 20

    @property
    def request_temperature(self) -> int:
        """``Z1_Heat_Request_Temp``: the direct setpoint, or the shift in compensation mode."""
        return self.direct_setpoint if self.heating_mode == DIRECT_MODE else self.request_shift

    def curve(self, outside_c: float) -> float:
        """Water temperature of the stored curve at ``outside_c`` (clamped at the ends)."""
        low, high = self.curve_outside_low, self.curve_outside_high
        if high <= low:
            return float(self.curve_target_high)
        fraction = min(max((outside_c - low) / (high - low), 0.0), 1.0)
        return self.curve_target_high + fraction * (self.curve_target_low - self.curve_target_high)

    def water_target(self, outside_c: float) -> int:
        """Water target the pump derives from its registers at outside ``outside_c``."""
        if self.heating_mode == DIRECT_MODE:
            return self.direct_setpoint
        return math.floor(self.curve(outside_c) + 0.5) + self.request_shift

    def apply(self, command: Command, payload: str) -> Registers:
        """Return the registers after the pump executed ``command``.

        Parameters
        ----------
        command
            Command name.
        payload
            Raw payload text.

        Returns
        -------
        Registers
            Updated registers.
        """
        match command:
            case Command.SET_Z1_HEAT_REQUEST_TEMPERATURE:
                value = temperature_byte(to_int(payload))
                if self.heating_mode == DIRECT_MODE:
                    return replace(self, direct_setpoint=value)
                return replace(self, request_shift=value)
            case Command.SET_CURVES:
                fields = parse_curves(payload)
                updated = replace(
                    self,
                    curve_target_high=fields.get("target_high", self.curve_target_high),
                    curve_target_low=fields.get("target_low", self.curve_target_low),
                    curve_outside_high=fields.get("outside_high", self.curve_outside_high),
                    curve_outside_low=fields.get("outside_low", self.curve_outside_low),
                )
                if self.heating_mode == DIRECT_MODE and "target_high" in fields:
                    return replace(updated, direct_setpoint=fields["target_high"])
                return updated
            case Command.SET_MAX_PUMP_DUTY:
                return replace(self, max_pump_duty=duty_byte(to_int(payload)))
            case Command.SET_QUIET_MODE:
                return replace(self, quiet_level=quiet_byte(to_int(payload)))
            case Command.SET_FLOOR_HEAT_DELTA:
                delta = kept_temperature_byte(to_int(payload), self.heat_delta)
                return replace(self, heat_delta=delta)
            case Command.SET_PUMP_FLOWRATE_MODE:
                return replace(self, pump_flowrate_mode=flowrate_mode(to_int(payload)))
            case Command.SET_HEATING_OFF_OUTDOOR_TEMP:
                off = kept_temperature_byte(to_int(payload), self.heating_off_outdoor)
                return replace(self, heating_off_outdoor=off)

    def topics(self) -> dict[str, str]:
        """Register topics keyed by ``main/*`` name (without the water target)."""
        return {
            "Heating_Mode": str(self.heating_mode),
            "Operating_Mode_State": str(self.operating_mode),
            "Z1_Heat_Request_Temp": str(self.request_temperature),
            "Z1_Heat_Curve_Target_High_Temp": str(self.curve_target_high),
            "Z1_Heat_Curve_Target_Low_Temp": str(self.curve_target_low),
            "Z1_Heat_Curve_Outside_High_Temp": str(self.curve_outside_high),
            "Z1_Heat_Curve_Outside_Low_Temp": str(self.curve_outside_low),
            "Max_Pump_Duty": str(self.max_pump_duty),
            "Quiet_Mode_Level": str(self.quiet_level),
            "Heat_Delta": str(self.heat_delta),
            "Pump_Flowrate_Mode": str(self.pump_flowrate_mode),
            "Heating_Off_Outdoor_Temp": str(self.heating_off_outdoor),
        }


def register_names() -> tuple[str, ...]:
    """Field names of :class:`Registers` (what an injection or a state file may set)."""
    return tuple(item.name for item in fields(Registers))


def registers_to_json(registers: Registers) -> str:
    """Return the state-file form of ``registers``."""
    return json.dumps({"schema": STATE_SCHEMA, "registers": asdict(registers)}, sort_keys=True)


def registers_from_json(text: str) -> Registers:
    """Parse a state file written by :func:`registers_to_json`.

    Raises
    ------
    ValueError
        When the text is not a state file of this schema or a value is not an integer.
    """
    document = json.loads(text)
    if not isinstance(document, dict) or document.get("schema") != STATE_SCHEMA:
        raise ValueError("not a simulated HeishaMon state file")
    stored = document.get("registers")
    if not isinstance(stored, dict):
        raise ValueError("state file without registers")
    values: dict[str, int] = {}
    for name in register_names():
        if name not in stored:
            continue
        value = stored[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"register {name} is not an integer")
        values[name] = value
    return replace(Registers(), **values)
