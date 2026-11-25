"""Pump settings an operator may write: the second closed allowlist of the command adapter.

The controller's own intents (:class:`~ovenbird_core.control.IntentKind`) cover the
water setpoint, the maximum pump duty and the quiet mode. Besides those, exactly three
pump settings may be written, one at a time and only on an operator's request:

- ``heat_delta``: ``SetFloorHeatDelta``, read back on ``main/Heat_Delta``, 3-10 K;
- ``pump_flowrate_mode``: ``SetPumpFlowrateMode``, ``main/Pump_Flowrate_Mode``, 0-1;
- ``heating_off_outdoor``: ``SetHeatingOffOutdoorTemp``, ``main/Heating_Off_Outdoor_Temp``,
  10-35 °C.

HeishaMon reads each payload as an integer and passes it to the pump without a range
check (``SetPumpFlowrateMode``: 1 Max flow, anything else DeltaT), so only clamped
decimal integers are ever sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.readings import SignalId


class PumpSetting(StrEnum):
    """Pump settings an operator may write (the closed allowlist)."""

    HEAT_DELTA = "heat_delta"
    PUMP_FLOWRATE_MODE = "pump_flowrate_mode"
    HEATING_OFF_OUTDOOR = "heating_off_outdoor"


@dataclass(frozen=True, slots=True)
class PumpSettingSpec:
    """How one writable pump setting is written and verified.

    Parameters
    ----------
    setting
        The setting.
    command
        HeishaMon command name (below ``<base>/commands/``).
    signal
        Read-back signal the write is verified against.
    low, high
        Inclusive integer clamp; values outside are refused, never clamped.
    unit
        Unit of the value (``None`` for an enum).
    """

    setting: PumpSetting
    command: str
    signal: SignalId
    low: int
    high: int
    unit: str | None

    def __post_init__(self) -> None:
        """Check that the clamp is ordered."""
        if self.low > self.high:
            raise ValueError("pump setting clamps must be ordered")


PUMP_SETTINGS: Final[MappingProxyType[PumpSetting, PumpSettingSpec]] = MappingProxyType(
    {
        PumpSetting.HEAT_DELTA: PumpSettingSpec(
            PumpSetting.HEAT_DELTA, "SetFloorHeatDelta", HeishaSignal.HEAT_DELTA, 3, 10, "K"
        ),
        PumpSetting.PUMP_FLOWRATE_MODE: PumpSettingSpec(
            PumpSetting.PUMP_FLOWRATE_MODE,
            "SetPumpFlowrateMode",
            HeishaSignal.PUMP_FLOWRATE_MODE,
            0,
            1,
            None,
        ),
        PumpSetting.HEATING_OFF_OUTDOOR: PumpSettingSpec(
            PumpSetting.HEATING_OFF_OUTDOOR,
            "SetHeatingOffOutdoorTemp",
            HeishaSignal.HEATING_OFF_OUTDOOR_TEMP,
            10,
            35,
            "°C",
        ),
    }
)


def pump_setting_spec(setting: PumpSetting) -> PumpSettingSpec:
    """Return the specification of ``setting``."""
    return PUMP_SETTINGS[setting]
