"""The outside thermometer of the heating curve in the service: settings, loop and alarm."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ovenbird.config import ConfigError, Settings
from ovenbird.control import AlarmCode
from ovenbird.history import AlarmRow
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core import SourceKind, StateStore, ha_reading

T0 = 1_800_000_000.0
GARDEN = "sensor.garden_temperature"
GARDEN_ID = f"ha/{GARDEN}"
HA: dict[str, Any] = {
    "ha_url": "http://ha.local:8123",
    "ha_token": "token",
    "control_outside_signal": GARDEN_ID,
    "control_outside_max_age_s": 1800.0,
}


async def no_sleep(_: float) -> None:
    return None


class Journal:
    def __init__(self) -> None:
        self.alarms: list[AlarmRow] = []

    def offer_decision(self, row: Any) -> None:
        return None

    def offer_command(self, row: Any) -> None:
        return None

    def offer_alarm(self, row: AlarmRow) -> None:
        self.alarms.append(row)

    def offer_state(self, row: Any) -> None:
        return None


class Rig:
    def __init__(self, settings: Settings) -> None:
        self.clock = FakeClock(T0)
        self.runtime = Runtime(
            StateStore(settings.staleness_policy()), clock=self.clock, ha_enabled=True
        )
        self.ingest = MqttIngest(settings, self.runtime)
        self.loop, _ = build_control(
            settings,
            self.runtime,
            Journal(),  # type: ignore[arg-type]
            sleep=no_sleep,
        )

    def tick(self, minutes: int = 1, garden: float | None = None, outside: str = "8") -> None:
        for _ in range(minutes):
            for message in pump_messages(Outside_Temp=outside):
                self.ingest.ingest(message)
            if garden is not None:
                self.runtime.apply(ha_reading(GARDEN, f"{garden:.1f}", instant=self.clock()))
            self.loop.tick()
            self.clock.advance(60.0)

    @property
    def state(self) -> dict[str, Any]:
        return self.loop.latest_state or {}


def test_unset_keeps_the_pump_sensor(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.control_outside_signal is None
    assert settings.controller_config().outside is None


def test_the_signal_reaches_the_controller_and_is_subscribed(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(**HA)
    source = settings.controller_config().outside
    assert source is not None
    assert source.signal == GARDEN_ID
    assert source.max_age_s == 1800.0
    assert (source.plausible_min_c, source.plausible_max_c) == (-40.0, 50.0)
    assert source.max_deviation_k == 10.0
    assert GARDEN in settings.ha_subscriptions
    assert GARDEN_ID in settings.ha_temperature_signals


def test_the_plausibility_limits_reach_the_controller(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        **HA,
        control_outside_plausible_min_c=-30.0,
        control_outside_plausible_max_c=40.0,
        control_outside_max_deviation_k=5.0,
    )
    source = settings.controller_config().outside
    assert source is not None
    assert (source.plausible_min_c, source.plausible_max_c) == (-30.0, 40.0)
    assert source.max_deviation_k == 5.0


@pytest.mark.parametrize("limit", [600.0, 1800.0, 3600.0, 86_400.0])
def test_the_store_judges_the_outside_signal_by_its_age_limit(
    make_settings: Callable[..., Settings], limit: float
) -> None:
    policy = make_settings(**{**HA, "control_outside_max_age_s": limit}).staleness_policy()
    assert policy.max_age(GARDEN_ID, SourceKind.HA) == limit
    assert policy.max_age("ha/sensor.other", SourceKind.HA) == 1800.0


def test_the_room_profile_keeps_its_own_limit_for_a_shared_signal(
    make_settings: Callable[..., Settings],
) -> None:
    shared = {**HA, "control_room_signal": GARDEN_ID, "control_outside_max_age_s": 600.0}
    settings = make_settings(**shared)
    room_only = make_settings(**{**shared, "control_outside_signal": None})
    assert settings.staleness_policy() == room_only.staleness_policy()


def test_an_age_limit_above_the_store_default_keeps_the_sensor(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings(**{**HA, "control_outside_max_age_s": 3600.0}))
    rig.tick(garden=2.0)
    rig.tick(45)
    assert rig.state["outside_source"] == GARDEN_ID
    assert rig.state["outside_fallback"] is False
    assert not rig.loop.alarms.is_active(AlarmCode.OUTSIDE_SENSOR_STALE)
    rig.tick(20)
    assert rig.state["outside_fallback"] is True
    alarm = rig.loop.alarms.get(AlarmCode.OUTSIDE_SENSOR_STALE)
    assert alarm is not None
    assert "younger than 60 min" in alarm.message


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"ha_url": None, "ha_token": None}, "outside signal"),
        ({"control_outside_signal": "ha/switch.garden"}, "not a temperature"),
        ({"control_outside_max_age_s": 10.0}, "control_outside_max_age_s"),
        ({"control_outside_plausible_min_c": 5.0}, "control_outside_plausible_min_c"),
        ({"control_outside_plausible_max_c": 10.0}, "control_outside_plausible_max_c"),
        ({"control_outside_max_deviation_k": 0.5}, "control_outside_max_deviation_k"),
    ],
)
def test_invalid_outside_settings_are_rejected(
    make_settings: Callable[..., Settings], overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises((ConfigError, ValueError), match=match):
        make_settings(**{**HA, **overrides})


def test_a_stale_outside_sensor_falls_back_and_raises_an_alarm(
    make_settings: Callable[..., Settings],
) -> None:
    code = AlarmCode.OUTSIDE_SENSOR_STALE
    rig = Rig(make_settings(**HA))
    rig.tick(garden=2.0)
    assert rig.state["outside_source"] == GARDEN_ID
    assert rig.state["outside_fallback"] is False
    assert not rig.loop.alarms.is_active(code)
    rig.tick(31)
    assert rig.state["outside_fallback"] is True
    alarm = rig.loop.alarms.get(code)
    assert alarm is not None
    assert alarm.severity.value == "warning"
    assert GARDEN_ID in alarm.message
    assert alarm.message.startswith(f"the outside sensor {GARDEN_ID} has no value younger than")
    assert rig.state["outside_reason"] == "stale"
    rig.tick(garden=2.5)
    assert rig.state["outside_fallback"] is False
    assert rig.state["outside_reason"] is None
    assert not rig.loop.alarms.is_active(code)


@pytest.mark.parametrize(
    ("garden", "reason", "words"),
    [
        (60.0, "implausible", "reads 60 °C, outside the plausible range of -40 to 50 °C"),
        (-45.0, "implausible", "reads -45 °C, outside the plausible range of -40 to 50 °C"),
        (20.0, "deviates", "reads 20 °C, more than 10 K from the pump's own outside sensor (8 °C)"),
    ],
)
def test_a_rejected_outside_value_raises_the_implausible_alarm(
    make_settings: Callable[..., Settings], garden: float, reason: str, words: str
) -> None:
    stale, implausible = AlarmCode.OUTSIDE_SENSOR_STALE, AlarmCode.OUTSIDE_SENSOR_IMPLAUSIBLE
    rig = Rig(make_settings(**HA))
    rig.tick(garden=garden)
    assert rig.state["outside_fallback"] is True
    assert rig.state["outside_reason"] == reason
    assert not rig.loop.alarms.is_active(stale)
    alarm = rig.loop.alarms.get(implausible)
    assert alarm is not None
    assert alarm.severity.value == "warning"
    assert words in alarm.message
    assert "stale" not in alarm.message
    assert alarm.detail == {"signal": GARDEN_ID, "reason": reason}
    rig.tick(garden=7.5)
    assert rig.state["outside_fallback"] is False
    assert not rig.loop.alarms.is_active(implausible)


def test_the_two_outside_alarms_follow_the_reason(
    make_settings: Callable[..., Settings],
) -> None:
    stale, implausible = AlarmCode.OUTSIDE_SENSOR_STALE, AlarmCode.OUTSIDE_SENSOR_IMPLAUSIBLE
    rig = Rig(make_settings(**HA))
    rig.tick(garden=60.0)
    assert rig.loop.alarms.is_active(implausible)
    rig.tick(31)
    assert rig.state["outside_reason"] == "stale"
    assert rig.loop.alarms.is_active(stale)
    assert not rig.loop.alarms.is_active(implausible)
    rig.tick(garden=20.0)
    assert rig.loop.alarms.is_active(implausible)
    assert not rig.loop.alarms.is_active(stale)


def test_without_a_chosen_sensor_no_outside_keys_and_no_alarm(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings())
    rig.tick(3)
    assert "outside_source" not in rig.state
    assert "outside_reason" not in rig.state
    assert not rig.loop.alarms.is_active(AlarmCode.OUTSIDE_SENSOR_STALE)
    assert not rig.loop.alarms.is_active(AlarmCode.OUTSIDE_SENSOR_IMPLAUSIBLE)
