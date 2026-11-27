"""Every validation code is documented in ``docs/api-v1.md`` with the params it carries."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.configstore import Actor, ConfigManager, ConfigRefusedError, Source
from ovenbird.configstore.effective import VALIDATION_ERRORS, VALIDATION_WARNINGS
from ovenbird.testing import FakeClock

DOC = Path(__file__).resolve().parents[3] / "docs" / "api-v1.md"
ROW = re.compile(r"^\| `([a-z_]+)` \| (error|warning)[^|]*\| ([^|]*) \|", re.MULTILINE)
NAME = re.compile(r"`([a-z_]+)`")
INPUTS = [{"topic": "room/t", "signal": "room_temperature", "unit": "°C"}]
TRIGGERS: list[tuple[str, dict[str, Any]]] = [
    ("unknown_field", {"no_such_field": 1}),
    ("not_editable", {"control_interval_s": 30}),
    ("type", {"control_comfort_c": "warm"}),
    ("missing", {"control_quiet_windows": [{"start": "22:00", "level": 1}]}),
    ("below_min", {"control_comfort_c": 1}),
    ("above_max", {"control_comfort_c": 99}),
    ("not_allowed", {"control_emitter": "underfloor"}),
    ("too_many", {"control_quiet_windows": [{"start": "22:00", "end": "06:00", "level": 1}] * 5}),
    ("clock_time", {"control_quiet_windows": [{"start": "25:00", "end": "06:00", "level": 1}]}),
    ("curve_order", {"control_curve": [[0, 34], [-10, 39]]}),
    ("curve_outside_range", {"control_curve": [[-40, 39], [15, 25]]}),
    ("curve_points", {"control_curve": [[-10, 39]]}),
    ("integral_time", {"control_feedback_ti_s": 600}),
    ("timezone", {"control_timezone": "Mars/Olympus"}),
    ("window_empty", {"control_quiet_windows": [{"start": "22:00", "end": "22:00", "level": 1}]}),
    ("room_signal_required", {"control_room_crosscheck_signal": "main/Room_Thermostat_Temp"}),
    (
        "liveness_is_room",
        {
            "control_room_signal": "room_temperature",
            "control_room_liveness_signals": ["room_temperature"],
        },
    ),
    (
        "crosscheck_is_room",
        {
            "control_room_signal": "room_temperature",
            "control_room_crosscheck_signal": "room_temperature",
        },
    ),
    ("signal_unknown", {"control_room_signal": "nowhere"}),
    ("too_long", {"mqtt_inputs": [{"topic": "garden/" + "t" * 300}]}),
    ("too_many", {"mqtt_inputs": [{"topic": f"garden/t{i}"} for i in range(33)]}),
    ("input_bounds", {"mqtt_inputs": [{"topic": "garden/t", "minimum": 30, "maximum": 10}]}),
    (
        "input_topic_reserved",
        {"mqtt_inputs": [{"topic": "panasonic_heat_pump/main/Outside_Temp", "signal": "garden"}]},
    ),
    ("input_topic_repeated", {"mqtt_inputs": [{"topic": "garden/t"}, {"topic": "garden/t"}]}),
    (
        "input_signal_reserved",
        {"mqtt_inputs": [{"topic": "garden/temp", "signal": "main/Outside_Temp"}]},
    ),
    (
        "input_signal_repeated",
        {
            "mqtt_inputs": [
                {"topic": "garden/a", "signal": "garden"},
                {"topic": "garden/b", "signal": "garden"},
            ]
        },
    ),
    ("pump_duty_order", {"control_pump_duty_idle": 170}),
    ("pump_duty_clamp", {"control_pump_duty_heat": 250}),
    (
        "stove_hysteresis",
        {"control_stove_enter_above_k": 1.0, "control_stove_exit_hysteresis_k": 1.2},
    ),
    (
        "stove_min_above_max",
        {"control_stove_min_active_s": 18_000.0, "control_stove_max_active_s": 14_400.0},
    ),
    (
        "stove_reference_is_room",
        {
            "control_room_signal": "room_temperature",
            "control_stove_reference_signal": "room_temperature",
        },
    ),
    ("min_above_max", {"control_min_setpoint_c": 40}),
    ("curve_range", {"control_curve": [[-10, 41], [15, 25]]}),
    ("outside_envelope", {"control_curve": [[-10, 39], [5, 37], [15, 25]]}),
    (
        "integral_above_output",
        {"control_feedback_integral_limit_k": 2.5, "control_feedback_output_limit_k": 2.0},
    ),
    ("ramp_below_envelope", {"control_ramp_max_below_curve_k": 8}),
    ("fixed_range", {"control_weather_compensation": False, "control_fixed_water_c": 45}),
    ("location_pair", {"weather_latitude": 52.1}),
    ("location_required", {"weather_location_source": "manual"}),
    ("max_supply_raise", {"control_max_supply_c": 45}),
    ("house_bounds_order", {"house_ua_min_w_per_k": 300, "house_ua_max_w_per_k": 200}),
    ("house_fit_days_short", {"house_learn_fit_days": 21}),
    ("model_use_on_locked", {"control_model_use": "on"}),
    ("date_format", {"house_learn_excluded_days": ["2026-13-01"]}),
    ("date_repeated", {"house_learn_excluded_days": ["2026-01-01", "2026-01-01"]}),
    ("date_future", {"house_learn_excluded_days": ["2999-01-01"]}),
    ("below_soft_min", {"control_comfort_c": 17}),
    ("above_soft_max", {"control_comfort_c": 25}),
    ("curve_shift_large", {"control_curve": [[-10, 39], [0, 37], [15, 28]]}),
    ("cycling_disabled", {"control_cycling_enabled": False}),
    ("emitter_changed", {"control_emitter": "radiators"}),
    ("weather_compensation_off", {"control_weather_compensation": False}),
    (
        "fixed_outside_envelope",
        {"control_weather_compensation": False, "control_fixed_water_c": 25},
    ),
]
NESTED_ONLY = frozenset({"unknown_field", "type"})


def documented() -> dict[str, tuple[str, frozenset[str]]]:
    text = DOC.read_text(encoding="utf-8")
    return {
        code: (kind, frozenset(NAME.findall(params))) for code, kind, params in ROW.findall(text)
    }


def test_every_code_has_a_row() -> None:
    rows = documented()
    assert set(VALIDATION_ERRORS) <= set(rows)
    assert set(VALIDATION_WARNINGS) <= set(rows)
    assert {code for code, (kind, _) in rows.items() if kind == "warning"} == set(
        VALIDATION_WARNINGS
    )


@pytest.fixture
def manager(make_settings: Callable[..., Settings]) -> ConfigManager:
    settings = make_settings(mqtt_inputs=INPUTS)
    return ConfigManager.open(settings, FakeClock(), locked={"control_dwell_s": Source.ENV})


@pytest.mark.parametrize(("code", "changes"), TRIGGERS, ids=[code for code, _ in TRIGGERS])
def test_params_match_the_documentation(
    manager: ConfigManager, code: str, changes: dict[str, Any]
) -> None:
    result = manager.validate(changes)
    found = [issue for issue in (*result.errors, *result.warnings) if issue.code == code]
    assert found, (code, result.errors, result.warnings)
    _, params = documented()[code]
    for issue in found:
        keys = set(issue.params)
        if code in NESTED_ONLY and not keys:
            continue
        assert keys == params, (code, keys, params)


def test_an_mqtt_input_cannot_stand_in_for_the_pump_outside_sensor(
    manager: ConfigManager,
) -> None:
    result = manager.validate(
        {"mqtt_inputs": [{"topic": "garden/temp", "signal": "main/Outside_Temp"}]}
    )
    assert [(issue.code, issue.params["path"]) for issue in result.errors] == [
        ("input_signal_reserved", "0.signal")
    ]


@pytest.mark.parametrize(
    "inputs",
    [
        [{"topic": "panasonic_heat_pump/1wire/28ab", "signal": "room_1wire", "unit": "°C"}],
        [{"topic": "garden/temp", "signal": "garden_temperature", "minimum": -40, "maximum": 50}],
        [{"topic": f"garden/t{i}"} for i in range(32)],
    ],
)
def test_valid_mqtt_inputs(manager: ConfigManager, inputs: list[dict[str, Any]]) -> None:
    assert manager.validate({"mqtt_inputs": inputs}).valid


def test_locked_params(manager: ConfigManager) -> None:
    (issue,) = manager.validate({"control_dwell_s": 900}).errors
    assert issue.code == "locked"
    assert set(issue.params) == documented()["locked"][1]


def test_put_only_codes_carry_their_params(manager: ConfigManager) -> None:
    clock = manager.clock
    assert isinstance(clock, FakeClock)
    with pytest.raises(ConfigRefusedError) as unacked:
        manager.apply(0, {"control_comfort_c": 25}, Actor("test"))
    errors = unacked.value.body["errors"]
    assert [e["code"] for e in errors] == ["warning_not_acknowledged"]
    assert set(errors[0]["params"]) == documented()["warning_not_acknowledged"][1]
    with pytest.raises(ConfigRefusedError) as unchanged:
        manager.apply(0, {}, Actor("test"))
    assert unchanged.value.body["errors"][0]["params"] == {}
    with pytest.raises(ConfigRefusedError) as long:
        manager.apply(0, {"control_comfort_c": 21}, Actor("test"), comment="x" * 201)
    assert long.value.body["errors"][0]["code"] == "comment_too_long"
    assert long.value.body["errors"][0]["params"] == {}
