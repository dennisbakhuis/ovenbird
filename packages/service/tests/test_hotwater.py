"""The hot-water display setting and the pump's DHW_Installed report."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.hotwater import dhw_installed, hot_water_payload
from ovenbird.mqtt import build_router
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, inbound
from ovenbird_core import MqttMessage, StateStore


def _runtime_with(payload: str | None) -> Runtime:
    """Build a runtime that has seen the given DHW_Installed payload, or none."""
    runtime = Runtime(StateStore(), clock=FakeClock(1000.0))
    if payload is not None:
        router = build_router(Settings())
        message = inbound("panasonic_heat_pump/main/DHW_Installed", payload)
        delivery = MqttMessage(message.topic, message.payload, False, runtime.clock())
        runtime.apply(router.route(delivery))
    return runtime


@pytest.mark.parametrize(("payload", "expected"), [("1", True), ("0", False), (None, None)])
def test_the_pump_reports_whether_a_tank_is_installed(
    payload: str | None, expected: bool | None
) -> None:
    """The DHW_Installed report maps to True, False or None when unreported."""
    runtime = _runtime_with(payload)
    assert dhw_installed(runtime.store, runtime.clock()) is expected


@pytest.mark.parametrize(
    ("setting", "installed", "shown"),
    [
        ("auto", True, True),
        ("auto", False, False),
        ("auto", None, True),
        ("on", False, True),
        ("off", True, False),
        ("off", None, False),
    ],
)
def test_auto_follows_the_pump_and_unknown_shows_it(
    setting: str, installed: bool | None, shown: bool
) -> None:
    """Auto follows the pump's report and shows hot water when unknown; on and off override it."""
    assert hot_water_payload(setting, installed) == {
        "setting": setting,
        "installed": installed,
        "shown": shown,
    }


def test_the_configuration_says_whether_hot_water_is_shown(
    make_settings: Callable[..., Settings],
) -> None:
    """The config payload reflects the setting and the installed report."""
    manager = ConfigManager.open(make_settings(), FakeClock(), locked={})
    try:
        assert manager.payload()["hot_water"]["shown"] is True
        manager.dhw_installed = lambda: False
        assert manager.payload()["hot_water"] == {
            "setting": "auto",
            "installed": False,
            "shown": False,
        }
        manager.settings = make_settings(hot_water="on")
        assert manager.payload()["hot_water"]["shown"] is True
    finally:
        manager.close()


def test_the_setting_defaults_to_auto_and_rejects_other_values() -> None:
    """The hot-water setting defaults to auto and rejects unknown values."""
    assert Settings().hot_water == "auto"
    with pytest.raises(ValueError, match="hot_water"):
        Settings(hot_water="sometimes")  # type: ignore[arg-type]
