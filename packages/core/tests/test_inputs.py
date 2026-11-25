from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ovenbird_core.heishamon import MqttMessage
from ovenbird_core.inputs import (
    InputRouter,
    MqttSignal,
    attribute_supported,
    ha_attribute_signal,
    ha_reading,
    ha_signal,
    parse_ha_payload,
    reserved_signal,
    split_ha_signal,
    temperature_unit,
    to_celsius,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, ParseErrorKind, Reading, SourceKind

NOW = Instant(5_000.0, datetime(2026, 11, 13, 12, 0, tzinfo=UTC))
ROOM = "sensor.living_room_temperature"


def test_ha_numeric_state_becomes_float_reading_with_source_timestamp() -> None:
    reported = datetime(2026, 11, 13, 11, 50, tzinfo=UTC)
    result = ha_reading(ROOM, "20.5", instant=NOW, unit="°C", last_reported=reported)
    assert result == Reading(
        ha_signal(ROOM), 20.5, "°C", NOW, SourceKind.HA, False, source_timestamp=reported
    )


@pytest.mark.parametrize(
    ("state", "unit", "expected"),
    [("70.0", "°F", 21.11), ("32", "℉", 0.0), ("294.65", "K", 21.5), ("21.4", "℃", 21.4)],
)
def test_ha_temperatures_are_converted_to_celsius(state: str, unit: str, expected: float) -> None:
    result = ha_reading(ROOM, state, instant=NOW, unit=unit)
    assert isinstance(result, Reading)
    assert result.value == pytest.approx(expected)
    assert result.unit == "°C"
    assert result.source_unit == unit


@pytest.mark.parametrize("unit", ["°C", None, "%", "lx"])
def test_ha_other_units_pass_unchanged(unit: str | None) -> None:
    result = ha_reading(ROOM, "21.37", instant=NOW, unit=unit)
    assert isinstance(result, Reading)
    assert (result.value, result.unit, result.source_unit) == (21.37, unit, None)


def test_ha_garbage_in_fahrenheit_stays_text() -> None:
    result = ha_reading(ROOM, "warm", instant=NOW, unit="°F")
    assert isinstance(result, Reading)
    assert (result.value, result.unit, result.source_unit) == ("warm", "°F", None)


def test_ha_attribute_reading_gets_the_attribute_signal() -> None:
    result = ha_reading(
        "climate.living", "68", instant=NOW, unit="°F", attribute="current_temperature"
    )
    assert isinstance(result, Reading)
    assert result.signal == "ha/climate.living#current_temperature"
    assert result.value == pytest.approx(20.0)


def test_ha_signal_helpers() -> None:
    signal = ha_attribute_signal("climate.living", "current_temperature")
    assert signal == "ha/climate.living#current_temperature"
    assert split_ha_signal(signal) == ("climate.living", "current_temperature")
    assert split_ha_signal(ha_signal(ROOM)) == (ROOM, None)
    assert split_ha_signal("main/Outside_Temp") is None
    assert attribute_supported("climate.living", "current_temperature")
    assert not attribute_supported("sensor.living", "current_temperature")
    assert not attribute_supported("climate.living", "temperature")
    assert temperature_unit(" °F ") == "°F"
    assert temperature_unit("%") is None
    assert temperature_unit(None) is None
    with pytest.raises(ValueError, match="not a temperature unit"):
        to_celsius(1.0, "%")


def test_ha_text_state_stays_text() -> None:
    result = ha_reading("binary_sensor.window", "on", instant=NOW)
    assert isinstance(result, Reading)
    assert result.value == "on"


@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "Unavailable"])
def test_ha_placeholder_states_are_unavailable(state: str) -> None:
    result = ha_reading(ROOM, state, instant=NOW)
    assert isinstance(result, ParseError)
    assert result.kind is ParseErrorKind.UNAVAILABLE


def test_ha_payload_prefers_last_reported_over_last_updated() -> None:
    payload = json.dumps(
        {
            "state": "21.0",
            "last_updated": "2026-11-13T10:00:00+00:00",
            "last_reported": "2026-11-13T11:59:00+00:00",
            "unit": "°C",
            "device_class": "temperature",
        }
    )
    result = parse_ha_payload(ROOM, payload, instant=NOW)
    assert isinstance(result, Reading)
    assert result.source_timestamp == datetime(2026, 11, 13, 11, 59, tzinfo=UTC)
    assert result.unit == "°C"


def test_ha_payload_falls_back_to_last_updated() -> None:
    payload = json.dumps({"state": "21.0", "last_updated": "2026-11-13T10:00:00+01:00"})
    result = parse_ha_payload(ROOM, payload, instant=NOW)
    assert isinstance(result, Reading)
    assert result.source_timestamp == datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def test_ha_payload_ignores_bad_timestamps() -> None:
    payload = json.dumps({"state": "21.0", "last_reported": "yesterday", "last_updated": 5})
    result = parse_ha_payload(ROOM, payload, instant=NOW)
    assert isinstance(result, Reading)
    assert result.source_timestamp is None


@pytest.mark.parametrize("payload", ["", "{", "[]", '{"state": 3}', '{"no": "state"}'])
def test_malformed_ha_payload(payload: str) -> None:
    result = parse_ha_payload(ROOM, payload, instant=NOW)
    assert isinstance(result, ParseError)
    assert result.kind is ParseErrorKind.MALFORMED
    assert result.signal == "ha/" + ROOM


ROOM_MIRROR = MqttSignal("room_temperature", "°C", minimum=-10, maximum=45)
ROUTER = InputRouter(mqtt_signals={"climate_manager_capture/room_temp": ROOM_MIRROR})


def message(topic: str, payload: str | bytes, retained: bool = False) -> MqttMessage:
    return MqttMessage(topic, payload, retained, NOW)


def test_router_reads_configured_plain_topics() -> None:
    result = ROUTER.route(message("climate_manager_capture/room_temp", "22.3", retained=True))
    assert result == Reading("room_temperature", 22.3, "°C", NOW, SourceKind.MQTT, True)


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ("warm", ParseErrorKind.MALFORMED),
        (b"\xff", ParseErrorKind.MALFORMED),
        ("80", ParseErrorKind.OUT_OF_RANGE),
        ("nan", ParseErrorKind.MALFORMED),
    ],
)
def test_router_rejects_bad_plain_payloads(payload: str | bytes, kind: ParseErrorKind) -> None:
    result = ROUTER.route(message("climate_manager_capture/room_temp", payload))
    assert isinstance(result, ParseError)
    assert result.kind is kind


def test_router_sends_heishamon_topics_to_the_parser() -> None:
    result = ROUTER.route(message("panasonic_heat_pump/main/Outside_Temp", "2"))
    assert isinstance(result, Reading)
    assert result.source is SourceKind.HEISHAMON


def test_router_ignores_unconfigured_topics() -> None:
    assert ROUTER.route(message("zigbee2mqtt/plug", "{}")) == Ignored(
        "zigbee2mqtt/plug", "not_configured"
    )


@pytest.mark.parametrize(
    "signal",
    [
        "main/Outside_Temp",
        "main/Anything",
        "ha/sensor.x",
        "stats",
        "LWT",
        "derived/x",
        "commands/y",
    ],
)
def test_router_never_lets_a_plain_topic_produce_a_reserved_signal(signal: str) -> None:
    router = InputRouter(mqtt_signals={"garden/temp": MqttSignal(signal, "°C")})
    assert router.route(message("garden/temp", "25")) == Ignored("garden/temp", "reserved_signal")


@pytest.mark.parametrize(
    "topic",
    [
        "panasonic_heat_pump/main/Outside_Temp",
        "panasonic_heat_pump/main",
        "panasonic_heat_pump/commands/SetZ1HeatRequestTemperature",
        "panasonic_heat_pump/stats",
        "panasonic_heat_pump/LWT",
    ],
)
def test_router_keeps_the_board_topics_for_the_parser(topic: str) -> None:
    router = InputRouter(mqtt_signals={topic: MqttSignal("garden", "°C")})
    result = router.route(message(topic, "2"))
    assert not (isinstance(result, Reading) and result.signal == "garden")


def test_router_reads_plain_inputs_in_other_board_subtrees() -> None:
    topic = "panasonic_heat_pump/1wire/28abcdef"
    router = InputRouter(mqtt_signals={topic: MqttSignal("room", "°C")})
    assert router.route(message(topic, "21.5")) == Reading(
        "room", 21.5, "°C", NOW, SourceKind.MQTT, False
    )


def test_reserved_signals() -> None:
    assert reserved_signal("main/Outside_Temp")
    assert reserved_signal("ha/sensor.room")
    assert not reserved_signal("garden_temperature")
    assert not reserved_signal("mqtt/garden/temp")
