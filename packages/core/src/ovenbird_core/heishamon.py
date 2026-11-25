"""Parse HeishaMon MQTT messages into readings, heartbeats or typed errors.

HeishaMon publishes every value as a decimal string: ``main/*`` on change plus a
full dump every 300 s, ``stats`` (JSON) every 5 s query cycle and ``LWT``. The
parser never raises on a payload; anything it cannot use becomes a
:class:`~ovenbird_core.readings.ParseError` or an
:class:`~ovenbird_core.readings.Ignored`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from ovenbird_core.catalogue import CATALOGUE, MAIN_PREFIX, TopicSpec, ValueKind
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

DEFAULT_BASE: Final = "panasonic_heat_pump"
STATS_SIGNAL: Final[SignalId] = "stats"
LWT_SIGNAL: Final[SignalId] = "LWT"
COMMANDS_PREFIX: Final = "commands/"
RESERVED_SUBTREES: Final = (MAIN_PREFIX, COMMANDS_PREFIX)
MAX_SCALAR_LENGTH: Final = 32
MAX_STATS_LENGTH: Final = 4096
_INT_RE: Final = re.compile(r"[+-]?[0-9]+", re.ASCII)
_FLOAT_RE: Final = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?", re.ASCII)


@dataclass(frozen=True, slots=True)
class MqttMessage:
    """One MQTT delivery, the parser's input.

    Parameters
    ----------
    topic
        Full topic.
    payload
        Payload as received; bytes are decoded as UTF-8.
    retained
        Whether the broker delivered it from its retained store.
    instant
        When it was received.
    """

    topic: str
    payload: str | bytes
    retained: bool
    instant: Instant


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """A parsed ``stats`` message; live ones prove HeishaMon is polling the pump.

    Parameters
    ----------
    observed
        When it was received.
    retained
        Retained deliveries are replays and never prove liveness.
    uptime_s
        Board uptime in seconds, when reported.
    version
        Firmware version, when reported.
    total_reads, good_reads
        Pump read counters, when reported.
    """

    observed: Instant
    retained: bool
    uptime_s: float | None = None
    version: str | None = None
    total_reads: int | None = None
    good_reads: int | None = None


@dataclass(frozen=True, slots=True)
class LwtNotice:
    """A parsed ``LWT`` message; informational only, never used for liveness.

    Parameters
    ----------
    online
        ``True`` for ``Online``, ``False`` for ``Offline``.
    observed
        When it was received.
    retained
        Whether it came from the retained store (the will ``Offline`` usually does).
    """

    online: bool
    observed: Instant
    retained: bool


type ParseResult = Reading | Heartbeat | LwtNotice | ParseError | Ignored


def decode_payload(payload: str | bytes) -> str | None:
    """Return the payload as text, or ``None`` when it is not valid UTF-8."""
    if isinstance(payload, str):
        return payload
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse_value(
    spec: TopicSpec,
    text: str,
    *,
    retained: bool,
    instant: Instant,
) -> Reading | ParseError:
    """Decode one ``main/*`` payload according to its catalogue entry.

    Parameters
    ----------
    spec
        Catalogue entry of the topic.
    text
        Payload text.
    retained
        Whether the delivery came from the retained store.
    instant
        Receipt time.

    Returns
    -------
    Reading or ParseError
        The reading, or why the payload was rejected.
    """

    def fail(kind: ParseErrorKind, detail: str) -> ParseError:
        return ParseError(spec.signal, kind, echo(text), detail, instant, retained)

    stripped = text.strip()
    value: Value
    if spec.kind is ValueKind.TEXT:
        if not spec.matches(stripped):
            return fail(ParseErrorKind.MALFORMED, f"does not match {spec.pattern!r}")
        value = stripped
    elif len(stripped) > MAX_SCALAR_LENGTH:
        return fail(ParseErrorKind.MALFORMED, "payload too long for a number")
    elif spec.kind is ValueKind.FLOAT:
        if _FLOAT_RE.fullmatch(stripped) is None:
            return fail(ParseErrorKind.MALFORMED, "not a decimal number")
        value = float(stripped)
        if not _in_range(spec, value):
            return fail(ParseErrorKind.OUT_OF_RANGE, f"outside [{spec.minimum}, {spec.maximum}]")
    else:
        if _INT_RE.fullmatch(stripped) is None:
            return fail(ParseErrorKind.MALFORMED, "not an integer")
        code = int(stripped)
        if spec.kind is ValueKind.ENUM and spec.meaning(code) is None:
            detail = "firmware reports -1 (unknown)" if code == -1 else "code has no meaning"
            return fail(ParseErrorKind.UNKNOWN_ENUM, detail)
        if not _in_range(spec, code):
            return fail(ParseErrorKind.OUT_OF_RANGE, f"outside [{spec.minimum}, {spec.maximum}]")
        value = code
    return Reading(spec.signal, value, spec.unit, instant, SourceKind.HEISHAMON, retained)


def _in_range(spec: TopicSpec, value: float) -> bool:
    if spec.minimum is not None and value < spec.minimum:
        return False
    return spec.maximum is None or value <= spec.maximum


def parse_stats(text: str, *, retained: bool, instant: Instant) -> Heartbeat | ParseError:
    """Parse a ``stats`` JSON object into a :class:`Heartbeat`.

    Parameters
    ----------
    text
        Payload text.
    retained
        Whether the delivery came from the retained store.
    instant
        Receipt time.

    Returns
    -------
    Heartbeat or ParseError
        A heartbeat for any JSON object (unknown or missing fields are tolerated),
        otherwise an error.
    """
    if len(text) > MAX_STATS_LENGTH:
        return ParseError(
            STATS_SIGNAL, ParseErrorKind.MALFORMED, echo(text), "too long", instant, retained
        )
    try:
        obj = json.loads(text)
    except ValueError, RecursionError:
        obj = None
    if not isinstance(obj, dict):
        return ParseError(
            STATS_SIGNAL,
            ParseErrorKind.MALFORMED,
            echo(text),
            "not a JSON object",
            instant,
            retained,
        )
    uptime_ms = _number(obj.get("uptime"))
    return Heartbeat(
        observed=instant,
        retained=retained,
        uptime_s=uptime_ms / 1000.0 if uptime_ms is not None else None,
        version=_text(obj.get("version")),
        total_reads=_count(obj.get("total reads")),
        good_reads=_count(obj.get("good reads")),
    )


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    number = float(raw)
    return number if math.isfinite(number) else None


def _count(raw: Any) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None


def _text(raw: Any) -> str | None:
    return raw if isinstance(raw, str) else None


@dataclass(frozen=True, slots=True)
class HeishaMonParser:
    """Turn messages below one HeishaMon topic base into parse results.

    Parameters
    ----------
    base
        Topic base configured in HeishaMon (``mqtt_topic_base``).
    catalogue
        Catalogued ``main/*`` topics by signal id.
    """

    base: str = DEFAULT_BASE
    catalogue: Mapping[SignalId, TopicSpec] = field(default_factory=lambda: CATALOGUE)

    def owns(self, topic: str) -> bool:
        """Whether ``topic`` lies below this parser's base."""
        return topic.startswith(self.base + "/")

    def reserves(self, topic: str) -> bool:
        """Whether ``topic`` belongs to the board itself and no plain input may read it.

        The board's own topics are ``<base>/stats``, ``<base>/LWT`` and everything at
        or below ``<base>/main`` and ``<base>/commands``; other subtrees of the base
        (``1wire``, ``s0``, ...) stay readable as plain inputs.
        """
        if not self.owns(topic):
            return False
        suffix = topic[len(self.base) + 1 :]
        if suffix in (STATS_SIGNAL, LWT_SIGNAL):
            return True
        return any(
            suffix == subtree.rstrip("/") or suffix.startswith(subtree)
            for subtree in RESERVED_SUBTREES
        )

    def parse(
        self,
        topic: str,
        payload: str | bytes,
        *,
        retained: bool,
        instant: Instant,
    ) -> ParseResult:
        """Parse one delivery.

        Parameters
        ----------
        topic
            Full MQTT topic.
        payload
            Payload as delivered.
        retained
            Whether the broker delivered it from its retained store.
        instant
            Receipt time.

        Returns
        -------
        ParseResult
            A reading for catalogued ``main/*`` topics, a heartbeat for ``stats``,
            a notice for ``LWT``, an error for unusable payloads and
            :class:`~ovenbird_core.readings.Ignored` for everything else.
        """
        if not self.owns(topic):
            return Ignored(topic, "outside_base")
        suffix = topic[len(self.base) + 1 :]
        if suffix in (STATS_SIGNAL, LWT_SIGNAL) or suffix in self.catalogue:
            text = decode_payload(payload)
            if text is None:
                return ParseError(
                    suffix,
                    ParseErrorKind.MALFORMED,
                    echo(repr(payload)),
                    "not UTF-8",
                    instant,
                    retained,
                )
            if suffix == STATS_SIGNAL:
                return parse_stats(text, retained=retained, instant=instant)
            if suffix == LWT_SIGNAL:
                return _parse_lwt(text, retained=retained, instant=instant)
            return parse_value(self.catalogue[suffix], text, retained=retained, instant=instant)
        if suffix.startswith(MAIN_PREFIX):
            return Ignored(topic, "uncatalogued")
        if suffix.startswith(COMMANDS_PREFIX):
            return Ignored(topic, "command")
        return Ignored(topic, "not_used")

    def parse_message(self, message: MqttMessage) -> ParseResult:
        """Parse an :class:`MqttMessage`; see :meth:`parse`."""
        return self.parse(
            message.topic, message.payload, retained=message.retained, instant=message.instant
        )


def _parse_lwt(text: str, *, retained: bool, instant: Instant) -> LwtNotice | ParseError:
    match text.strip().lower():
        case "online":
            return LwtNotice(True, instant, retained)
        case "offline":
            return LwtNotice(False, instant, retained)
        case _:
            return ParseError(
                LWT_SIGNAL,
                ParseErrorKind.MALFORMED,
                echo(text),
                "expected Online or Offline",
                instant,
                retained,
            )
