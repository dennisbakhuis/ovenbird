from __future__ import annotations

import pytest

from ovenbird_core.catalogue import CATALOGUE, HeishaSignal, ValueKind
from ovenbird_core.heishamon import (
    DEFAULT_BASE,
    Heartbeat,
    HeishaMonParser,
    LwtNotice,
    MqttMessage,
    ParseResult,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, ParseErrorKind, Reading, SourceKind

NOW = Instant.from_unix(1_794_528_000.0)
PARSER = HeishaMonParser()


def parse(suffix: str, payload: str | bytes, *, retained: bool = False) -> ParseResult:
    """Parse ``payload`` on the HeishaMon topic ``suffix``."""
    return PARSER.parse(f"{DEFAULT_BASE}/{suffix}", payload, retained=retained, instant=NOW)


def reading(suffix: str, payload: str | bytes) -> Reading:
    """Parse and return the Reading, failing if the result is another type."""
    result = parse(suffix, payload)
    assert isinstance(result, Reading), result
    return result


def error(suffix: str, payload: str | bytes) -> ParseError:
    """Parse and return the ParseError, failing if the result is another type."""
    result = parse(suffix, payload)
    assert isinstance(result, ParseError), result
    return result


def test_catalogue_and_signal_enum_agree() -> None:
    """The catalogue and the HeishaSignal enum list the same signals, with sane ranges."""
    assert set(CATALOGUE) == {str(signal) for signal in HeishaSignal}
    for signal, spec in CATALOGUE.items():
        assert spec.signal == signal
        if spec.kind is ValueKind.ENUM:
            assert spec.meanings
        if spec.kind in (ValueKind.INT, ValueKind.FLOAT):
            assert spec.minimum is not None
            assert spec.maximum is not None
            assert spec.minimum < spec.maximum


@pytest.mark.parametrize(
    ("suffix", "payload", "value", "unit"),
    [
        ("main/Main_Outlet_Temp", "34.5", 34.5, "°C"),
        ("main/Main_Inlet_Temp", "28", 28.0, "°C"),
        ("main/Pump_Flow", "25.55", 25.55, "l/min"),
        ("main/Compressor_Current", "4.0", 4.0, "A"),
        ("main/Outside_Temp", "-3", -3, "°C"),
        ("main/Compressor_Freq", "48", 48, "Hz"),
        ("main/Heat_Power_Production", "11200", 11200, "W"),
        ("main/Max_Pump_Duty", "159", 159, None),
        ("main/Heating_Off_Outdoor_Temp", "30", 30, "°C"),
        ("main/Z1_Heat_Request_Temp", "-5", -5, "°C"),
        ("main/Z1_Heat_Curve_Outside_High_Temp", "-5", -5, "°C"),
    ],
)
def test_numeric_topics(suffix: str, payload: str, value: float, unit: str | None) -> None:
    """Numeric topics parse to the expected value, type, unit and source."""
    result = reading(suffix, payload)
    assert result.value == value
    assert type(result.value) is type(value)
    assert result.unit == unit
    assert result.signal == suffix
    assert result.source is SourceKind.HEISHAMON
    assert result.observed == NOW
    assert result.retained is False


def test_float_topic_accepts_integer_payload_as_float() -> None:
    """An integer payload on a float topic is returned as float."""
    assert isinstance(reading("main/Main_Outlet_Temp", "35").value, float)


@pytest.mark.parametrize(
    ("suffix", "payload", "code", "meaning"),
    [
        ("main/Heatpump_State", "1", 1, "on"),
        ("main/Operating_Mode_State", "0", 0, "heat"),
        ("main/Operating_Mode_State", "8", 8, "auto_cool_dhw"),
        ("main/Heating_Mode", "1", 1, "direct"),
        ("main/Defrosting_State", "1", 1, "on"),
        ("main/ThreeWay_Valve_State", "1", 1, "dhw"),
        ("main/Quiet_Mode_Level", "3", 3, "level_3"),
        ("main/Room_Heater_State", "0", 0, "blocked"),
        ("main/Internal_Heater_State", "1", 1, "active"),
        ("main/Zones_State", "2", 2, "zone1_and_zone2"),
    ],
)
def test_enum_topics(suffix: str, payload: str, code: int, meaning: str) -> None:
    """Enum topics parse to their code and the catalogue gives the meaning."""
    result = reading(suffix, payload)
    assert result.value == code
    assert result.unit is None
    assert CATALOGUE[suffix].meaning(code) == meaning


@pytest.mark.parametrize(
    ("suffix", "payload"),
    [
        ("main/Error", "No error"),
        ("main/Error", "H62"),
        ("main/Error", "F12"),
        ("main/Heat_Pump_Model", "C2 D3 0B 33 65 B2 D3 0B 94 65"),
    ],
)
def test_text_topics(suffix: str, payload: str) -> None:
    """Text topics keep their payload unchanged."""
    assert reading(suffix, payload).value == payload


def test_payload_whitespace_is_tolerated() -> None:
    """Surrounding whitespace in a numeric payload is ignored."""
    assert reading("main/Compressor_Freq", " 48\n").value == 48


def test_bytes_payload_is_decoded() -> None:
    """A bytes payload is decoded and parsed."""
    assert reading("main/Main_Outlet_Temp", b"30.5").value == 30.5


@pytest.mark.parametrize(
    ("suffix", "payload", "kind"),
    [
        ("main/Main_Outlet_Temp", "", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "abc", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "nan", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "inf", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "1e3", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "3_4", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "٣٤", ParseErrorKind.MALFORMED),
        ("main/Main_Outlet_Temp", "-78", ParseErrorKind.OUT_OF_RANGE),
        ("main/Main_Outlet_Temp", "1" * 40, ParseErrorKind.MALFORMED),
        ("main/Compressor_Freq", "48.5", ParseErrorKind.MALFORMED),
        ("main/Compressor_Freq", "-1", ParseErrorKind.OUT_OF_RANGE),
        ("main/Compressor_Freq", "999", ParseErrorKind.OUT_OF_RANGE),
        ("main/Outside_Temp", "-128", ParseErrorKind.OUT_OF_RANGE),
        ("main/Heat_Power_Production", "-200", ParseErrorKind.OUT_OF_RANGE),
        ("main/Pump_Flow", "-0.5", ParseErrorKind.OUT_OF_RANGE),
        ("main/Heatpump_State", "-1", ParseErrorKind.UNKNOWN_ENUM),
        ("main/Heatpump_State", "2", ParseErrorKind.UNKNOWN_ENUM),
        ("main/Operating_Mode_State", "9", ParseErrorKind.UNKNOWN_ENUM),
        ("main/Heating_Mode", "on", ParseErrorKind.MALFORMED),
        ("main/Error", "H6", ParseErrorKind.MALFORMED),
        ("main/Error", "", ParseErrorKind.MALFORMED),
        ("main/Heat_Pump_Model", "32 D4", ParseErrorKind.MALFORMED),
    ],
)
def test_malformed_payloads_become_typed_errors(
    suffix: str, payload: str, kind: ParseErrorKind
) -> None:
    """Bad payloads become a ParseError of the expected kind with signal, time and detail."""
    result = error(suffix, payload)
    assert result.kind is kind
    assert result.signal == suffix
    assert result.observed == NOW
    assert result.detail


def test_unknown_enum_minus_one_is_explained() -> None:
    """An enum payload of -1 is reported as unknown."""
    assert "unknown" in error("main/Defrosting_State", "-1").detail


def test_invalid_utf8_is_malformed() -> None:
    """A payload that is not valid UTF-8 is a malformed error."""
    assert error("main/Main_Outlet_Temp", b"\xff\xfe").kind is ParseErrorKind.MALFORMED


def test_long_payload_is_truncated_in_the_error() -> None:
    """An overlong payload is truncated in the error."""
    result = error("main/Error", "X" * 10_000)
    assert len(result.payload) < 300


def test_retained_flag_is_carried() -> None:
    """The retained flag is carried into the Reading."""
    result = parse("main/Outside_Temp", "3", retained=True)
    assert isinstance(result, Reading)
    assert result.retained is True


@pytest.mark.parametrize(
    ("topic", "reason"),
    [
        (f"{DEFAULT_BASE}/main/Buffer_Temp", "uncatalogued"),
        (f"{DEFAULT_BASE}/commands/SetCurves", "command"),
        (f"{DEFAULT_BASE}/1wire/28ff641e93acb036", "not_used"),
        (f"{DEFAULT_BASE}/s0/Watt/1", "not_used"),
        (f"{DEFAULT_BASE}/log", "not_used"),
        ("other_base/main/Outside_Temp", "outside_base"),
        (DEFAULT_BASE, "outside_base"),
    ],
)
def test_unused_topics_are_ignored(topic: str, reason: str) -> None:
    """Uncatalogued, command and foreign topics are Ignored with a reason."""
    result = PARSER.parse(topic, "1", retained=False, instant=NOW)
    assert result == Ignored(topic, reason)


def test_topic_base_is_configurable() -> None:
    """A parser with another base topic reads only that base."""
    parser = HeishaMonParser(base="aquarea")
    result = parser.parse("aquarea/main/Outside_Temp", "4", retained=False, instant=NOW)
    assert isinstance(result, Reading)
    assert result.signal == HeishaSignal.OUTSIDE_TEMP
    assert isinstance(
        parser.parse(f"{DEFAULT_BASE}/main/Outside_Temp", "4", retained=False, instant=NOW),
        Ignored,
    )


STATS = (
    '{"uptime":2992216346,"voltage":3.3,"free memory":59,"free heap":201508,"wifi":-1,'
    '"mqtt reconnects":4,"total reads":600912,"good reads":600906,"bad crc reads":0,'
    '"version":"v4.2.3","board":"ESP32","rules active":0}'
)


def test_stats_become_a_heartbeat() -> None:
    """A stats message becomes a Heartbeat with uptime, version and read counts."""
    result = parse("stats", STATS)
    assert result == Heartbeat(
        observed=NOW,
        retained=False,
        uptime_s=2992216.346,
        version="v4.2.3",
        total_reads=600912,
        good_reads=600906,
    )


def test_stats_with_unexpected_fields_still_count() -> None:
    """Unexpected stats field types still give a Heartbeat without the details."""
    result = parse("stats", '{"uptime":"soon","version":3,"total reads":-1}')
    assert result == Heartbeat(NOW, False)


@pytest.mark.parametrize("payload", ["", "not json", "[1,2]", "42", "[" * 5000])
def test_malformed_stats_are_errors(payload: str) -> None:
    """Non-JSON or non-object stats payloads are malformed errors."""
    result = error("stats", payload)
    assert result.signal == "stats"
    assert result.kind is ParseErrorKind.MALFORMED


@pytest.mark.parametrize(
    ("payload", "retained", "online"),
    [("Online", False, True), ("Offline", True, False), ("online", False, True)],
)
def test_lwt_is_a_notice(payload: str, retained: bool, online: bool) -> None:
    """An LWT payload becomes an online or offline notice."""
    assert parse("LWT", payload, retained=retained) == LwtNotice(online, NOW, retained)


def test_unexpected_lwt_is_an_error() -> None:
    """An unknown LWT payload is an error."""
    assert error("LWT", "maybe").signal == "LWT"


def test_parse_message_matches_parse() -> None:
    """parse_message gives the same result as parse for the same topic and payload."""
    message = MqttMessage(f"{DEFAULT_BASE}/main/Pump_Flow", "12.5", True, NOW)
    assert PARSER.parse_message(message) == parse("main/Pump_Flow", "12.5", retained=True)
