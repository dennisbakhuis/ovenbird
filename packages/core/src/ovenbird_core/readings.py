"""Readings and the other outcomes of parsing an input message."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ovenbird_core.instant import Instant

type SignalId = str
type Value = float | int | str | bool


class SourceKind(StrEnum):
    """Where a reading came from."""

    HEISHAMON = "heishamon"
    HA = "ha"
    MQTT = "mqtt"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class Reading:
    """One observed value of one signal.

    Parameters
    ----------
    signal
        Stable signal id, e.g. ``main/Main_Outlet_Temp`` or ``ha/sensor.living_room``.
    value
        The parsed value.
    unit
        Unit of ``value`` (``"°C"``, ``"W"``, ...); ``None`` for enums and text.
    observed
        When the core received the value.
    source
        The kind of source that delivered it.
    retained
        ``True`` when the broker replayed the value from its retained store; such a
        delivery tells nothing about how current the value is.
    source_timestamp
        When the source itself last confirmed the value (HA ``last_reported``),
        if it reports one.
    source_changed
        When the source says the value last changed (HA ``last_changed``), if it
        reports one; seeds the held time of a value after a restart.
    source_unit
        The unit the source reported when the value was converted at ingest (a
        Home Assistant temperature in °F or K becomes °C); ``None`` otherwise.
    """

    signal: SignalId
    value: Value
    unit: str | None
    observed: Instant
    source: SourceKind
    retained: bool = False
    source_timestamp: datetime | None = None
    source_changed: datetime | None = None
    source_unit: str | None = None


class ParseErrorKind(StrEnum):
    """Why an input could not become a reading."""

    MALFORMED = "malformed"
    OUT_OF_RANGE = "out_of_range"
    UNKNOWN_ENUM = "unknown_enum"
    UNAVAILABLE = "unavailable"
    UNIT = "unit"


@dataclass(frozen=True, slots=True)
class ParseError:
    """A payload that was rejected; returned instead of raised.

    Parameters
    ----------
    signal
        The signal the payload was meant for.
    kind
        Category of the problem.
    payload
        The raw payload, truncated to keep diagnostics small.
    detail
        Human-readable explanation.
    observed
        When the payload was received.
    retained
        Whether it was a retained delivery.
    """

    signal: SignalId
    kind: ParseErrorKind
    payload: str
    detail: str
    observed: Instant
    retained: bool = False


@dataclass(frozen=True, slots=True)
class Ignored:
    """An input the core does not use (uncatalogued topic, command, log, ...).

    Parameters
    ----------
    key
        Topic or record key.
    reason
        Short reason code.
    """

    key: str
    reason: str


MAX_PAYLOAD_ECHO = 200


def echo(payload: str) -> str:
    """Truncate a payload for inclusion in a :class:`ParseError`."""
    return payload if len(payload) <= MAX_PAYLOAD_ECHO else payload[:MAX_PAYLOAD_ECHO] + "…"
