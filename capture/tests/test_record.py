from __future__ import annotations

import inspect
import re

import pytest

from climate_manager_capture import record
from climate_manager_capture.record import DEFAULT_TOPICS, _build_argparser, config_from_args


def test_recorder_never_sends_anything() -> None:
    source = inspect.getsource(record)
    assert not re.search(r"\.publish\(", source)
    assert "will_set" not in source


def test_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MQTT_HOST", "MQTT_PORT", "TOPICS", "CAPTURE_NAME", "MAX_HOURS"):
        monkeypatch.delenv(name, raising=False)
    config = config_from_args(_build_argparser().parse_args([]))
    assert config.host == "localhost"
    assert config.port == 1883
    assert config.topics == DEFAULT_TOPICS
    assert config.name == "live"
    assert config.max_hours is None


def test_env_fallbacks_and_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_HOST", "mqtt.example")
    monkeypatch.setenv("MQTT_PORT", "1883")
    monkeypatch.setenv("TOPICS", "#, other/#")
    monkeypatch.setenv("CAPTURE_NAME", "discovery")
    monkeypatch.setenv("MAX_HOURS", "2")
    config = config_from_args(_build_argparser().parse_args(["--port", "1884"]))
    assert config.host == "mqtt.example"
    assert config.port == 1884
    assert config.topics == ("#", "other/#")
    assert config.name == "discovery"
    assert config.max_hours == 2.0
    config = config_from_args(_build_argparser().parse_args(["--topics", "a/#"]))
    assert config.topics == ("a/#",)
