from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import (
    ConfigError,
    Settings,
    is_simulation_broker,
    load_settings,
    normalise_broker,
)
from ovenbird.control.guard import CommandsRefusedError, PublishGuard, broker_listed
from ovenbird_core.control import Mode

ALL_THREE = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}


def test_defaults_never_publish(make_settings: Callable[..., Settings]) -> None:
    """By default nothing is permitted and all three conditions are reported as refused."""
    settings = make_settings()
    assert settings.control_mode == "shadow"
    assert settings.allow_commands is False
    assert settings.command_brokers == ()
    guard = PublishGuard.from_settings(settings)
    assert not guard.permits
    assert len(guard.refusals()) == 3


def test_all_three_conditions_permit(make_settings: Callable[..., Settings]) -> None:
    """Auto mode, allowed commands and a listed broker together permit publishing."""
    guard = PublishGuard.from_settings(make_settings(**ALL_THREE))
    assert guard.permits
    assert guard.refusals() == ()
    guard.require()


@pytest.mark.parametrize(
    ("missing", "value", "fragment"),
    [
        ("control_mode", "shadow", "control mode is shadow"),
        ("control_mode", "off", "control mode is off"),
        ("allow_commands", False, "OVENBIRD_ALLOW_COMMANDS"),
        ("command_brokers", (), "not in OVENBIRD_COMMAND_BROKERS"),
        ("mqtt_host", "core-mosquitto", "not in OVENBIRD_COMMAND_BROKERS"),
    ],
)
def test_each_condition_is_required(
    make_settings: Callable[..., Settings], missing: str, value: object, fragment: str
) -> None:
    """Removing any one of the three conditions refuses publishing with its own reason."""
    guard = PublishGuard.from_settings(make_settings(**{**ALL_THREE, missing: value}))
    assert not guard.permits
    (reason,) = guard.refusals()
    assert fragment in reason
    with pytest.raises(CommandsRefusedError, match=fragment):
        guard.require()


@pytest.mark.parametrize(
    ("host", "port", "entries", "listed"),
    [
        ("mosquitto", 1883, {"mosquitto"}, True),
        ("Mosquitto", 1883, {"mosquitto"}, True),
        ("mosquitto", 1883, {"mosquitto:1883"}, True),
        ("mosquitto", 1884, {"mosquitto:1883"}, False),
        ("mosquitto.lan", 1883, {"mosquitto"}, False),
        ("192.168.1.5", 1883, {"mosquitto"}, False),
        ("localhost", 1883, {"127.0.0.1"}, False),
        ("::1", 1883, {"[::1]:1883"}, True),
        ("", 1883, {""}, False),
    ],
)
def test_broker_allowlist_is_exact(host: str, port: int, entries: set[str], listed: bool) -> None:
    """A broker is listed only on an exact host, or host and port, match ignoring case."""
    assert broker_listed(host, port, frozenset(entries)) is listed


def test_guard_ignores_mode_spelling() -> None:
    """The guard permits only auto mode, not manual."""
    guard = PublishGuard(Mode.MANUAL, True, "mosquitto", 1883, frozenset({"mosquitto"}))
    assert not guard.permits


def test_command_settings_come_from_the_environment_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Command permissions are ignored in the options file and only read from the environment."""
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps(
            {
                "control_mode": "auto",
                "allow_commands": True,
                "command_brokers": ["localhost"],
                "mqtt_host": "localhost",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(options))
    settings = load_settings()
    assert settings.control_mode == "auto"
    assert settings.allow_commands is False
    assert settings.command_brokers == ()
    assert not PublishGuard.from_settings(settings).permits
    monkeypatch.setenv("OVENBIRD_ALLOW_COMMANDS", "true")
    monkeypatch.setenv("OVENBIRD_COMMAND_BROKERS", "LocalHost, localhost:1883")
    settings = load_settings()
    assert settings.command_brokers == ("localhost", "localhost:1883")
    assert PublishGuard.from_settings(settings).permits


@pytest.mark.parametrize("entry", ["mqtt://broker", "*", "a/b", "user@broker", "x:0", "x:http"])
def test_invalid_broker_entries(entry: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed broker entries are rejected by normalisation and by settings loading."""
    with pytest.raises(ValueError, match="command broker"):
        normalise_broker(entry)
    monkeypatch.setenv("OVENBIRD_COMMAND_BROKERS", entry)
    with pytest.raises(ConfigError, match="command_brokers"):
        load_settings()


def test_control_settings_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown control mode and an inverted pump duty range are config errors."""
    monkeypatch.setenv("OVENBIRD_CONTROL_MODE", "manual")
    with pytest.raises(ConfigError, match="control_mode"):
        load_settings()
    monkeypatch.delenv("OVENBIRD_CONTROL_MODE")
    monkeypatch.setenv("OVENBIRD_COMMAND_PUMP_DUTY_MIN", "150")
    monkeypatch.setenv("OVENBIRD_COMMAND_PUMP_DUTY_MAX", "100")
    with pytest.raises(ConfigError, match="pump_duty"):
        load_settings()


def test_clock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clock speed and start are parsed, and a zero speed is rejected."""
    monkeypatch.setenv("OVENBIRD_CLOCK_SPEED", "60")
    monkeypatch.setenv("OVENBIRD_CLOCK_START", "2026-11-07T00:00:00")
    settings = load_settings()
    assert settings.clock_speed == 60.0
    assert settings.clock_start is not None
    assert settings.clock_start.isoformat() == "2026-11-07T00:00:00+00:00"
    monkeypatch.setenv("OVENBIRD_CLOCK_SPEED", "0")
    with pytest.raises(ConfigError, match="clock_speed"):
        load_settings()


SIM_BASE: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}


@pytest.mark.parametrize("clock", [{"clock_speed": 60.0}, {"clock_start": "2026-11-07T00:00:00Z"}])
def test_a_scaled_clock_refuses_publishing_without_simulation(
    make_settings: Callable[..., Settings], clock: dict[str, Any]
) -> None:
    """A scaled or shifted clock refuses publishing unless simulation is on."""
    guard = PublishGuard.from_settings(make_settings(**SIM_BASE, **clock))
    assert not guard.permits
    assert any("OVENBIRD_SIMULATION" in reason for reason in guard.refusals())


def test_simulation_permits_a_scaled_clock_on_the_dev_broker(
    make_settings: Callable[..., Settings],
) -> None:
    """Simulation allows a scaled clock on the dev broker, also a local one on another port."""
    settings = make_settings(**SIM_BASE, clock_speed=60.0, simulation=True)
    assert PublishGuard.from_settings(settings).permits
    local = make_settings(
        **{**SIM_BASE, "mqtt_host": "127.0.0.1", "command_brokers": ("127.0.0.1:1884",)},
        mqtt_port=1884,
        clock_speed=60.0,
        simulation=True,
    )
    assert PublishGuard.from_settings(local).permits


def test_a_real_clock_needs_no_simulation(make_settings: Callable[..., Settings]) -> None:
    """A real clock permits publishing without simulation."""
    assert PublishGuard.from_settings(make_settings(**SIM_BASE)).permits


@pytest.mark.parametrize(
    "overrides",
    [
        {"mqtt_host": "core-mosquitto", "command_brokers": ("core-mosquitto",)},
        {"mqtt_host": "192.0.2.10", "command_brokers": ("192.0.2.10",)},
        {"command_brokers": ("mosquitto", "broker.lan")},
        {"ingress": True},
    ],
)
def test_simulation_refuses_anything_but_a_dev_broker(
    make_settings: Callable[..., Settings], overrides: dict[str, Any]
) -> None:
    """Simulation is a config error on any broker other than the dev broker or under ingress."""
    with pytest.raises(ConfigError, match="SIMULATION"):
        make_settings(**{**SIM_BASE, **overrides}, simulation=True)


def test_simulation_is_environment_only(
    make_settings: Callable[..., Settings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulation is not read from the options file, only from the environment."""
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"simulation": True, "clock_speed": 60.0}), encoding="utf-8")
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(options))
    settings = load_settings(data_dir=tmp_path / "d", ui_dir=tmp_path / "u", **SIM_BASE)
    assert settings.simulation is False
    assert settings.clock_speed == 60.0
    assert not PublishGuard.from_settings(settings).permits
    monkeypatch.setenv("OVENBIRD_SIMULATION", "true")
    assert load_settings(data_dir=tmp_path / "d", ui_dir=tmp_path / "u", **SIM_BASE).simulation


def test_guard_rechecks_the_simulation_broker() -> None:
    """The guard re-checks the broker when simulation is on and refuses a non-dev broker."""
    guard = PublishGuard(
        Mode.AUTO, True, "broker.lan", 1883, frozenset({"broker.lan"}), False, True
    )
    assert "simulation mode refuses broker broker.lan" in guard.refusals()
    assert is_simulation_broker("[::1]:1883")
    assert not is_simulation_broker("mosquitto.example")
