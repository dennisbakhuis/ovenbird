"""The three operator pump settings on the simulated board, parsed as HeishaMon parses them."""

from __future__ import annotations

import pytest

from ovenbird_core import PUMP_SETTINGS, PumpSetting
from ovenbird_sim.heishamon.registers import Command, Registers


@pytest.mark.parametrize(
    ("payload", "expected"),
    [("4", 4), ("10", 10), ("7.9", 7), ("abc", 0), ("-3", -3), ("200", -56), ("-128", 5)],
)
def test_floor_heat_delta_follows_the_frame_byte(payload: str, expected: int) -> None:
    """The floor heat delta is the signed frame byte of the payload."""
    registers = Registers(heat_delta=5).apply(Command.SET_FLOOR_HEAT_DELTA, payload)
    assert registers.heat_delta == expected
    assert registers.topics()["Heat_Delta"] == str(expected)


@pytest.mark.parametrize(
    ("payload", "expected"), [("1", 1), ("0", 0), ("2", 0), ("x", 0), ("1.7", 1)]
)
def test_flowrate_mode_is_max_flow_only_for_one(payload: str, expected: int) -> None:
    """The pump flow rate mode is maximum flow only for the payload one."""
    registers = Registers(pump_flowrate_mode=1).apply(Command.SET_PUMP_FLOWRATE_MODE, payload)
    assert registers.pump_flowrate_mode == expected
    assert registers.topics()["Pump_Flowrate_Mode"] == str(expected)


@pytest.mark.parametrize(("payload", "expected"), [("16", 16), ("35", 35), ("-128", 20)])
def test_heating_off_outdoor_temp_follows_the_frame_byte(payload: str, expected: int) -> None:
    """The heating-off outdoor temperature is the signed frame byte of the payload."""
    registers = Registers().apply(Command.SET_HEATING_OFF_OUTDOOR_TEMP, payload)
    assert registers.heating_off_outdoor == expected
    assert registers.topics()["Heating_Off_Outdoor_Temp"] == str(expected)


def test_the_board_knows_every_allowlisted_command_and_topic() -> None:
    """Every allow-listed pump setting has a command and a main topic on the board."""
    topics = Registers().topics()
    for spec in PUMP_SETTINGS.values():
        assert Command(spec.command).value == spec.command
        assert spec.signal.removeprefix("main/") in topics
    assert set(PUMP_SETTINGS) == set(PumpSetting)
