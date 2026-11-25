"""Non-HeishaMon inputs (Home Assistant states, plain MQTT topics) and message routing.

Home Assistant signals are ``ha/<entity_id>`` for an entity's state and
``ha/<entity_id>#<attribute>`` for one numeric attribute; the only attribute read is
a thermostat's ``current_temperature`` (``ha/climate.living_room#current_temperature``),
because many thermostats expose the room temperature only there.

Home Assistant temperatures in °F or K are converted to °C when the reading is
built (:func:`ha_reading`), so everything downstream sees °C; the reading keeps the
reported unit in ``source_unit``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from ovenbird_core.catalogue import CATALOGUE, MAIN_PREFIX
from ovenbird_core.heishamon import (
    COMMANDS_PREFIX,
    LWT_SIGNAL,
    STATS_SIGNAL,
    HeishaMonParser,
    MqttMessage,
    ParseResult,
    decode_payload,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import (
    Ignored,
    ParseError,
    ParseErrorKind,
    Reading,
    SignalId,
    SourceKind,
    Value,
    echo,
)

HA_SIGNAL_PREFIX: Final = "ha/"
HA_ATTRIBUTE_SEPARATOR: Final = "#"
CLIMATE_DOMAIN: Final = "climate"
CURRENT_TEMPERATURE: Final = "current_temperature"
HA_ATTRIBUTES: Final = frozenset({(CLIMATE_DOMAIN, CURRENT_TEMPERATURE)})
CELSIUS: Final = "°C"
FAHRENHEIT: Final = "°F"
KELVIN: Final = "K"
TEMPERATURE_UNITS: Final = {
    CELSIUS: CELSIUS,
    "℃": CELSIUS,
    FAHRENHEIT: FAHRENHEIT,
    "℉": FAHRENHEIT,
    KELVIN: KELVIN,
}
KELVIN_OFFSET: Final = 273.15
CONVERTED_DECIMALS: Final = 2
MQTT_SIGNAL_PREFIX: Final = "mqtt/"
DERIVED_SIGNAL_PREFIX: Final = "derived/"
RESERVED_SIGNAL_PREFIXES: Final = (
    MAIN_PREFIX,
    HA_SIGNAL_PREFIX,
    COMMANDS_PREFIX,
    DERIVED_SIGNAL_PREFIX,
)
RESERVED_SIGNALS: Final = frozenset({STATS_SIGNAL, LWT_SIGNAL})
HA_UNAVAILABLE: Final = frozenset({"", "unavailable", "unknown", "none"})
MAX_HA_PAYLOAD: Final = 16384


def ha_signal(entity_id: str) -> SignalId:
    """Return the signal id of a Home Assistant entity (``ha/<entity_id>``)."""
    return HA_SIGNAL_PREFIX + entity_id


def ha_attribute_signal(entity_id: str, attribute: str) -> SignalId:
    """Return the signal id of an entity's attribute (``ha/<entity_id>#<attribute>``)."""
    return f"{HA_SIGNAL_PREFIX}{entity_id}{HA_ATTRIBUTE_SEPARATOR}{attribute}"


def split_ha_signal(signal: str) -> tuple[str, str | None] | None:
    """Split a Home Assistant signal id into its entity id and attribute.

    Parameters
    ----------
    signal
        Any signal id.

    Returns
    -------
    tuple or None
        ``(entity_id, attribute)`` (``attribute`` is ``None`` for the state) of an
        ``ha/`` signal; ``None`` for every other signal. The parts are not checked.
    """
    if not signal.startswith(HA_SIGNAL_PREFIX):
        return None
    entity_id, separator, attribute = signal[len(HA_SIGNAL_PREFIX) :].partition(
        HA_ATTRIBUTE_SEPARATOR
    )
    return entity_id, (attribute if separator else None)


def attribute_supported(entity_id: str, attribute: str) -> bool:
    """Whether ovenbird reads ``attribute`` of ``entity_id`` (a thermostat's room temperature)."""
    return (entity_id.split(".", 1)[0], attribute) in HA_ATTRIBUTES


def temperature_unit(unit: str | None) -> str | None:
    """Return the canonical temperature unit (``°C``, ``°F``, ``K``) of ``unit``, else ``None``."""
    return None if unit is None else TEMPERATURE_UNITS.get(unit.strip())


def to_celsius(value: float, unit: str) -> float:
    """Convert a temperature in a canonical unit (see :func:`temperature_unit`) to °C.

    Raises
    ------
    ValueError
        When ``unit`` is not a canonical temperature unit.
    """
    if unit == CELSIUS:
        return value
    if unit == FAHRENHEIT:
        return (value - 32.0) * 5.0 / 9.0
    if unit == KELVIN:
        return value - KELVIN_OFFSET
    raise ValueError(f"not a temperature unit: {unit!r}")


def mqtt_signal(topic: str) -> SignalId:
    """Return the default signal id of a plain MQTT topic (``mqtt/<topic>``)."""
    return MQTT_SIGNAL_PREFIX + topic


def reserved_signal(signal: str) -> bool:
    """Whether ``signal`` belongs to the pump, Home Assistant or the service itself.

    A plain MQTT input may never produce such a signal: the HeishaMon catalogue,
    ``stats``, ``LWT`` and the prefixes ``main/``, ``ha/``, ``commands/`` and
    ``derived/`` are reserved.
    """
    return (
        signal in CATALOGUE
        or signal in RESERVED_SIGNALS
        or signal.startswith(RESERVED_SIGNAL_PREFIXES)
    )


def parse_number(text: str) -> float | None:
    """Parse a finite decimal number, or return ``None``."""
    stripped = text.strip()
    if not stripped or len(stripped) > 64:
        return None
    try:
        number = float(stripped)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or return ``None``."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def ha_reading(
    entity_id: str,
    state: str,
    *,
    instant: Instant,
    unit: str | None = None,
    last_reported: datetime | None = None,
    last_updated: datetime | None = None,
    last_changed: datetime | None = None,
    attribute: str | None = None,
) -> Reading | ParseError:
    """Build a reading from one Home Assistant state.

    A number in °F or K (or ``℃``) becomes °C with ``source_unit`` set to the
    reported unit; every other unit is passed on as it is.

    Parameters
    ----------
    entity_id
        Entity id, e.g. ``sensor.living_room_temperature``.
    state
        The entity's state string (or the attribute's value as text).
    instant
        When the state was received.
    unit
        ``unit_of_measurement`` attribute, if any.
    last_reported, last_updated
        HA's own timestamps; ``last_reported`` (or else ``last_updated``) becomes the
        reading's source timestamp, so a state replayed on reconnect is not mistaken
        for a fresh one.
    last_changed
        HA's ``last_changed``: when the value last changed (the held time of an
        unchanged value after a restart).
    attribute
        The attribute the state was read from; the signal is then
        ``ha/<entity_id>#<attribute>``.

    Returns
    -------
    Reading or ParseError
        A numeric reading when the state is a finite number, a text reading for
        other states, and an ``unavailable`` error for HA's placeholder states.
    """
    signal = (
        ha_signal(entity_id) if attribute is None else ha_attribute_signal(entity_id, attribute)
    )
    if state.strip().lower() in HA_UNAVAILABLE:
        return ParseError(
            signal, ParseErrorKind.UNAVAILABLE, echo(state), "entity has no state", instant
        )
    number = parse_number(state)
    value: Value = number if number is not None else state
    canonical = temperature_unit(unit)
    source_unit: str | None = None
    if number is not None and canonical is not None and (canonical, unit) != (CELSIUS, CELSIUS):
        value = round(to_celsius(number, canonical), CONVERTED_DECIMALS)
        source_unit, unit = unit, CELSIUS
    return Reading(
        signal,
        value,
        unit,
        instant,
        SourceKind.HA,
        retained=False,
        source_timestamp=last_reported or last_updated,
        source_changed=last_changed,
        source_unit=source_unit,
    )


def parse_ha_payload(entity_id: str, payload: str, *, instant: Instant) -> Reading | ParseError:
    """Parse a recorded HA state payload (the capture's ``ha/<entity_id>`` JSON).

    Parameters
    ----------
    entity_id
        Entity id.
    payload
        JSON object with ``state`` and optional ``last_updated``, ``last_reported``,
        ``last_changed`` and ``unit``.
    instant
        Receipt time.

    Returns
    -------
    Reading or ParseError
        See :func:`ha_reading`; malformed JSON becomes a ``malformed`` error.
    """
    signal = ha_signal(entity_id)
    obj: Any = None
    if len(payload) <= MAX_HA_PAYLOAD:
        try:
            obj = json.loads(payload)
        except ValueError, RecursionError:
            obj = None
    if not isinstance(obj, dict) or not isinstance(obj.get("state"), str):
        return ParseError(
            signal, ParseErrorKind.MALFORMED, echo(payload), "expected a state object", instant
        )
    unit = obj.get("unit")
    return ha_reading(
        entity_id,
        obj["state"],
        instant=instant,
        unit=unit if isinstance(unit, str) else None,
        last_reported=parse_timestamp(obj.get("last_reported")),
        last_updated=parse_timestamp(obj.get("last_updated")),
        last_changed=parse_timestamp(obj.get("last_changed")),
    )


@dataclass(frozen=True, slots=True)
class MqttSignal:
    """A numeric value on a plain MQTT topic (e.g. a mirrored room temperature).

    Parameters
    ----------
    signal
        Signal id the readings get.
    unit
        Unit of the value.
    minimum, maximum
        Inclusive plausibility range.
    """

    signal: SignalId
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    def parse(self, message: MqttMessage) -> Reading | ParseError:
        """Parse one delivery on this topic."""
        text = decode_payload(message.payload)
        if text is None:
            return ParseError(
                self.signal,
                ParseErrorKind.MALFORMED,
                echo(repr(message.payload)),
                "not UTF-8",
                message.instant,
                message.retained,
            )
        number = parse_number(text)
        if number is None:
            return ParseError(
                self.signal,
                ParseErrorKind.MALFORMED,
                echo(text),
                "not a number",
                message.instant,
                message.retained,
            )
        if (self.minimum is not None and number < self.minimum) or (
            self.maximum is not None and number > self.maximum
        ):
            return ParseError(
                self.signal,
                ParseErrorKind.OUT_OF_RANGE,
                echo(text),
                f"outside [{self.minimum}, {self.maximum}]",
                message.instant,
                message.retained,
            )
        return Reading(
            self.signal, number, self.unit, message.instant, SourceKind.MQTT, message.retained
        )


@dataclass(frozen=True, slots=True)
class InputRouter:
    """Send each MQTT delivery to the HeishaMon parser or a configured plain topic.

    A plain topic never overrides the board: a topic the HeishaMon parser reserves
    (:meth:`~ovenbird_core.heishamon.HeishaMonParser.reserves`) always goes to the
    parser, and a plain topic configured with a reserved signal id
    (:func:`reserved_signal`) is ignored (``reserved_signal``).

    Parameters
    ----------
    heishamon
        Parser for the HeishaMon topic base.
    mqtt_signals
        Plain MQTT topics to read, by full topic.
    """

    heishamon: HeishaMonParser = field(default_factory=HeishaMonParser)
    mqtt_signals: Mapping[str, MqttSignal] = field(default_factory=dict)

    def route(self, message: MqttMessage) -> ParseResult:
        """Parse one delivery with whichever parser owns its topic."""
        spec = self.mqtt_signals.get(message.topic)
        if spec is not None and not self.heishamon.reserves(message.topic):
            if reserved_signal(spec.signal):
                return Ignored(message.topic, "reserved_signal")
            return spec.parse(message)
        if self.heishamon.owns(message.topic):
            return self.heishamon.parse_message(message)
        return Ignored(message.topic, "not_configured")
