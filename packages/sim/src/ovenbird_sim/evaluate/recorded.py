"""Recorded inputs for open-loop evaluation: capture records, Datalake room states, room choice.

The capture is read day file by day file and filtered on the raw line by topic
before JSON decoding, so only the HeishaMon topics a controller reads, the ``stats``
heartbeat, the recorded commands (kept as reference, never fed to a controller) and
the mirrored room temperature are decoded. Home Assistant states from the Datalake
become readings at their ``last_updated`` time and are merged into the same
time-ordered stream.

**Room temperature freshness**
The recording holds the room sensor's state *changes* only (the mirror automation
and the Datalake both store ``last_updated``, not ``last_reported``), and the living
room sensor changes in small steps every few hours. A open-loop run judges it by the
live 30 min Home Assistant rule unless configured (the room then looks stale most of
the time - a pessimistic bound, since live re-reads ``last_reported``);
:data:`ROOM_MAX_AGE_S` (24 h) is the lenient alternative for decision studies.
"""

from __future__ import annotations

import gzip
import heapq
import json
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Final

from ovenbird_core.capture import CaptureRecord, parse_capture_line
from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.types import RoomInput
from ovenbird_core.inputs import ha_signal, mqtt_signal
from ovenbird_core.instant import Instant
from ovenbird_core.readings import ParseError, ParseErrorKind, Reading, SignalId, SourceKind
from ovenbird_core.store import Snapshot
from ovenbird_sim import local
from ovenbird_sim.data import datalake as dl
from ovenbird_sim.data.capture import capture_files

BASE: Final = "panasonic_heat_pump/"
STATS_TOPIC: Final = BASE + "stats"
SETCURVES_TOPIC: Final = BASE + "commands/SetCurves"
SETDUTY_TOPIC: Final = BASE + "commands/SetMaxPumpDuty"
MIRROR_TOPIC: Final = "climate_manager_capture/room_temp"
MIRROR_SIGNAL: Final[SignalId] = mqtt_signal(MIRROR_TOPIC)
ROOM_ENTITY: Final = "sensor.living_room_temperature"
DATALAKE_SIGNAL: Final[SignalId] = ha_signal(local.entity(ROOM_ENTITY))
ROOM_MAX_AGE_S: Final = 24 * 3600.0
SECONDS_PER_DAY: Final = 86400.0
ROOM_RANGE_C: Final = (0.0, 40.0)
_KEY_MARK: Final = '"k":"'
_CONTROL_SIGNALS: Final = frozenset(
    {
        HeishaSignal.OUTSIDE_TEMP,
        HeishaSignal.OUTLET_TEMP,
        HeishaSignal.INLET_TEMP,
        HeishaSignal.COMPRESSOR_FREQ,
        HeishaSignal.DEFROSTING_STATE,
        HeishaSignal.THREEWAY_VALVE_STATE,
        HeishaSignal.HEATING_MODE,
        HeishaSignal.OPERATING_MODE_STATE,
        HeishaSignal.Z1_WATER_TARGET_TEMP,
        HeishaSignal.MAIN_TARGET_TEMP,
        HeishaSignal.MAX_PUMP_DUTY,
        HeishaSignal.QUIET_MODE_LEVEL,
        HeishaSignal.HEATPUMP_STATE,
        HeishaSignal.ROOM_THERMOSTAT_TEMP,
        HeishaSignal.PUMP_FLOW,
    }
)


class RoomSource(StrEnum):
    """Which recorded signal is the controller's room temperature.

    ``auto``: the Datalake living-room sensor where it has a usable value, else the
    mirrored copy of the same sensor. ``datalake`` / ``mirror``: one of them only.
    ``none``: no room sensor.
    """

    AUTO = "auto"
    DATALAKE = "datalake"
    MIRROR = "mirror"
    NONE = "none"


type StreamItem = CaptureRecord | Reading | ParseError


def control_topics() -> frozenset[str]:
    """Full topics a open-loop run decodes: controller inputs, heartbeat, commands, room mirror."""
    topics = {BASE + str(signal) for signal in _CONTROL_SIGNALS}
    return frozenset(topics | {STATS_TOPIC, SETCURVES_TOPIC, SETDUTY_TOPIC, MIRROR_TOPIC})


def setcurves_target(payload: str) -> int | None:
    """Return the zone 1 water target a recorded ``SetCurves`` payload sets, if any.

    Parameters
    ----------
    payload
        JSON text such as ``{"zone1":{"heat":{"target":{"high":31}}}}``.

    Returns
    -------
    int or None
        ``zone1.heat.target.high`` as an integer; ``None`` when absent or not a number.
    """
    try:
        node = json.loads(payload)
    except ValueError:
        return None
    for key in ("zone1", "heat", "target", "high"):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if isinstance(node, bool) or not isinstance(node, int | float) or not math.isfinite(node):
        return None
    return int(node)


def _open(path: Path) -> IO[str]:
    """Open a capture file for text reading, decompressing it when it ends in ``.gz``."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _day(path: Path) -> date | None:
    """Return the date in a capture file name (``YYYY-MM-DD.jsonl``), or ``None``."""
    try:
        return date.fromisoformat(path.name.split(".", 1)[0])
    except ValueError:
        return None


def day_files(capture: Path, start: float | None = None, end: float | None = None) -> list[Path]:
    """Capture day files overlapping ``[start - 1 day, end]`` (a single file passes through).

    Parameters
    ----------
    capture
        Capture directory or one ``.jsonl[.gz]`` file.
    start, end
        Optional span in unix seconds.

    Returns
    -------
    list of Path
        Files in date order.
    """
    if capture.is_file():
        return [capture]
    files = capture_files(capture)
    out = []
    for path in files:
        day = _day(path)
        if day is None:
            continue
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()
        if start is not None and day_start + SECONDS_PER_DAY < start - SECONDS_PER_DAY:
            continue
        if end is not None and day_start > end:
            continue
        out.append(path)
    return out


def iter_records(
    files: Sequence[Path],
    topics: frozenset[str],
    end: float | None = None,
) -> Iterator[CaptureRecord]:
    """Yield the records of ``files`` whose topic is in ``topics`` and ``t <= end``.

    Records before a run's first tick are kept: they set the state it sees.

    Parameters
    ----------
    files
        Day files in date order.
    topics
        Full topics to keep (matched on the raw line before JSON decoding).
    end
        Last record time to keep.

    Yields
    ------
    CaptureRecord
        Records in file order.
    """
    for path in files:
        with _open(path) as handle:
            for line in handle:
                begin = line.find(_KEY_MARK)
                if begin < 0:
                    continue
                begin += len(_KEY_MARK)
                if line[begin : line.find('"', begin)] not in topics:
                    continue
                record = parse_capture_line(line)
                if record is None:
                    continue
                if end is not None and record.t > end:
                    return
                yield record


def datalake_room(
    root: Path | None, entity: str = ROOM_ENTITY, end: float | None = None
) -> list[Reading | ParseError]:
    """Datalake states of the room entity as readings (``unavailable`` as errors).

    Parameters
    ----------
    root
        Datalake root; ``None`` or missing gives no states.
    entity
        Entity id; the readings carry this install's id (:func:`ovenbird_sim.local.entity`).
    end
        Last state time to keep.

    Returns
    -------
    list
        Readings and parse errors in time order.
    """
    if root is None or not root.is_dir():
        return []
    series = dl.load_state(root, entity)
    signal = ha_signal(local.entity(entity))
    out: list[Reading | ParseError] = []
    for t, v in zip(series.t.tolist(), series.v.tolist(), strict=True):
        if end is not None and t > end:
            break
        instant = Instant.from_unix(t)
        if math.isfinite(v):
            stamp = datetime.fromtimestamp(t, UTC)
            out.append(Reading(signal, v, "°C", instant, SourceKind.HA, False, stamp))
        else:
            out.append(
                ParseError(signal, ParseErrorKind.UNAVAILABLE, "", "state not numeric", instant)
            )
    return out


def item_time(item: StreamItem) -> float:
    """Time of a stream item in unix seconds."""
    if isinstance(item, CaptureRecord):
        return item.t
    return item.observed.wall.timestamp()


def merged_stream(*streams: Iterable[StreamItem]) -> Iterator[StreamItem]:
    """Merge time-ordered streams into one (stable for equal times)."""
    return heapq.merge(*streams, key=item_time)


@dataclass(frozen=True, slots=True)
class RoomResolver:
    """Chooses the room input of a tick from the snapshot (the caller's job per the interface).

    Parameters
    ----------
    source
        Room source.
    """

    source: RoomSource

    def resolve(self, snapshot: Snapshot) -> RoomInput | None:
        """Return the tick's room input, ``None`` without a room sensor or value."""
        match self.source:
            case RoomSource.NONE:
                return None
            case RoomSource.DATALAKE:
                return _room(snapshot, DATALAKE_SIGNAL)
            case RoomSource.MIRROR:
                return _room(snapshot, MIRROR_SIGNAL)
            case RoomSource.AUTO:
                lake = _room(snapshot, DATALAKE_SIGNAL)
                if lake is not None and lake.fresh:
                    return lake
                mirror = _room(snapshot, MIRROR_SIGNAL)
                if mirror is not None and (mirror.fresh or lake is None):
                    return mirror
                return lake


def _room(snapshot: Snapshot, signal: SignalId) -> RoomInput | None:
    """Return the finite numeric reading of ``signal`` as a room input, or ``None``."""
    view = snapshot.get(signal)
    if view is None:
        return None
    value = view.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return RoomInput(number, view.age, view.fresh, view.signal, view.reason)
