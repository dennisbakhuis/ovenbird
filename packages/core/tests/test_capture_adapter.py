from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ovenbird_core.capture import (
    CaptureRecord,
    capture_input,
    capture_inputs,
    parse_capture_line,
    replay_results,
)
from ovenbird_core.heishamon import Heartbeat, MqttMessage
from ovenbird_core.inputs import InputRouter, MqttSignal
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, Reading, SourceKind

T = 1794528003.813


def test_parse_capture_line_reads_retained_flag() -> None:
    line = '{"t":1794528003.813,"k":"panasonic_heat_pump/main/Outside_Temp","p":"3","r":true}'
    assert parse_capture_line(line) == CaptureRecord(
        T, "panasonic_heat_pump/main/Outside_Temp", "3", True
    )
    assert parse_capture_line(line.replace(',"r":true', "")) == CaptureRecord(
        T, "panasonic_heat_pump/main/Outside_Temp", "3", False
    )


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        '{"v":1,"name":"live","started":"2026-11-13T00:00:03+00:00"}',
        "not json",
        "[1]",
        '{"t":"x","k":"a","p":"b"}',
        '{"t":true,"k":"a","p":"b"}',
        '{"t":1e300,"k":"a","p":"b"}',
        '{"t":-5,"k":"a","p":"b"}',
        '{"t":1,"k":5,"p":"b"}',
        '{"t":1,"k":"a","p":5}',
    ],
)
def test_parse_capture_line_skips_headers_and_garbage(line: str) -> None:
    assert parse_capture_line(line) is None


def test_mqtt_record_becomes_message_at_capture_instant() -> None:
    record = CaptureRecord(T, "panasonic_heat_pump/stats", "{}", True)
    assert capture_input(record) == MqttMessage(
        "panasonic_heat_pump/stats", "{}", True, Instant.from_capture(T)
    )


def test_ha_record_becomes_reading_with_reported_timestamp() -> None:
    payload = json.dumps(
        {
            "state": "20.5",
            "last_updated": "2026-11-13T00:00:00+00:00",
            "last_reported": "2026-11-13T00:00:02+00:00",
            "unit": "°C",
        }
    )
    result = capture_input(CaptureRecord(T, "ha/sensor.living_room", payload))
    assert result == Reading(
        "ha/sensor.living_room",
        20.5,
        "°C",
        Instant.from_capture(T),
        SourceKind.HA,
        False,
        datetime(2026, 11, 13, 0, 0, 2, tzinfo=UTC),
    )


def test_bad_ha_record_becomes_error() -> None:
    assert isinstance(capture_input(CaptureRecord(T, "ha/sensor.x", "{")), ParseError)


def test_snapshot_records_are_ignored() -> None:
    assert capture_input(CaptureRecord(T, "snapshot/open-meteo", "{}")) == Ignored(
        "snapshot/open-meteo", "snapshot"
    )


def test_replay_routes_mqtt_and_passes_ha_through() -> None:
    records = [
        CaptureRecord(T, "panasonic_heat_pump/stats", '{"uptime":1000}'),
        CaptureRecord(T + 1, "climate_manager_capture/room_temp", "22.3", True),
        CaptureRecord(T + 2, "ha/sensor.living_room", '{"state":"21"}'),
    ]
    router = InputRouter(
        mqtt_signals={"climate_manager_capture/room_temp": MqttSignal("room", "°C")}
    )
    results = list(replay_results(records, router))
    assert isinstance(results[0], Heartbeat)
    assert isinstance(results[1], Reading)
    assert results[1].source is SourceKind.MQTT
    assert results[1].retained is True
    assert isinstance(results[2], Reading)
    assert results[2].source is SourceKind.HA
    assert len(list(capture_inputs(records))) == 3
