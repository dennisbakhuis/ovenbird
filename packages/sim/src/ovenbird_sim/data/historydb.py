"""Read the service's ``history.db`` (or its ``history.snapshot.db``) into a :class:`Dataset`.

The service stores every signal's time-weighted 1 min, 15 min and 1 h rollups
(``rollup``: ``weighted_sum``, ``duration``, ``minimum``, ``maximum``, ``last`` per
bucket); the 15 min and 1 h ones are kept forever, the 1 min ones for 90 days by
default. A dataset is built from one rollup step: the bucket mean is the column
value where the bucket is at least half covered (``duration / step``), else ``NaN``.

What differs from a capture (:func:`ovenbird_sim.data.dataset.assemble`, 5 s data):

* the compressor's running share of a bucket is ``mean / maximum`` of
  ``Compressor_Freq`` (1 with a positive minimum, 0 with a zero maximum);
* loop heat is the stored ``derived/heat_delivered_w`` (the live
  ``flow x spread`` the service computes, 0 with the compressor stopped, a gap in
  DHW) minus the calibrated inlet/outlet offset over the running share; older
  history without it falls back to ``mean(flow) x mean(spread)`` (flagged in the
  notes: it misses the covariance within a bucket);
* there is no ``stats`` liveness, so ``gap`` marks buckets without any HeishaMon
  loop signal and ``stale`` buckets where one of them is under half covered;
* rooms, time zone and the wood-stove reference come from the service
  configuration (:class:`HistoryRoles`), not from the owner's entity ids;
* the service's wood-stove journal (alarm code ``stove_mode``) adds known events
  next to the detector (which needs a reference room), and the days the owner left
  out can be passed in as known events too;
* weather comes from the stored forecasts (``forecast``): per target hour the row
  with the shortest lead (non-negative first) stands in for the observation. Only
  global horizontal irradiance (GHI, preceding-hour mean) is stored, so direct and
  diffuse radiation, and thus the facade orientation, cannot be separated: the
  solar aperture is an effective GHI aperture. An Open-Meteo cache can replace the
  forecasts (:func:`ovenbird_sim.data.weather.load_weather`).

The database is opened read-only and immutable: point it at the snapshot (replaced
atomically by the service) or at a closed database, never at the live WAL file.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L
from ovenbird_sim.data import events as ev
from ovenbird_sim.data.dataset import (
    MAIN_SIGNALS,
    Dataset,
    RoomRoles,
    calibrate_offset,
    finish,
    heat_from_loop,
)
from ovenbird_sim.data.grid import TimeGrid
from ovenbird_sim.data.series import BoolArray, FloatArray, Series

MINUTE: Final = 60
QUARTER: Final = 900
HOUR: Final = 3600
MIN_COVERAGE: Final = 0.5
GAP_COVERAGE: Final = 0.05
HEAT_SIGNAL: Final = "derived/heat_delivered_w"
STOVE_JOURNAL_CODE: Final = "stove_mode"
STOVE_STARTED: Final = "started"
COMPRESSOR: Final = "main/Compressor_Freq"
DEFROST: Final = "main/Defrosting_State"
VALVE: Final = "main/ThreeWay_Valve_State"
LOOP: Final = ("inlet", "outlet", "flow", "hz")
ROOM_COLUMN: Final = "room"
REFERENCE_PREFIX: Final = "room_ref_"
FORECAST_SERIES: Final[Mapping[str, str]] = {
    "temp_c": "wx/temperature_2m",
    "radiation_wm2": "wx/shortwave_radiation",
    "cloud_pct": "wx/cloud_cover",
    "wind_ms": "wx/wind_speed_10m",
}
KMH_PER_MS: Final = 3.6
RADIATION_SHIFT_S: Final = -1800.0
OUTSIDE_FILL_S: Final = 6 * 3600.0
W_PER_LPM_K: Final = WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K / 60.0


@dataclass(frozen=True, slots=True)
class HistoryRoles:
    """Which history signals play which role, from the service configuration.

    Parameters
    ----------
    room
        Signal id of the controlled room (``control_room_signal``).
    references
        Rooms away from the wood stove (``control_stove_reference_signal``); they feed
        the stove detector and the house mean.
    timezone
        IANA time zone of the installation (``control_timezone``).
    """

    room: str | None
    references: tuple[str, ...] = ()
    timezone: str = "UTC"

    def room_roles(self) -> RoomRoles:
        """Column roles of the assembled dataset."""
        refs = tuple(f"{REFERENCE_PREFIX}{i + 1}" for i in range(len(self.references)))
        return RoomRoles((ROOM_COLUMN,), (ROOM_COLUMN, *refs), refs)


def effective_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the flat ``field: value`` mapping of a configuration document.

    Accepts the body of ``GET api/v1/config`` (``fields.<name>.value``), the export
    file (``effective``), a seed file (``values``) or a flat mapping.
    """
    fields = payload.get("fields")
    if isinstance(fields, Mapping):
        return {
            str(name): entry.get("value") if isinstance(entry, Mapping) else entry
            for name, entry in fields.items()
        }
    effective = payload.get("effective")
    if isinstance(effective, Mapping):
        return dict(effective)
    values = payload.get("values")
    if isinstance(values, Mapping):
        return dict(values)
    return dict(payload)


def load_config(path: Path) -> dict[str, Any]:
    """Read a configuration document (see :func:`effective_config`)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return effective_config(payload)


def roles_from_config(config: Mapping[str, Any]) -> HistoryRoles:
    """Build the roles from an effective configuration mapping."""
    room = config.get("control_room_signal") or None
    reference = config.get("control_stove_reference_signal") or None
    refs = (str(reference),) if reference and reference != room else ()
    return HistoryRoles(
        room=None if room is None else str(room),
        references=refs,
        timezone=str(config.get("control_timezone") or "UTC"),
    )


def connect(path: Path) -> sqlite3.Connection:
    """Open a history database read-only and immutable."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def signal_ids(conn: sqlite3.Connection) -> dict[str, int]:
    """Signal name to id."""
    return {str(name): int(i) for i, name in conn.execute("SELECT id, name FROM signal")}


def rollup_span(conn: sqlite3.Connection, step: int) -> tuple[float, float] | None:
    """First bucket start and last bucket end of a rollup step, or ``None`` when empty."""
    row = conn.execute(
        "SELECT min(bucket), max(bucket) FROM rollup WHERE step = ?", (step,)
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0]), float(row[1]) + step


@dataclass(frozen=True, slots=True)
class Rollup:
    """One signal's rollups on a grid.

    Parameters
    ----------
    mean, last, minimum, maximum
        Bucket values (``NaN`` where the bucket has no row).
    coverage
        Covered share of each bucket.
    """

    mean: FloatArray
    last: FloatArray
    minimum: FloatArray
    maximum: FloatArray
    coverage: FloatArray

    def valid(self, threshold: float = MIN_COVERAGE) -> FloatArray:
        """Mean where the bucket is at least ``threshold`` covered, else ``NaN``."""
        return np.where(self.coverage >= threshold, self.mean, np.nan)


def _empty(n: int) -> Rollup:
    """Return a rollup of ``n`` empty (NaN, zero coverage) buckets."""
    nan = np.full(n, np.nan)
    return Rollup(nan, nan.copy(), nan.copy(), nan.copy(), np.zeros(n))


def read_rollup(conn: sqlite3.Connection, signal_id: int | None, grid: TimeGrid) -> Rollup:
    """Read one signal's rollups of step ``grid.step`` onto ``grid``.

    Parameters
    ----------
    conn
        Open connection to the history database.
    signal_id
        Row id of the signal; ``None`` (signal not recorded) gives an empty rollup.
    grid
        Time grid whose step selects the rollup resolution and whose span is read.

    Returns
    -------
    Rollup
        Mean, minimum, maximum, last value and coverage per grid bucket; NaN where unrecorded.
    """
    n = grid.n
    if signal_id is None:
        return _empty(n)
    step = round(grid.step)
    rows = conn.execute(
        "SELECT bucket, weighted_sum, duration, minimum, maximum, last FROM rollup "
        "WHERE step = ? AND signal_id = ? AND bucket >= ? AND bucket < ? ORDER BY bucket",
        (step, signal_id, grid.start, grid.end),
    ).fetchall()
    out = _empty(n)
    if not rows:
        return out
    data = np.asarray(rows, dtype=np.float64)
    idx = np.round((data[:, 0] - grid.start) / grid.step).astype(np.intp)
    ok = (idx >= 0) & (idx < n)
    idx, data = idx[ok], data[ok]
    duration = data[:, 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(duration > 0, data[:, 1] / duration, np.nan)
    out.mean[idx] = mean
    out.minimum[idx] = data[:, 3]
    out.maximum[idx] = data[:, 4]
    out.last[idx] = data[:, 5]
    out.coverage[idx] = np.clip(duration / grid.step, 0.0, 1.0)
    return out


def read_forecast_weather(conn: sqlite3.Connection, start: float, end: float) -> dict[str, Series]:
    """Return the stored forecasts as weather series: the shortest-lead row per target hour.

    Parameters
    ----------
    conn
        History connection.
    start, end
        Span in unix seconds.

    Returns
    -------
    dict of str to Series
        ``wx/temperature_2m``, ``wx/shortwave_radiation`` (moved to the middle of its
        averaging hour), ``wx/cloud_cover`` and ``wx/wind_speed_10m`` (km/h, as the
        Open-Meteo cache); empty without forecasts.
    """
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forecast'"
    ).fetchone()
    if has_table is None:
        return {}
    rows = conn.execute(
        "SELECT target_ts, temp_c, radiation_wm2, cloud_pct, wind_ms FROM ("
        " SELECT target_ts, temp_c, radiation_wm2, cloud_pct, wind_ms,"
        " row_number() OVER (PARTITION BY target_ts ORDER BY"
        " CASE WHEN target_ts >= issued_ts THEN 0 ELSE 1 END,"
        " abs(target_ts - issued_ts), issued_ts) AS rank"
        " FROM forecast WHERE target_ts >= ? AND target_ts < ?)"
        " WHERE rank = 1 ORDER BY target_ts",
        (start - HOUR, end + HOUR),
    ).fetchall()
    if not rows:
        return {}
    t = np.array([float(r[0]) for r in rows])
    out: dict[str, Series] = {}
    for k, (column, key) in enumerate(FORECAST_SERIES.items(), start=1):
        values = np.array([math.nan if r[k] is None else float(r[k]) for r in rows])
        if column == "wind_ms":
            values = values * KMH_PER_MS
        shift = RADIATION_SHIFT_S if column == "radiation_wm2" else 0.0
        ok = np.isfinite(values)
        if ok.any():
            out[key] = Series(t[ok] + shift, values[ok])
    return out


def read_stove_journal(
    conn: sqlite3.Connection,
    start: float,
    end: float,
    capped: list[float] | None = None,
) -> tuple[ev.Event, ...]:
    """Wood-stove mode episodes from the service's alarm journal, as known events.

    An episode without a recorded end (a service restart lost it) is closed at the next
    ``started`` or :data:`OPEN_EPISODE_MAX_S` after its start, whichever comes first.

    Parameters
    ----------
    conn
        Open history database.
    start, end
        Span in unix seconds.
    capped
        When given, receives the start of every open episode that was closed this way.
    """
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alarm'"
    ).fetchone()
    if has_table is None:
        return ()
    rows = conn.execute(
        "SELECT ts, event FROM alarm WHERE code = ? AND ts >= ? AND ts < ? ORDER BY ts, id",
        (STOVE_JOURNAL_CODE, start - 2 * 86400.0, end),
    ).fetchall()
    found: list[ev.Event] = []
    began: float | None = None

    def close_open(opened: float, limit: float, final: bool = False) -> None:
        """Close the stove-mode episode opened at ``opened``, capped at the maximum length."""
        stop = min(limit, opened + OPEN_EPISODE_MAX_S)
        if capped is not None and (stop < limit or not final):
            capped.append(opened)
        found.append(ev.Event(ev.STOVE_MODE, opened, stop, stop + ev.TAIL_S, *_NAN2))

    for ts, kind in rows:
        if kind == STOVE_STARTED:
            if began is not None:
                close_open(began, float(ts))
            began = float(ts)
        elif began is not None:
            found.append(ev.Event(ev.STOVE_MODE, began, float(ts), float(ts) + ev.TAIL_S, *_NAN2))
            began = None
    if began is not None:
        close_open(began, end, True)
    return tuple(e for e in found if e.tail_end > start)


OPEN_EPISODE_MAX_S: Final = 24 * 3600.0
_NAN2: Final = (math.nan, math.nan)


@dataclass(frozen=True, slots=True)
class HistoryData:
    """A dataset built from history with what it was built from.

    Parameters
    ----------
    dataset
        The aligned dataset.
    step
        Rollup step used.
    notes
        Provenance: signals found or missing, heat source, weather source, events.
    """

    dataset: Dataset
    step: int
    notes: dict[str, Any] = field(default_factory=dict)


def history_dataset(
    path: Path,
    roles: HistoryRoles,
    *,
    step: int = MINUTE,
    start: float | None = None,
    end: float | None = None,
    weather: Mapping[str, Series] | None = None,
    excluded: tuple[ev.Event, ...] = (),
) -> HistoryData:
    """Assemble a dataset from a history database.

    Parameters
    ----------
    path
        ``history.snapshot.db`` (or a closed ``history.db``).
    roles
        Room, reference rooms and time zone.
    step
        Rollup step: 60 (1 min, the identification grid) or 900 (15 min, kept forever).
    start, end
        Optional span in unix seconds (clipped to the stored rollups).
    weather
        Weather series replacing the stored forecasts (an Open-Meteo cache).
    excluded
        Days the owner left out (:func:`ovenbird_sim.data.events.excluded_days`),
        flagged like the wood-stove events but kept apart from them.

    Returns
    -------
    HistoryData
        Dataset, switching signals and provenance notes.

    Raises
    ------
    ValueError
        When the database has no rollups of ``step`` in the span or no loop signals.
    """
    with connect(path) as conn:
        span = rollup_span(conn, step)
        if span is None:
            raise ValueError(f"{path} holds no {step} s rollups")
        t0 = span[0] if start is None else max(span[0], math.floor(start / step) * step)
        t1 = span[1] if end is None else min(span[1], math.ceil(end / step) * step)
        if t1 - t0 < step:
            raise ValueError(f"{path} holds no {step} s rollups in the span")
        grid = TimeGrid(t0, float(step), round((t1 - t0) / step))
        ids = signal_ids(conn)
        missing = [s for s in (*MAIN_SIGNALS.values(), DEFROST, VALVE) if s not in ids]
        rollups = {
            name: read_rollup(conn, ids.get(sig), grid) for name, sig in MAIN_SIGNALS.items()
        }
        defrost = read_rollup(conn, ids.get(DEFROST), grid)
        valve = read_rollup(conn, ids.get(VALVE), grid)
        heat_stored = read_rollup(conn, ids.get(HEAT_SIGNAL), grid)
        room = read_rollup(conn, ids.get(roles.room) if roles.room else None, grid)
        refs = [read_rollup(conn, ids.get(sig), grid) for sig in roles.references]
        wx = dict(weather) if weather is not None else read_forecast_weather(conn, t0, t1)
        capped_starts: list[float] = []
        journal = read_stove_journal(conn, t0, t1, capped_starts)
    if all(rollups[name].coverage.max(initial=0.0) == 0.0 for name in LOOP):
        raise ValueError(f"{path} holds no HeishaMon loop signals")
    data = _assemble(
        grid,
        rollups,
        defrost,
        valve,
        heat_stored,
        room,
        refs,
        wx,
        journal,
        roles,
        excluded=tuple(e for e in excluded if e.tail_end > t0 and e.start < t1),
        notes={
            "source": str(path),
            "step_s": step,
            "missing_signals": missing,
            "room_signal": roles.room,
            "reference_signals": list(roles.references),
            "timezone": roles.timezone,
            "weather": "open-meteo cache"
            if weather is not None
            else ("stored forecasts (shortest lead)" if wx else "none"),
        },
    )
    if capped_starts:
        data.notes["stove_journal"] = (
            f"{len(capped_starts)} wood-stove episode(s) without a recorded end capped at "
            f"{OPEN_EPISODE_MAX_S / 3600:.0f} h or the next start: "
            + ", ".join(
                datetime.fromtimestamp(start, ZoneInfo(roles.timezone)).strftime("%Y-%m-%d %H:%M")
                for start in capped_starts
            )
        )
    return data


def _running_share(hz: Rollup) -> FloatArray:
    """Return per bucket the share (0 to 1) of time the compressor ran."""
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(hz.maximum > 0, hz.mean / hz.maximum, 0.0)
    share = np.where(hz.minimum > 0, 1.0, share)
    share = np.where(hz.coverage >= MIN_COVERAGE, share, 0.0)
    return np.clip(np.nan_to_num(share), 0.0, 1.0)


def _assemble(
    grid: TimeGrid,
    rollups: Mapping[str, Rollup],
    defrost: Rollup,
    valve: Rollup,
    heat_stored: Rollup,
    room: Rollup,
    refs: list[Rollup],
    weather: Mapping[str, Series],
    journal: tuple[ev.Event, ...],
    roles: HistoryRoles,
    notes: dict[str, Any],
    excluded: tuple[ev.Event, ...] = (),
) -> HistoryData:
    """Assemble the history rollups, weather and journal into a ``HistoryData`` on ``grid``.

    Parameters
    ----------
    grid
        Time grid of the result.
    rollups
        Rollups of the loop signals (inlet, outlet, flow, compressor frequency, ...) by name.
    defrost
        Rollup of the defrost state.
    valve
        Rollup of the three-way (hot water) valve state.
    heat_stored
        Rollup of the heat the pump itself reports (W); unused when it has no coverage.
    room
        Rollup of the living-room temperature (degC).
    refs
        Rollups of the reference room sensors (degC).
    weather
        Weather series by name.
    journal
        Journalled events (e.g. stove mode) added to the detected ones.
    roles
        Which signals play which role, and the time zone.
    notes
        Provenance notes, updated in place with how heat, outside and events were derived.
    excluded
        Events that are kept in the data but excluded from fitting.

    Returns
    -------
    HistoryData
        The assembled dataset.
    """
    columns: dict[str, FloatArray] = {}
    flags: dict[str, BoolArray] = {}
    loop_cov = np.vstack([rollups[name].coverage for name in LOOP])
    flags["gap"] = loop_cov.max(axis=0) < GAP_COVERAGE
    flags["stale"] = loop_cov.min(axis=0) < MIN_COVERAGE
    inlet, outlet = rollups["inlet"].valid(), rollups["outlet"].valid()
    flow, hz = rollups["flow"].valid(), rollups["hz"].valid()
    share = _running_share(rollups["hz"])
    defrost_any = np.nan_to_num(defrost.maximum) >= 1
    dhw_any = np.nan_to_num(valve.maximum) >= 1
    running_any = np.nan_to_num(rollups["hz"].maximum) > 0
    calibration = calibrate_offset(
        inlet, outlet, flow, np.where(running_any, 1.0, 0.0), defrost_any, grid.step
    )
    if heat_stored.coverage.max(initial=0.0) > 0:
        correction = np.nan_to_num(flow) * W_PER_LPM_K * calibration.offset_k * share
        heat = heat_stored.valid() - correction
        notes["heat"] = (
            f"stored {HEAT_SIGNAL} minus the calibrated offset "
            f"({calibration.offset_k:.3f} K) over the running share"
        )
    else:
        heat = heat_from_loop(flow, inlet, outlet, hz, dhw_any, calibration.offset_k)
        notes["heat"] = "approximated from bucket means (flow x spread); no stored loop heat"
    columns["inlet"] = inlet
    columns["outlet"] = outlet
    columns["flow"] = flow
    columns["hz"] = hz
    columns["heat_w"] = np.where(dhw_any & ~np.isfinite(heat), np.nan, heat)
    columns["spread_raw"] = outlet - inlet
    columns["compressor_frac"] = share
    columns["defrost_frac"] = np.clip(np.nan_to_num(defrost.mean), 0.0, 1.0)
    flags["defrost"] = defrost_any
    flags["dhw"] = dhw_any
    flags["compressor_on"] = share >= 0.5
    for name, rollup in rollups.items():
        if name not in columns:
            columns[name] = rollup.valid()
    room_value = room.valid()
    columns[ROOM_COLUMN] = room_value
    columns["room_mirror"] = room_value.copy()
    flags["room_stale"] = ~np.isfinite(room_value)
    for i, ref in enumerate(refs):
        columns[f"{REFERENCE_PREFIX}{i + 1}"] = ref.valid()
    dataset = finish(
        grid,
        columns,
        flags,
        calibration,
        weather=weather,
        tz=roles.timezone,
        rooms=roles.room_roles(),
        extra_events=journal,
        notes={"source": "service history", "heat": str(notes["heat"])},
        kept_events=excluded,
    )
    if not weather:
        dataset.columns["outside"] = fill_outside(
            dataset.columns["outside"], dataset.columns["outside_hp"], grid.step
        )
        notes["outside"] = (
            "no weather: idle pump sensor (1 h mean) interpolated over runs up to "
            f"{OUTSIDE_FILL_S / 3600:.0f} h, the raw sensor beyond"
        )
    notes["events"] = [event.to_json(roles.timezone) for event in dataset.events]
    notes["stove_detection"] = (
        "detector and journal" if roles.references else "journal only (no reference room)"
    )
    return HistoryData(dataset, round(grid.step), notes)


def fill_outside(outside: FloatArray, sensor: FloatArray, step: float) -> FloatArray:
    """Fill the idle-only outside estimate over compressor runs.

    Without weather data the fused outside temperature exists only while the
    compressor is idle (its cold exhaust biases the sensor while it runs). Gaps are
    interpolated linearly when both neighbours are within :data:`OUTSIDE_FILL_S`;
    longer gaps take the raw sensor.
    """
    ok = np.isfinite(outside)
    if not ok.any():
        return sensor.copy()
    idx = np.arange(outside.size)
    known = np.flatnonzero(ok)
    filled = np.interp(idx, known, outside[known])
    after = np.searchsorted(known, idx)
    prev_i = known[np.clip(after - 1, 0, known.size - 1)]
    next_i = known[np.clip(after, 0, known.size - 1)]
    span_s = (next_i - prev_i).astype(np.float64) * step
    short = (after > 0) & (after < known.size) & (span_s <= OUTSIDE_FILL_S)
    out = np.where(ok, outside, np.where(short, filled, sensor))
    return np.asarray(out, dtype=np.float64)
