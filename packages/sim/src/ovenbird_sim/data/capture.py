"""Load a HeishaMon capture (``captures/<name>/YYYY-MM-DD.jsonl[.gz]``) into numeric series.

Each capture line is parsed with :func:`ovenbird_core.capture.parse_capture_line`.
Numeric ``main/*`` payloads outside the catalogue's plausibility range (the
firmware's "sensor absent" sentinels) are dropped. Commands are decoded to the
integer HeishaMon would apply. ``stats`` deliveries become the liveness series
(value 1 at every live heartbeat), used to find recorder and board gaps.

Parsing is the slow part (~250k lines per day), so each closed day is cached as an
``.npz`` file next to the capture under ``cache/``; a cache entry is reused only
while the source file's size and modification time are unchanged.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Final, TextIO

import numpy as np

from ovenbird_core.capture import parse_capture_line
from ovenbird_core.catalogue import CATALOGUE, ValueKind
from ovenbird_sim.data.series import Series, merge_maps

BASE: Final = "panasonic_heat_pump/"
MIRROR: Final = "climate_manager_capture/"
LIVENESS: Final = "liveness"
ROOM_MIRROR: Final = "room_temp"
CMD_SETPOINT: Final = "cmd/SetCurves"
CMD_PUMP_DUTY: Final = "cmd/SetMaxPumpDuty"
CMD_HEAT_REQUEST: Final = "cmd/SetZ1HeatRequestTemperature"
CACHE_VERSION: Final = 2
_SKIP_SUFFIXES: Final = ("/alias", "/LWT")


def _open(path: Path) -> TextIO:
    """Open a capture file for text reading, decompressing it when it ends in ``.gz``."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _number(text: str) -> float | None:
    """Parse ``text`` as a finite float, returning ``None`` for anything else."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _setcurves_high(payload: str) -> float | None:
    """Return the heating-curve upper target (degC) of a set-curves payload, or ``None``."""
    try:
        obj = json.loads(payload)
        value = obj["zone1"]["heat"]["target"]["high"]
    except ValueError, KeyError, TypeError:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(int(value))
    if isinstance(value, str):
        number = _number(value)
        return None if number is None else float(int(number))
    return None


def decode(topic: str, payload: str) -> tuple[str, float] | None:
    """Map one capture record to ``(signal, value)``, or ``None`` when it is not used.

    Parameters
    ----------
    topic
        Record key as recorded.
    payload
        Payload text.

    Returns
    -------
    tuple of (str, float) or None
        Signal name (``main/<Name>``, ``1wire/<id>``, ``cmd/<Command>``,
        :data:`ROOM_MIRROR`, :data:`LIVENESS`) and numeric value.
    """
    if topic.startswith(MIRROR):
        name = topic[len(MIRROR) :]
        if name != ROOM_MIRROR:
            return None
        number = _number(payload)
        return None if number is None else (ROOM_MIRROR, number)
    if not topic.startswith(BASE) or topic.endswith(_SKIP_SUFFIXES):
        return None
    name = topic[len(BASE) :]
    if name == "stats":
        return (LIVENESS, 1.0)
    if name.startswith("main/"):
        spec = CATALOGUE.get(name)
        if spec is not None and spec.kind is ValueKind.TEXT:
            return None
        number = _number(payload)
        if number is None:
            return None
        if spec is not None:
            low = -math.inf if spec.minimum is None else spec.minimum
            high = math.inf if spec.maximum is None else spec.maximum
            if not low <= number <= high:
                return None
        return (name, number)
    if name.startswith("1wire/"):
        number = _number(payload)
        return None if number is None or number <= -100 else (name, number)
    if name == "commands/SetCurves":
        setpoint = _setcurves_high(payload)
        return None if setpoint is None else (CMD_SETPOINT, setpoint)
    if name.startswith("commands/"):
        number = _number(payload)
        return None if number is None else ("cmd/" + name[len("commands/") :], float(int(number)))
    return None


def parse_lines(lines: Iterator[str]) -> dict[str, Series]:
    """Parse capture lines into one series per signal.

    Parameters
    ----------
    lines
        Lines of a capture file, including its header.

    Returns
    -------
    dict of str to Series
        Numeric series keyed by signal name.
    """
    times: dict[str, list[float]] = {}
    values: dict[str, list[float]] = {}
    for line in lines:
        if '/alias"' in line or "/LWT" in line:
            continue
        record = parse_capture_line(line)
        if record is None:
            continue
        decoded = decode(record.topic, record.payload)
        if decoded is None:
            continue
        signal, value = decoded
        times.setdefault(signal, []).append(record.t)
        values.setdefault(signal, []).append(value)
    return {key: Series.from_pairs(times[key], values[key]) for key in times}


def _cache_path(path: Path) -> Path:
    """Return the path of the ``.npz`` cache that belongs to the capture file ``path``."""
    stem = path.name.removesuffix(".gz").removesuffix(".jsonl")
    return path.parent.parent / "cache" / path.parent.name / f"{stem}.npz"


def _fingerprint(path: Path) -> np.ndarray:
    """Return the version, size and mtime of ``path``, which identify a cache as current."""
    stat = path.stat()
    return np.array([CACHE_VERSION, stat.st_size, stat.st_mtime_ns], dtype=np.int64)


def _read_cache(cache: Path, fingerprint: np.ndarray) -> dict[str, Series] | None:
    """Return the cached series when ``cache`` matches ``fingerprint``, otherwise ``None``."""
    if not cache.exists():
        return None
    try:
        with np.load(cache, allow_pickle=False) as data:
            if not np.array_equal(data["__fingerprint__"], fingerprint):
                return None
            keys = [str(k) for k in data["__keys__"]]
            return {key: Series(data[f"t{i}"], data[f"v{i}"]) for i, key in enumerate(keys)}
    except OSError, KeyError, ValueError:
        return None


def _write_cache(cache: Path, fingerprint: np.ndarray, series: dict[str, Series]) -> None:
    """Write ``series`` and ``fingerprint`` to ``cache`` atomically (temp file, then rename)."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(series)
    arrays: dict[str, np.ndarray] = {
        "__fingerprint__": fingerprint,
        "__keys__": np.array(keys, dtype=np.str_),
    }
    for i, key in enumerate(keys):
        arrays[f"t{i}"] = series[key].t
        arrays[f"v{i}"] = series[key].v
    tmp = cache.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, allow_pickle=False, **arrays)
    tmp.replace(cache)


def load_file(path: Path, *, use_cache: bool = True) -> dict[str, Series]:
    """Load one capture day file, using the cache when it is current.

    Parameters
    ----------
    path
        A ``.jsonl`` or ``.jsonl.gz`` capture file.
    use_cache
        Read and write the ``.npz`` cache.

    Returns
    -------
    dict of str to Series
        Numeric series of that file.
    """
    fingerprint = _fingerprint(path)
    cache = _cache_path(path)
    if use_cache:
        cached = _read_cache(cache, fingerprint)
        if cached is not None:
            return cached
    with _open(path) as handle:
        series = parse_lines(iter(handle))
    if use_cache:
        with contextlib.suppress(OSError):
            _write_cache(cache, fingerprint, series)
    return series


def capture_files(directory: Path) -> list[Path]:
    """Return the day files of a capture directory in date order.

    A day present both as ``.jsonl`` and ``.jsonl.gz`` is read from the closed
    ``.gz`` file only.
    """
    by_day: dict[str, Path] = {}
    for path in sorted(directory.glob("*.jsonl*")):
        day = path.name.split(".", 1)[0]
        if path.suffix == ".gz" or day not in by_day:
            by_day[day] = path
    return [by_day[day] for day in sorted(by_day)]


def load_capture(directory: Path, *, use_cache: bool = True) -> dict[str, Series]:
    """Load every day file of a capture directory.

    Parameters
    ----------
    directory
        Capture directory, e.g. ``capture/captures/live``.
    use_cache
        Use the per-day ``.npz`` cache.

    Returns
    -------
    dict of str to Series
        Merged numeric series over the whole capture.
    """
    return merge_maps(load_file(path, use_cache=use_cache) for path in capture_files(directory))
