"""Turn recorded capture records into core inputs, for tests, open-loop runs and replay.

A capture line is ``{"t": unix_s, "k": key, "p": payload, "r": true?}`` (see
``capture/README.md``). ``r`` marks a delivery from the broker's retained store.
MQTT records become :class:`~ovenbird_core.heishamon.MqttMessage`, ``ha/<entity_id>``
records become Home Assistant readings carrying HA's own timestamps, and
``snapshot/*`` records are ignored here. File handling stays with the caller.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final, Protocol

from ovenbird_core.heishamon import MqttMessage, ParseResult
from ovenbird_core.inputs import InputRouter, parse_ha_payload
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, Reading

HA_KEY_PREFIX: Final = "ha/"
SNAPSHOT_KEY_PREFIX: Final = "snapshot/"
MAX_UNIX_S: Final = 253_402_300_799.0


class CaptureRecordLike(Protocol):
    """Anything shaped like a capture record (e.g. the recorder's ``Record``)."""

    @property
    def t(self) -> float:
        """Receipt time in unix seconds."""
        ...

    @property
    def topic(self) -> str:
        """Record key: MQTT topic, ``ha/<entity_id>`` or ``snapshot/<name>``."""
        ...

    @property
    def payload(self) -> str:
        """Payload text."""
        ...

    @property
    def retained(self) -> bool:
        """Delivered from the broker's retained store."""
        ...


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    """One capture line.

    Parameters
    ----------
    t
        Receipt time in unix seconds.
    topic
        Record key.
    payload
        Payload text.
    retained
        Delivered from the broker's retained store.
    """

    t: float
    topic: str
    payload: str
    retained: bool = False


def parse_capture_line(line: str) -> CaptureRecord | None:
    """Parse one capture line.

    Parameters
    ----------
    line
        One JSONL line.

    Returns
    -------
    CaptureRecord or None
        The record; ``None`` for blank lines, file headers and lines that are not
        a valid record.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except ValueError, RecursionError:
        return None
    if not isinstance(obj, dict):
        return None
    t, key, payload = obj.get("t"), obj.get("k"), obj.get("p")
    if isinstance(t, bool) or not isinstance(t, int | float) or not math.isfinite(t):
        return None
    if not 0.0 <= t <= MAX_UNIX_S:
        return None
    if not isinstance(key, str) or not isinstance(payload, str):
        return None
    return CaptureRecord(float(t), key, payload, obj.get("r") is True)


type CaptureInput = MqttMessage | Reading | ParseError | Ignored


def capture_input(record: CaptureRecordLike) -> CaptureInput:
    """Convert one capture record into a core input.

    Parameters
    ----------
    record
        A capture record.

    Returns
    -------
    CaptureInput
        An MQTT message for MQTT topics, a reading or error for ``ha/<entity_id>``,
        and :class:`~ovenbird_core.readings.Ignored` for ``snapshot/*``.
    """
    instant = Instant.from_capture(record.t)
    if record.topic.startswith(HA_KEY_PREFIX):
        entity_id = record.topic[len(HA_KEY_PREFIX) :]
        return parse_ha_payload(entity_id, record.payload, instant=instant)
    if record.topic.startswith(SNAPSHOT_KEY_PREFIX):
        return Ignored(record.topic, "snapshot")
    return MqttMessage(record.topic, record.payload, record.retained, instant)


def capture_inputs(records: Iterable[CaptureRecordLike]) -> Iterator[CaptureInput]:
    """Convert capture records lazily; see :func:`capture_input`."""
    for record in records:
        yield capture_input(record)


def replay_results(
    records: Iterable[CaptureRecordLike],
    router: InputRouter | None = None,
) -> Iterator[ParseResult]:
    """Convert and parse capture records into results ready for the state store.

    Parameters
    ----------
    records
        Capture records in time order.
    router
        Routing for MQTT topics; defaults to HeishaMon on ``panasonic_heat_pump``.

    Yields
    ------
    ParseResult
        One result per record.
    """
    active = router or InputRouter()
    for item in capture_inputs(records):
        yield active.route(item) if isinstance(item, MqttMessage) else item
