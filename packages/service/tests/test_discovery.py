from __future__ import annotations

from ovenbird.discovery import ENTITIES, STOVE_MODE, stove_state


def test_stove_mode_is_a_read_only_binary_sensor() -> None:
    config = STOVE_MODE.config()
    assert STOVE_MODE.config_topic == "homeassistant/binary_sensor/ovenbird/stove_mode/config"
    assert config["name"] == "Stove mode"
    assert config["unique_id"] == "ovenbird_stove_mode"
    assert config["state_topic"] == "ovenbird/stove_mode/state"
    assert "command_topic" not in config
    assert all(entity.component in {"binary_sensor", "sensor"} for entity in ENTITIES)


def test_stove_state() -> None:
    assert stove_state(None) == ("OFF", {})
    state, attributes = stove_state(
        {"enabled": True, "active": True, "source": "auto", "trigger": "level", "backoff_k": 3.0}
    )
    assert state == "ON"
    assert attributes["source"] == "auto"
    assert attributes["backoff_k"] == 3.0
    assert stove_state({"enabled": True, "active": False})[0] == "OFF"
