"""Write raw samples and incrementally maintained rollups; apply retention.

Raw samples are stored when a signal's value changes. Every live reading (also an
unchanged one) confirms the value held since the previous reading; that held
interval is integrated into the 1 min, 15 min and 1 h rollup buckets it overlaps,
so a rollup's mean is time-weighted. A value is held for at most ``max_hold``
seconds (the signal's staleness limit), so an outage is a gap, not a plateau; a
gap sample (``value`` ``None``, sent when a value became unavailable) ends the
held interval at once.

Retention never deletes a signal's most recent raw sample, so a raw query can
always report the value a signal has held since its last change.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from ovenbird.history.snapshot import write_snapshot
from ovenbird_core import (
    CATALOGUE,
    HeishaSignal,
    ParseError,
    Reading,
    Snapshot,
    StalenessPolicy,
    ValueKind,
    heat_delivered_w,
)

ROLLUP_STEPS: Final = (60, 900, 3600)
SECONDS_PER_DAY: Final = 86_400.0
INCREMENTAL_VACUUM: Final = 2
HEAT_SIGNAL: Final = "derived/heat_delivered_w"
HEAT_UNIT: Final = "W"
HEAT_DECIMALS: Final = 1
HEAT_INPUTS: Final = frozenset(
    {
        HeishaSignal.COMPRESSOR_FREQ,
        HeishaSignal.THREEWAY_VALVE_STATE,
        HeishaSignal.PUMP_FLOW,
        HeishaSignal.INLET_TEMP,
        HeishaSignal.OUTLET_TEMP,
    }
)

DELETE_OLD_SAMPLES: Final = """
DELETE FROM sample
WHERE ts < ?
  AND ts < (SELECT max(newer.ts) FROM sample AS newer WHERE newer.signal_id = sample.signal_id)
"""

UPSERT_ROLLUP: Final = """
INSERT INTO rollup
    (step, signal_id, bucket, weighted_sum, duration, minimum, maximum, last, last_ts)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (step, signal_id, bucket) DO UPDATE SET
    weighted_sum = weighted_sum + excluded.weighted_sum,
    duration = duration + excluded.duration,
    minimum = min(minimum, excluded.minimum),
    maximum = max(maximum, excluded.maximum),
    last = CASE WHEN excluded.last_ts >= last_ts THEN excluded.last ELSE last END,
    last_ts = max(last_ts, excluded.last_ts)
"""


class SampleKind(StrEnum):
    """How a signal is aggregated: numbers are averaged, enums and flags take the last value."""

    NUMBER = "number"
    ENUM = "enum"
    BOOL = "bool"


@dataclass(frozen=True, slots=True)
class Sample:
    """One numeric observation handed to the history writer.

    Parameters
    ----------
    signal
        Signal id.
    unit
        Unit of the value.
    kind
        Aggregation kind.
    ts
        Wall-clock unix seconds of the observation.
    value
        Numeric value (flags as 0/1, enums as their code); ``None`` marks a gap:
        the previous value stopped being valid at ``ts``.
    max_hold
        Longest interval the value may be held until the next observation.
    """

    signal: str
    unit: str | None
    kind: SampleKind
    ts: float
    value: float | None
    max_hold: float


def gap_sample(error: ParseError) -> Sample | None:
    """Return the gap sample for a live error that invalidated a value.

    Parameters
    ----------
    error
        A parse error the state store applied as an invalidation.

    Returns
    -------
    Sample or None
        A sample with ``value`` ``None`` at the error's time; ``None`` for
        retained errors.
    """
    if error.retained:
        return None
    return Sample(error.signal, None, SampleKind.NUMBER, error.observed.wall.timestamp(), None, 0.0)


def sample_from_reading(reading: Reading, policy: StalenessPolicy) -> Sample | None:
    """Turn a live numeric reading into a history sample.

    Parameters
    ----------
    reading
        A reading from the state store's input.
    policy
        Staleness policy; its maximum age bounds how long a value is held.

    Returns
    -------
    Sample or None
        ``None`` for retained deliveries (they carry no time information), text
        values and non-finite numbers.
    """
    if reading.retained:
        return None
    value = reading.value
    if isinstance(value, bool):
        kind, number = SampleKind.BOOL, float(value)
    elif isinstance(value, int | float):
        spec = CATALOGUE.get(reading.signal)
        kind = (
            SampleKind.ENUM
            if spec is not None and spec.kind is ValueKind.ENUM
            else SampleKind.NUMBER
        )
        number = float(value)
    else:
        return None
    if not math.isfinite(number):
        return None
    return Sample(
        reading.signal,
        reading.unit,
        kind,
        reading.observed.wall.timestamp(),
        number,
        policy.max_age(reading.signal, reading.source),
    )


def heat_sample(snapshot: Snapshot, policy: StalenessPolicy) -> Sample:
    """Turn the loop heat of a snapshot into a history sample (:data:`HEAT_SIGNAL`).

    The value is :func:`ovenbird_core.heat_delivered_w` as the API reports it (no
    inlet/outlet offset; 0 while the compressor is stopped, negative in a defrost).
    When it has no value (DHW run, missing or stale input) the sample is a gap, so
    the rollups do not hold the last value across it.

    Parameters
    ----------
    snapshot
        State right after a heat input changed.
    policy
        Staleness policy; the flow's maximum age bounds how long the value is held.

    Returns
    -------
    Sample
        The heat sample at the snapshot's time.
    """
    derived = heat_delivered_w(snapshot)
    value = None if derived.value is None else round(derived.value, HEAT_DECIMALS)
    flow = snapshot.signals.get(HeishaSignal.PUMP_FLOW)
    max_hold = policy.max_age(HeishaSignal.PUMP_FLOW, flow.source) if flow is not None else 0.0
    return Sample(
        HEAT_SIGNAL,
        HEAT_UNIT,
        SampleKind.NUMBER,
        snapshot.now.wall.timestamp(),
        value,
        max_hold,
    )


@dataclass(frozen=True, slots=True)
class Retention:
    """Retention per resolution in days; ``None`` keeps data forever.

    Parameters
    ----------
    raw_days, minute_days, quarter_days, hour_days
        Raw samples, 1 min, 15 min and 1 h rollups.
    """

    raw_days: float | None = 14.0
    minute_days: float | None = 90.0
    quarter_days: float | None = None
    hour_days: float | None = None

    def rollup_days(self) -> dict[int, float | None]:
        """Retention per rollup step in seconds."""
        return {60: self.minute_days, 900: self.quarter_days, 3600: self.hour_days}


@dataclass(slots=True)
class _Aggregate:
    """Running time-weighted aggregate of one signal in one rollup bucket."""

    weighted_sum: float = 0.0
    duration: float = 0.0
    minimum: float = math.inf
    maximum: float = -math.inf
    last: float = 0.0
    last_ts: float = -math.inf

    def add(self, value: float, duration: float, at: float) -> None:
        """Add a value held for ``duration`` seconds, last seen at ``at``."""
        self.weighted_sum += value * duration
        self.duration += duration
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        if at >= self.last_ts:
            self.last, self.last_ts = value, at


@dataclass(slots=True)
class _Held:
    """The last value of a signal, held until the next sample or a gap."""

    value: float
    ts: float


@dataclass
class WriteResult:
    """What one batch did.

    Parameters
    ----------
    samples
        Raw samples inserted (value changes).
    rollup_rows
        Rollup rows inserted or updated.
    skipped
        Samples older than the signal's previous one.
    """

    samples: int = 0
    rollup_rows: int = 0
    skipped: int = 0


@dataclass
class HistoryDatabase:
    """Owner of the writer connection; not thread-safe, used by one thread only.

    Parameters
    ----------
    conn
        Open, migrated writer connection (autocommit mode).
    """

    conn: sqlite3.Connection
    _signal_ids: dict[str, int] = field(default_factory=dict)
    _signal_meta: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    _held: dict[int, _Held] = field(default_factory=dict)
    _max_holds: dict[int, float] = field(default_factory=dict)

    def write_snapshot(self, target: Path) -> None:
        """Write a consistent copy of the database to ``target`` (see :mod:`.snapshot`)."""
        write_snapshot(self.conn, target)

    def forget_held(self) -> None:
        """Drop the held values, so no interval is integrated across a write gap."""
        self._held.clear()

    def _known_signal_id(self, name: str) -> int | None:
        """Return the id of a signal already stored, or ``None``."""
        known = self._signal_ids.get(name)
        if known is not None:
            return known
        row = self.conn.execute("SELECT id FROM signal WHERE name = ?", (name,)).fetchone()
        return None if row is None else int(row[0])

    def _signal_id(self, sample: Sample) -> int:
        """Return the id of the sample's signal, storing or updating it when needed."""
        meta = (sample.unit, sample.kind.value)
        known = self._signal_ids.get(sample.signal)
        if known is not None and self._signal_meta.get(sample.signal) == meta:
            return known
        self.conn.execute(
            "INSERT INTO signal (name, unit, kind) VALUES (?, ?, ?) "
            "ON CONFLICT (name) DO UPDATE SET unit = excluded.unit, kind = excluded.kind",
            (sample.signal, sample.unit, sample.kind.value),
        )
        row = self.conn.execute("SELECT id FROM signal WHERE name = ?", (sample.signal,)).fetchone()
        signal_id = int(row[0])
        self._signal_ids[sample.signal] = signal_id
        self._signal_meta[sample.signal] = meta
        return signal_id

    def write_batch(self, samples: Iterable[Sample]) -> WriteResult:
        """Store samples and update the rollups in one transaction.

        Parameters
        ----------
        samples
            Samples in arrival order.

        Returns
        -------
        WriteResult
            Counters for this batch.
        """
        result = WriteResult()
        aggregates: dict[tuple[int, int, int], _Aggregate] = {}
        raw_rows: list[tuple[int, float, float]] = []
        held_before = dict(self._held)
        self.conn.execute("BEGIN")
        try:
            for sample in samples:
                if sample.value is None:
                    self._end_hold(sample, aggregates)
                    continue
                signal_id = self._signal_id(sample)
                held = self._held.get(signal_id)
                if held is not None and sample.ts < held.ts:
                    result.skipped += 1
                    continue
                if held is not None:
                    end = min(sample.ts, held.ts + sample.max_hold)
                    _integrate(aggregates, signal_id, held.value, held.ts, end)
                if held is None or held.value != sample.value:
                    raw_rows.append((signal_id, sample.ts, sample.value))
                for step in ROLLUP_STEPS:
                    bucket = _bucket(sample.ts, step)
                    aggregates.setdefault((step, signal_id, bucket), _Aggregate()).add(
                        sample.value, 0.0, sample.ts
                    )
                self._held[signal_id] = _Held(sample.value, sample.ts)
                self._max_holds[signal_id] = sample.max_hold
            self.conn.executemany(
                "INSERT OR REPLACE INTO sample (signal_id, ts, value) VALUES (?, ?, ?)", raw_rows
            )
            self.conn.executemany(
                UPSERT_ROLLUP,
                [
                    (
                        step,
                        signal_id,
                        bucket,
                        agg.weighted_sum,
                        agg.duration,
                        agg.minimum,
                        agg.maximum,
                        agg.last,
                        agg.last_ts,
                    )
                    for (step, signal_id, bucket), agg in aggregates.items()
                ],
            )
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            self._held = held_before
            self._signal_ids.clear()
            self._signal_meta.clear()
            raise
        result.samples = len(raw_rows)
        result.rollup_rows = len(aggregates)
        return result

    def _end_hold(self, gap: Sample, aggregates: dict[tuple[int, int, int], _Aggregate]) -> None:
        """End the held value of the gap's signal at the gap, adding it to the rollups."""
        signal_id = self._known_signal_id(gap.signal)
        if signal_id is None:
            return
        held = self._held.pop(signal_id, None)
        if held is None:
            return
        if gap.ts < held.ts:
            self._held[signal_id] = held
            return
        max_hold = self._max_holds.get(signal_id, 0.0)
        _integrate(aggregates, signal_id, held.value, held.ts, min(gap.ts, held.ts + max_hold))

    def apply_retention(self, retention: Retention, now: float) -> int:
        """Delete data older than the retention limits; a signal's newest raw sample stays.

        Parameters
        ----------
        retention
            Limits per resolution.
        now
            Current wall-clock unix seconds.

        Returns
        -------
        int
            Rows deleted.
        """
        deleted = 0
        self.conn.execute("BEGIN")
        try:
            if retention.raw_days is not None:
                cutoff = now - retention.raw_days * SECONDS_PER_DAY
                deleted += self.conn.execute(DELETE_OLD_SAMPLES, (cutoff,)).rowcount
            for step, days in retention.rollup_days().items():
                if days is None:
                    continue
                cutoff = now - days * SECONDS_PER_DAY
                deleted += self.conn.execute(
                    "DELETE FROM rollup WHERE step = ? AND bucket + ? <= ?", (step, step, cutoff)
                ).rowcount
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return deleted

    def release_free_pages(self) -> None:
        """Give free pages back to the file system (in incremental auto-vacuum mode only)."""
        mode = int(self.conn.execute("PRAGMA auto_vacuum").fetchone()[0])
        if mode == INCREMENTAL_VACUUM:
            self.conn.execute("PRAGMA incremental_vacuum").fetchall()

    def close(self) -> None:
        """Optimise and close the connection."""
        try:
            self.conn.execute("PRAGMA optimize")
        finally:
            self.conn.close()


def _bucket(ts: float, step: int) -> int:
    """Return the start of the ``step`` second bucket holding ``ts``."""
    return math.floor(ts / step) * step


def _integrate(
    aggregates: dict[tuple[int, int, int], _Aggregate],
    signal_id: int,
    value: float,
    start: float,
    end: float,
) -> None:
    """Add a value held from ``start`` to ``end`` to the aggregate of every rollup step it spans.

    Parameters
    ----------
    aggregates
        Aggregates by ``(signal id, step, bucket)`` to add to.
    signal_id
        Signal the value belongs to.
    value
        Held value.
    start
        Start of the hold, Unix time.
    end
        End of the hold, Unix time.
    """
    for step in ROLLUP_STEPS:
        cursor = start
        while cursor < end:
            bucket = _bucket(cursor, step)
            segment_end = min(end, bucket + step)
            aggregates.setdefault((step, signal_id, bucket), _Aggregate()).add(
                value, segment_end - cursor, cursor
            )
            cursor = segment_end
