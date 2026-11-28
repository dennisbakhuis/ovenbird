from __future__ import annotations

import pytest
from pydantic import ValidationError

from ovenbird.config import Settings
from ovenbird.control import controller_config


def settings(**values: object) -> Settings:
    """Validate Settings from the given field values."""
    return Settings.model_validate(values)


def test_pump_duty_is_off_by_default() -> None:
    """The pump duty limiter is disabled unless switched on."""
    assert controller_config(settings()).pump_duty is None


def test_pump_duty_switched_on_uses_the_example_values() -> None:
    """Switching the pump duty on uses the example heat, idle and delay values."""
    duty = controller_config(settings(control_pump_duty=True)).pump_duty
    assert duty is not None
    assert (duty.heat, duty.idle, duty.idle_delay_s) == (159, 102, 300.0)


def test_pump_duty_values_are_configurable() -> None:
    """Configured pump duty values reach the controller config."""
    duty = controller_config(
        settings(
            control_pump_duty=True,
            control_pump_duty_heat=160,
            control_pump_duty_idle=100,
            control_pump_duty_idle_delay_s=60,
        )
    ).pump_duty
    assert duty is not None
    assert (duty.heat, duty.idle, duty.idle_delay_s) == (160, 100, 60.0)


def test_pump_duty_reads_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pump duty settings are read from OVENBIRD_ environment variables."""
    monkeypatch.setenv("OVENBIRD_CONTROL_PUMP_DUTY", "false")
    monkeypatch.setenv("OVENBIRD_CONTROL_PUMP_DUTY_HEAT", "150")
    loaded = Settings()
    assert loaded.control_pump_duty is False
    assert loaded.control_pump_duty_heat == 150


@pytest.mark.parametrize(
    "values",
    [
        {"control_pump_duty_heat": 90, "control_pump_duty_idle": 120},
        {"control_pump_duty_idle": 50},
        {"control_pump_duty_heat": 230},
    ],
)
def test_inconsistent_pump_duty_values_are_rejected(values: dict[str, object]) -> None:
    """Pump duty values that contradict each other or leave the allowed range are rejected."""
    with pytest.raises(ValidationError):
        settings(**values)


def test_min_setpoint_defaults_to_the_preset() -> None:
    """The minimum setpoint defaults to the preset value of 20 degC."""
    assert controller_config(settings()).safety.min_setpoint_c == 20.0


def test_min_setpoint_is_configurable() -> None:
    """A configured minimum setpoint reaches the safety config and keeps the maximum supply."""
    config = controller_config(settings(control_min_setpoint_c=26))
    assert config.safety.min_setpoint_c == 26.0
    assert config.safety.max_supply_c == controller_config(settings()).safety.max_supply_c


def test_min_setpoint_above_the_preset_maximum_is_rejected() -> None:
    """A minimum setpoint above the preset maximum supply is rejected."""
    with pytest.raises(ValueError, match="max_supply_c"):
        controller_config(settings(control_min_setpoint_c=40))
