from __future__ import annotations

import pytest

from ovenbird_sim.heishamon.registers import (
    Command,
    Registers,
    duty_byte,
    json_int,
    parse_curves,
    quiet_byte,
    temperature_byte,
)


@pytest.mark.parametrize(
    ("value", "decoded"),
    [(31, 31), (127, 127), (128, -128), (300, 44), (-128, -128), (-129, 127), (0, 0)],
)
def test_temperature_byte_wraps_like_the_frame(value: int, decoded: int) -> None:
    """Temperatures wrap to a signed byte like the frame does."""
    assert temperature_byte(value) == decoded


@pytest.mark.parametrize(("value", "decoded"), [(159, 159), (102, 102), (254, 254), (255, -1)])
def test_duty_byte_wraps(value: int, decoded: int) -> None:
    """The pump duty wraps to a signed byte."""
    assert duty_byte(value) == decoded


@pytest.mark.parametrize(("value", "decoded"), [(0, 0), (1, 1), (3, 3), (4, 4), (31, -1)])
def test_quiet_byte(value: int, decoded: int) -> None:
    """The quiet mode byte keeps valid levels and maps an invalid one to -1."""
    assert quiet_byte(value) == decoded


@pytest.mark.parametrize(
    ("node", "value"),
    [(31, 31), (31.9, 31), (-2.7, -2), ("33", 33), ("33abc", 33), ("x", 0), (None, 0), (True, 1)],
)
def test_json_int_reads_integer_values(node: object, value: int) -> None:
    """Integer values are read from numbers and numeric strings, anything else as zero."""
    assert json_int(node) == value


def test_parse_curves_reads_only_present_fields() -> None:
    """Only the fields present in a set-curves payload are parsed; invalid payloads give none."""
    assert parse_curves('{"zone1":{"heat":{"target":{"high":31}}}}') == {"target_high": 31}
    assert parse_curves('{"zone1":{"heat":{"target":{"high":31.8,"low":null}}}}') == {
        "target_high": 31
    }
    assert parse_curves('{"zone1":{"heat":{"outside":{"low":-7,"high":15}}}}') == {
        "outside_low": -7,
        "outside_high": 15,
    }
    assert parse_curves("31") == {}
    assert parse_curves("{not json") == {}
    assert parse_curves('{"zone2":{"heat":{"target":{"high":31}}}}') == {}


def test_direct_mode_both_registers_write_the_direct_setpoint() -> None:
    """In direct mode both set-curves and the heat request write the direct setpoint."""
    regs = Registers(direct_setpoint=30)
    by_curve = regs.apply(Command.SET_CURVES, '{"zone1":{"heat":{"target":{"high":33}}}}')
    assert by_curve.direct_setpoint == 33
    assert by_curve.curve_target_high == 33
    assert by_curve.water_target(0.0) == 33
    by_request = regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, "28")
    assert by_request.direct_setpoint == 28
    assert by_request.curve_target_high == regs.curve_target_high
    assert by_request.topics()["Z1_Heat_Request_Temp"] == "28"


def test_no_range_check_and_integer_parsing() -> None:
    """Values are not range checked and are parsed as integers like the firmware does."""
    regs = Registers()
    assert regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, "300").direct_setpoint == 44
    assert regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, "abc").direct_setpoint == 0
    assert regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, "31.9").direct_setpoint == 31
    assert regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, " 29 °C").direct_setpoint == 29
    assert regs.apply(Command.SET_MAX_PUMP_DUTY, "102").max_pump_duty == 102
    assert regs.apply(Command.SET_MAX_PUMP_DUTY, "").max_pump_duty == 0
    assert regs.apply(Command.SET_QUIET_MODE, "2").quiet_level == 2
    invalid = regs.apply(Command.SET_CURVES, "garbage")
    assert invalid == regs


def test_compensation_mode_request_is_a_shift_on_the_curve() -> None:
    """In compensation mode the heat request is a shift on the heating curve."""
    regs = Registers(heating_mode=0, curve_target_high=34, curve_target_low=25)
    assert regs.water_target(-7.0) == 34
    assert regs.water_target(15.0) == 25
    assert regs.water_target(40.0) == 25
    shifted = regs.apply(Command.SET_Z1_HEAT_REQUEST_TEMPERATURE, "3")
    assert shifted.request_shift == 3
    assert shifted.direct_setpoint == regs.direct_setpoint
    assert shifted.water_target(-7.0) == 37
    raised = regs.apply(Command.SET_CURVES, '{"zone1":{"heat":{"target":{"high":30}}}}')
    assert raised.direct_setpoint == regs.direct_setpoint
    assert raised.water_target(-7.0) == 30
