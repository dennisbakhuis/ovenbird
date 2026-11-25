"""On-disk capture format: one JSON record per MQTT message, one file per UTC day.

Layout::

    captures/<name>/
        meta.json              # name, broker, filters, started
        2026-01-05.jsonl.gz    # closed days are gzipped
        2026-01-05.jsonl       # the active day stays plain text

Each file starts with a header record ``{"v": 1, ...}``; every other line is a
message record with short keys: ``t`` unix seconds, ``k`` topic, ``p`` payload,
``r`` set only when the broker delivered the message from its retained store.

The ``r`` flag does **not** say whether the publisher used ``retain`` — MQTT
3.1.1 clears it on live deliveries — so replay decides retain from the topic
class instead (:func:`is_retained`).
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any, Final

FORMAT_VERSION: Final = 1
FSYNC_INTERVAL_S: Final = 30.0
_DAY_RE: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl(\.gz)?$")
_DURATION_RE: Final = re.compile(r"(\d+(?:\.\d+)?)([dhms]?)")
_DURATION_UNITS: Final = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0, "": 1.0}


@dataclass(frozen=True, slots=True)
class Record:
    """One captured MQTT message."""

    t: float
    topic: str
    payload: str
    retained: bool = False

    def to_json(self) -> str:
        """Serialise to one JSON line (without newline)."""
        obj: dict[str, Any] = {"t": round(self.t, 3), "k": self.topic, "p": self.payload}
        if self.retained:
            obj["r"] = True
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> Record | None:
        """Parse one line; returns ``None`` for header lines and blanks."""
        line = line.strip()
        if not line:
            return None
        obj = json.loads(line)
        if "k" not in obj:
            return None
        return cls(float(obj["t"]), str(obj["k"]), str(obj["p"]), bool(obj.get("r", False)))


def is_retained(topic: str, payload: str) -> bool:
    """Whether HeishaMon would have published ``topic`` with the retain flag."""
    parts = topic.split("/")
    if "commands" in parts:
        return False
    if parts[-1] == "log":
        return False
    return not (parts[-1] == "LWT" and payload.strip().lower() == "online")


def topic_suffix(topic: str, base: str) -> str | None:
    """Strip ``base/`` from ``topic``; ``None`` when the topic is outside the base."""
    prefix = f"{base}/"
    return topic[len(prefix) :] if topic.startswith(prefix) else None


def day_of(t: float) -> str:
    """UTC calendar day of a unix timestamp as ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")


def parse_when(text: str, capture_start: float) -> float:
    """Parse ``+1h30m``-style offsets from ``capture_start`` or an ISO datetime.

    Naive ISO datetimes are interpreted in local time.
    """
    text = text.strip()
    if text.startswith("+"):
        body = text[1:]
        if not body or not re.fullmatch(r"(?:\d+(?:\.\d+)?[dhms]?)+", body):
            raise ValueError(f"invalid offset: {text!r}")
        total = sum(
            float(value) * _DURATION_UNITS[unit] for value, unit in _DURATION_RE.findall(body)
        )
        return capture_start + total
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()


class CaptureWriter:
    """Append records to day files, rotating and gzipping at UTC midnight.

    Thread-safe: paho delivers messages on its network thread while the
    process's main thread drives heartbeats.

    Parameters
    ----------
    directory
        Parent directory holding all captures.
    name
        Capture name; files go to ``directory/name``.
    header
        Extra fields written into every file header and ``meta.json``.
    clock
        Time source, injectable for tests.
    """

    def __init__(
        self,
        directory: Path | str,
        name: str,
        *,
        header: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(directory) / name
        self.path.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._header = {"v": FORMAT_VERSION, "name": name, **(header or {})}
        self._lock = threading.Lock()
        self._file: IO[str] | None = None
        self._day: str | None = None
        self._last_fsync = clock()
        self._threads: list[threading.Thread] = []
        self.records_written = 0
        self.bytes_written = 0
        self._write_meta()
        self._compress_leftovers()

    @property
    def active_file(self) -> Path | None:
        """Path of the day file currently being written."""
        return self.path / f"{self._day}.jsonl" if self._day else None

    def _write_meta(self) -> None:
        meta_path = self.path / "meta.json"
        meta = {**self._header, "started": datetime.fromtimestamp(self._clock(), UTC).isoformat()}
        if meta_path.exists():
            with meta_path.open(encoding="utf-8") as fh:
                existing = json.load(fh)
            meta["started"] = existing.get("started", meta["started"])
            meta["resumed"] = datetime.fromtimestamp(self._clock(), UTC).isoformat()
        with meta_path.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")

    def _compress_leftovers(self) -> None:
        today = day_of(self._clock())
        for plain in sorted(self.path.glob("*.jsonl")):
            if plain.stem != today:
                self._compress_async(plain)

    def _compress_async(self, plain: Path) -> None:
        thread = threading.Thread(target=_gzip_file, args=(plain,), daemon=True)
        thread.start()
        self._threads.append(thread)

    def _open_day(self, day: str) -> None:
        target = self.path / f"{day}.jsonl"
        new_file = not target.exists() or target.stat().st_size == 0
        self._file = target.open("a", encoding="utf-8")
        if new_file:
            header = {
                **self._header,
                "started": datetime.fromtimestamp(self._clock(), UTC).isoformat(),
            }
            self._file.write(json.dumps(header, separators=(",", ":")) + "\n")
        self._day = day

    def _rotate_locked(self, day: str) -> None:
        previous = self.active_file
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None
        self._open_day(day)
        if previous is not None and previous.exists():
            self._compress_async(previous)

    def write(self, record: Record) -> None:
        """Append one record, rotating the day file when the UTC day changes."""
        line = record.to_json() + "\n"
        with self._lock:
            day = day_of(record.t)
            if self._file is None or day != self._day:
                self._rotate_locked(day)
            assert self._file is not None
            self._file.write(line)
            self._file.flush()
            self.records_written += 1
            self.bytes_written += len(line.encode("utf-8"))
            now = self._clock()
            if now - self._last_fsync >= FSYNC_INTERVAL_S:
                os.fsync(self._file.fileno())
                self._last_fsync = now

    def close(self) -> None:
        """Flush and close the active file; wait for pending compressions."""
        with self._lock:
            if self._file is not None:
                self._file.flush()
                os.fsync(self._file.fileno())
                self._file.close()
                self._file = None
        for thread in self._threads:
            thread.join(timeout=60)


def _gzip_file(plain: Path) -> None:
    target = plain.with_suffix(".jsonl.gz")
    tmp = target.with_suffix(".gz.tmp")
    with plain.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    tmp.replace(target)
    plain.unlink()


class CaptureReader:
    """Stream records from a capture directory in time order.

    Parameters
    ----------
    directory
        The ``captures/<name>`` directory.
    """

    def __init__(self, directory: Path | str) -> None:
        self.path = Path(directory)
        if not self.path.is_dir():
            raise FileNotFoundError(f"capture directory not found: {self.path}")

    def meta(self) -> dict[str, Any]:
        """Return ``meta.json`` contents, or ``{}`` when absent."""
        meta_path = self.path / "meta.json"
        if not meta_path.exists():
            return {}
        with meta_path.open(encoding="utf-8") as fh:
            result: dict[str, Any] = json.load(fh)
        return result

    def files(self) -> list[Path]:
        """Day files in chronological order; a plain file wins over its gzip twin."""
        by_day: dict[str, Path] = {}
        for candidate in self.path.iterdir():
            match = _DAY_RE.match(candidate.name)
            if not match:
                continue
            day, gz = match.group(1), match.group(2)
            if day not in by_day or not gz:
                by_day[day] = candidate
        return [by_day[day] for day in sorted(by_day)]

    @staticmethod
    def _open(path: Path) -> IO[str]:
        if path.suffix == ".gz":
            return gzip.open(path, "rt", encoding="utf-8")
        return path.open("r", encoding="utf-8")

    def iter_records(
        self,
        start: float | None = None,
        end: float | None = None,
    ) -> Iterator[Record]:
        """Yield records with ``start <= t < end`` across all day files."""
        start_day = day_of(start - 86400) if start is not None else None
        end_day = day_of(end) if end is not None else None
        for path in self.files():
            day = path.name[:10]
            if (start_day is not None and day < start_day) or (
                end_day is not None and day > end_day
            ):
                continue
            with self._open(path) as fh:
                for line in fh:
                    record = Record.from_json(line)
                    if record is None:
                        continue
                    if start is not None and record.t < start:
                        continue
                    if end is not None and record.t >= end:
                        return
                    yield record

    def bounds(self) -> tuple[float, float]:
        """First and last record timestamps."""
        first: float | None = None
        last: float | None = None
        for record in self.iter_records():
            if first is None:
                first = record.t
            last = record.t
        if first is None or last is None:
            raise ValueError(f"capture is empty: {self.path}")
        return first, last

    def snapshot_at(self, t: float) -> dict[str, str]:
        """Latest retained-class payload per topic strictly before ``t``."""
        snapshot: dict[str, str] = {}
        for record in self.iter_records(end=t):
            if is_retained(record.topic, record.payload):
                snapshot[record.topic] = record.payload
        return snapshot


def format_duration(seconds: float) -> str:
    """Render seconds as ``1d 02:03:04``."""
    delta = timedelta(seconds=int(seconds))
    days, rest = divmod(int(delta.total_seconds()), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    prefix = f"{days}d " if days else ""
    return f"{prefix}{hours:02d}:{minutes:02d}:{secs:02d}"
