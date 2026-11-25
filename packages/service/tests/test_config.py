from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ovenbird.config import ConfigError, Settings, is_loopback, load_settings


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("127.0.0.53", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.0.2.10", False),
        ("example.org", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected


def test_defaults_are_valid_and_loopback() -> None:
    settings = load_settings()
    assert settings.http_host == "127.0.0.1"
    assert settings.heishamon_base == "panasonic_heat_pump"
    assert settings.data_dir == Path("/data")
    assert settings.ui_dir == Path("/opt/ovenbird/ui")
    assert not settings.ha_enabled
    assert not settings.auth_required
    assert settings.history_raw_days == 14
    assert settings.history_1m_days == 90
    assert settings.history_15m_days is None
    assert settings.history_1h_days is None


def test_refuses_non_loopback_bind_without_admin_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HTTP_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="OVENBIRD_ADMIN_PASSWORD"):
        load_settings()
    monkeypatch.setenv("OVENBIRD_ADMIN_PASSWORD", "s3cret-pw")
    settings = load_settings()
    assert settings.auth_required
    assert settings.http_host == "0.0.0.0"


def test_empty_admin_password_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("OVENBIRD_ADMIN_PASSWORD", "")
    with pytest.raises(ConfigError):
        load_settings()


def test_env_lists_and_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://ha.local:8123")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "tok")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.a_temp, sensor.b_temp,sensor.a_temp")
    monkeypatch.setenv(
        "OVENBIRD_MQTT_INPUTS",
        json.dumps([{"topic": "home/room/temp", "unit": "°C", "minimum": -10, "maximum": 45}]),
    )
    settings = load_settings()
    assert settings.ha_enabled
    assert settings.ha_entities == ("sensor.a_temp", "sensor.b_temp")
    signals = settings.mqtt_signals()
    assert signals["home/room/temp"].signal == "mqtt/home/room/temp"
    assert signals["home/room/temp"].maximum == 45


def test_entities_as_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HA_URL", "https://ha.example")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "tok")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", '["sensor.x"]')
    assert load_settings().ha_entities == ("sensor.x",)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"OVENBIRD_HA_URL": "http://ha:8123"}, "ha_token is missing"),
        ({"OVENBIRD_HA_TOKEN": "tok"}, "ha_url is missing"),
        ({"OVENBIRD_HA_URL": "ftp://ha", "OVENBIRD_HA_TOKEN": "t"}, "ha_url"),
        ({"OVENBIRD_HA_URL": "http://me:pw@ha:8123", "OVENBIRD_HA_TOKEN": "t"}, "user name"),
        ({"OVENBIRD_HA_URL": "http://ha:8123/?x=1", "OVENBIRD_HA_TOKEN": "t"}, "query"),
        ({"OVENBIRD_HA_URL": "http://ha:99999", "OVENBIRD_HA_TOKEN": "t"}, "port"),
        ({"OVENBIRD_HA_ENTITIES": "Sensor Bad"}, "not an entity id"),
        ({"OVENBIRD_HEISHAMON_BASE": "panasonic/#"}, "wildcards"),
        ({"OVENBIRD_MQTT_PORT": "70000"}, "mqtt_port"),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "a/+/b"}]'}, "wildcards"),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "a\\u0000b"}]'}, "control characters"),
        ({"OVENBIRD_HEISHAMON_BASE": "pana\tsonic"}, "control characters"),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "a"}, {"topic": "a"}]'}, "twice"),
        (
            {"OVENBIRD_MQTT_INPUTS": '[{"topic": "garden/temp", "signal": "main/Outside_Temp"}]'},
            "reserved",
        ),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "g", "signal": "ha/sensor.t"}]'}, "reserved"),
        (
            {"OVENBIRD_MQTT_INPUTS": '[{"topic": "panasonic_heat_pump/main/Outside_Temp"}]'},
            "HeishaMon board",
        ),
        (
            {"OVENBIRD_MQTT_INPUTS": '[{"topic": "panasonic_heat_pump/commands/SetHeatpump"}]'},
            "HeishaMon board",
        ),
        (
            {"OVENBIRD_MQTT_INPUTS": json.dumps([{"topic": t, "signal": "x"} for t in "ab"])},
            "another",
        ),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "a", "minimum": "inf"}]'}, "finite"),
        ({"OVENBIRD_MQTT_INPUTS": '[{"topic": "a", "minimum": 5, "maximum": 1}]'}, "above"),
        ({"OVENBIRD_LOG_LEVEL": "chatty"}, "log_level"),
    ],
)
def test_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=message):
        load_settings()


def test_ha_needs_no_entity_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://192.0.2.10:8123")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "t")
    settings = load_settings()
    assert settings.ha_enabled
    assert settings.ha_entities == ()
    assert settings.ha_subscriptions == ()


def test_ha_subscriptions_follow_the_signal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HA_URL", "https://ha.example/prefix")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "t")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.extra")
    settings = load_settings(
        control_room_signal="ha/climate.living#current_temperature",
        control_room_profile="on_change",
        control_room_liveness_signals=("ha/sensor.living_humidity",),
        control_room_crosscheck_signal="main/Room_Thermostat_Temp",
        control_stove_reference_signal="ha/sensor.hall_temperature",
    )
    assert settings.ha_signals == (
        "ha/climate.living#current_temperature",
        "ha/sensor.living_humidity",
        "ha/sensor.hall_temperature",
    )
    assert settings.ha_subscriptions == (
        "sensor.extra",
        "sensor.living_humidity",
        "sensor.hall_temperature",
    )
    assert settings.ha_attributes == (("climate.living", "current_temperature"),)
    assert settings.ha_temperature_signals == frozenset(
        {"ha/climate.living#current_temperature", "ha/sensor.hall_temperature"}
    )


@pytest.mark.parametrize(
    "signal",
    ["ha/climate.living#temperature", "ha/sensor.living#current_temperature", "ha/Climate.x"],
)
def test_unsupported_ha_signals_are_refused(monkeypatch: pytest.MonkeyPatch, signal: str) -> None:
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://ha:8123")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "t")
    with pytest.raises(ConfigError, match="room signal"):
        load_settings(control_room_signal=signal)


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_LOG_LEVEL", "debug")
    assert load_settings().log_level == "DEBUG"


def test_options_file_and_env_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps({"mqtt_host": "broker.lan", "mqtt_port": 1884, "unrelated_option": True}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(options))
    settings = load_settings()
    assert (settings.mqtt_host, settings.mqtt_port) == ("broker.lan", 1884)
    monkeypatch.setenv("OVENBIRD_MQTT_PORT", "1999")
    assert load_settings().mqtt_port == 1999
    assert load_settings(mqtt_port=2000).mqtt_port == 2000


def test_malformed_options_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    options = tmp_path / "options.json"
    options.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(options))
    with pytest.raises(ConfigError, match="cannot read settings"):
        load_settings()


def test_secrets_never_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_MQTT_PASSWORD", "mqtt-hunter2")
    monkeypatch.setenv("OVENBIRD_ADMIN_PASSWORD", "admin-hunter2")
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://ha:8123")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "token-hunter2")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.x")
    settings = load_settings()
    rendered = " ".join([repr(settings), str(settings), str(settings.summary())])
    assert "hunter2" not in rendered
    assert settings.summary()["mqtt_password"] == "set"
    assert settings.summary()["ha_token"] == "set"
    monkeypatch.setenv("OVENBIRD_HTTP_PORT", "admin-hunter2-not-a-port")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "hunter2" not in str(excinfo.value)


def test_factory_settings(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    settings = make_settings()
    assert settings.history_path == tmp_path / "data" / "history.db"


def write_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: dict[str, object]
) -> None:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(path))


def test_app_options_file_maps_to_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_options(
        tmp_path,
        monkeypatch,
        {
            "mqtt_host": "core-mosquitto",
            "mqtt_port": 1883,
            "mqtt_username": "heat",
            "mqtt_password": "pw",
            "heishamon_base": "panasonic_heat_pump",
            "ha_entities": ["sensor.room_temperature"],
            "log_level": "debug",
        },
    )
    settings = load_settings()
    assert settings.mqtt_host == "core-mosquitto"
    assert settings.mqtt_username == "heat"
    assert settings.ha_entities == ("sensor.room_temperature",)
    assert settings.log_level == "DEBUG"
    assert not settings.ingress_mode


def test_app_options_with_unset_optionals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_options(
        tmp_path,
        monkeypatch,
        {"mqtt_username": None, "mqtt_password": None, "ha_entities": None, "admin_password": ""},
    )
    settings = load_settings()
    assert settings.ha_entities == ()
    assert not settings.auth_required


def test_ingress_mode_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_INGRESS", "true")
    settings = load_settings()
    assert settings.ingress_mode
    assert settings.http_host == "0.0.0.0"
    assert settings.auth_required
    assert settings.trusted_sources == frozenset({"172.30.32.2"})
    assert not settings.ha_enabled


def test_ingress_mode_from_supervisor_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    settings = load_settings()
    assert settings.ingress_mode
    assert settings.ha_enabled
    assert settings.ha_url == "http://supervisor/core"


def test_ingress_mode_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setenv("OVENBIRD_INGRESS", "false")
    settings = load_settings()
    assert not settings.ingress_mode
    assert settings.http_host == "127.0.0.1"
    assert settings.trusted_sources == frozenset()


def test_ingress_mode_uses_supervisor_proxy_for_ha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.room_temperature")
    settings = load_settings()
    assert settings.ha_enabled
    assert settings.ha_url == "http://supervisor/core"
    assert settings.ha_token is not None
    assert settings.ha_token.get_secret_value() == "sup-token"
    assert "sup-token" not in str(settings.summary())


def test_explicit_ha_url_wins_over_supervisor_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.room_temperature")
    monkeypatch.setenv("OVENBIRD_HA_URL", "http://ha.local:8123")
    monkeypatch.setenv("OVENBIRD_HA_TOKEN", "llat")
    settings = load_settings()
    assert settings.ha_url == "http://ha.local:8123"


def test_ingress_mode_keeps_explicit_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_INGRESS", "true")
    monkeypatch.setenv("OVENBIRD_HTTP_HOST", "10.0.0.5")
    assert load_settings().http_host == "10.0.0.5"


def test_ingress_mode_supervisor_proxy_websocket_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from ovenbird.ha import websocket_url

    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setenv("OVENBIRD_HA_ENTITIES", "sensor.room_temperature")
    settings = load_settings()
    assert settings.ha_url is not None
    assert websocket_url(settings.ha_url) == "ws://supervisor/core/websocket"


@pytest.mark.parametrize("username", ["", "  "])
def test_empty_mqtt_username_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, username: str
) -> None:
    write_options(tmp_path, monkeypatch, {"mqtt_username": username, "mqtt_password": ""})
    settings = load_settings()
    assert settings.mqtt_username is None
    assert settings.mqtt_password is None


def test_allowed_origins_are_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "OVENBIRD_HTTP_ALLOWED_ORIGINS",
        "HTTPS://HA.Example:443, http://ha.local:8123/, http://[::1]:8099",
    )
    settings = load_settings()
    assert settings.http_allowed_origins == (
        "https://ha.example",
        "http://ha.local:8123",
        "http://[::1]:8099",
    )


@pytest.mark.parametrize(
    "origin", ["ftp://x", "https://ha.example/path", "https://user@ha.example", "ha.example"]
)
def test_invalid_allowed_origin(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("OVENBIRD_HTTP_ALLOWED_ORIGINS", origin)
    with pytest.raises(ConfigError, match="http_allowed_origins"):
        load_settings()


def test_snapshot_settings(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    settings = make_settings()
    assert settings.history_snapshot_hours == 6.0
    assert settings.snapshot_path == tmp_path / "data" / "history.snapshot.db"
    assert make_settings(history_snapshot_hours=None).history_snapshot_hours is None
