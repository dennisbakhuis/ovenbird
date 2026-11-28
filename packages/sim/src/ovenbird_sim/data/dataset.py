"""Align the capture, the Home Assistant Datalake and weather onto one time grid.

:func:`build_dataset` produces a :class:`Dataset`: per-bin means of every signal the
model needs plus explicit quality flags. Heat delivered to the heating loop is formed
on the 5 s base grid as ``flow x rho x cp x (outlet - inlet - offset)`` with the same
gating as :func:`ovenbird_core.derived.heat_delivered_w` (zero while the compressor
is stopped, negative during defrost, missing during DHW). The offset is calibrated on
circulation-only periods (:func:`calibrate_offset`).

Flags (per bin, true when the condition holds anywhere in the bin unless noted):

``gap``
    HeishaMon liveness (``stats``) older than :data:`LIVENESS_MAX_AGE_S` - recorder
    or board outage.
``stale``
    one of inlet, outlet, flow, compressor frequency missing for most of the bin.
``defrost``, ``dhw``
    ``Defrosting_State`` = 1, ``ThreeWay_Valve_State`` = 1.
``compressor_on``
    compressor frequency > 0 for at least half the bin.
``room_stale``
    the room sensor's last update is older than :data:`ROOM_MAX_AGE_S`.
``event``
    inside a known event the model does not represent, with its recovery tail
    (:mod:`ovenbird_sim.data.events`: wood-stove fires); the events themselves are
    kept in :attr:`Dataset.events`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np

from ovenbird_core.derived import WATER_CP_J_PER_KG_K, WATER_DENSITY_KG_PER_L
from ovenbird_sim.data import capture as cap
from ovenbird_sim.data import datalake as dl
from ovenbird_sim.data import events as ev
from ovenbird_sim.data.grid import (
    BASE_STEP_S,
    TimeGrid,
    bin_any,
    bin_fraction,
    bin_last,
    bin_mean,
    hold,
    interpolate,
    time_since,
)
from ovenbird_sim.data.series import BoolArray, FloatArray, Series
from ovenbird_sim.data.weather import load_weather

LIVENESS_MAX_AGE_S: Final = 30.0
MAIN_MAX_AGE_S: Final = 330.0
ROOM_MAX_AGE_S: Final = 48 * 3600.0
OUTSIDE_BIAS_WINDOW_S: Final = 24 * 3600.0
LOCAL_TZ: Final = "Europe/Amsterdam"
POWER_MAX_AGE_S: Final = 900.0
CALIBRATION_MIN_FLOW: Final = 5.0
CALIBRATION_SETTLE_S: Final = 1200.0

MAIN_SIGNALS: Final[Mapping[str, str]] = {
    "outside_hp": "main/Outside_Temp",
    "inlet": "main/Main_Inlet_Temp",
    "outlet": "main/Main_Outlet_Temp",
    "flow": "main/Pump_Flow",
    "hz": "main/Compressor_Freq",
    "target": "main/Main_Target_Temp",
    "z1_target": "main/Z1_Water_Target_Temp",
    "heat_hp_est_w": "main/Heat_Power_Production",
    "elec_hp_est_w": "main/Heat_Power_Consumption",
    "pump_duty": "main/Pump_Duty",
    "max_pump_duty": "main/Max_Pump_Duty",
    "room_thermostat": "main/Room_Thermostat_Temp",
    "hex_outlet": "main/Main_Hex_Outlet_Temp",
    "operations_counter": "main/Operations_Counter",
    "discharge": "main/Discharge_Temp",
    "outside_pipe": "main/Outside_Pipe_Temp",
}
ROOM_ENTITIES: Final[Mapping[str, str]] = {
    "room_living_room": "sensor.living_room_temperature",
    "room_living_room_smoke": "sensor.living_room_smoke_detector_temperature",
    "room_living_room_motion": "sensor.living_room_motion_temperature",
    "room_kitchen": "sensor.kitchen_motion_temperature",
    "room_hall": "sensor.hall_temperature",
    "room_toilet": "sensor.toilet_motion_temperature",
    "room_bedroom": "sensor.bedroom_temperature",
    "room_landing": "sensor.landing_temperature",
    "room_conservatory": "sensor.conservatory_temperature",
    "room_garage": "sensor.garage_air_temperature",
    "room_garden_shed": "sensor.garden_shed_temperature",
}
LIVING_ROOM: Final = (
    "room_living_room",
    "room_living_room_smoke",
    "room_living_room_motion",
)
HOUSE: Final = (
    *LIVING_ROOM,
    "room_kitchen",
    "room_hall",
    "room_toilet",
    "room_bedroom",
    "room_landing",
)
POWER_ENTITIES: Final[Mapping[str, str]] = {
    "p1_w": "sensor.grid_power",
    "pv_inverter_w": "sensor.pv_inverter_power",
    "pv_meter_a_w": "sensor.pv_meter_phase_a_power",
    "pv_meter_b_w": "sensor.pv_meter_phase_b_power",
    "pv_meter_c_w": "sensor.pv_meter_phase_c_power",
}
WEATHER: Final[Mapping[str, str]] = {
    "outside_wx": "wx/temperature_2m",
    "ghi": "wx/shortwave_radiation",
    "direct": "wx/direct_radiation",
    "diffuse": "wx/diffuse_radiation",
    "dni": "wx/direct_normal_irradiance",
    "cloud": "wx/cloud_cover",
    "wind": "wx/wind_speed_10m",
    "rh_wx": "wx/relative_humidity_2m",
}
FLAGS: Final = ("gap", "stale", "defrost", "dhw", "compressor_on", "room_stale", "event")


@dataclass(frozen=True, slots=True)
class RoomRoles:
    """Which room columns form the living-room composite, the house mean and the references.

    Parameters
    ----------
    living
        Living-room columns; the first is replaced by the controller's room (``room``)
        and the composite stays on its level.
    house
        Columns averaged into ``house_mean`` (the first replaced like ``living``).
    references
        Rooms away from the wood stove, for the event detector.
    """

    living: tuple[str, ...]
    house: tuple[str, ...]
    references: tuple[str, ...]


EXAMPLE_ROOMS: Final = RoomRoles(LIVING_ROOM, HOUSE, ev.REFERENCE_ROOMS)


@dataclass(frozen=True, slots=True)
class OffsetCalibration:
    """Outlet-minus-inlet reading at zero heat (pump circulating, compressor off).

    Parameters
    ----------
    offset_k
        Mean spread over the calibration samples (subtracted from every spread). The
        sensors report 0.25 K steps and the spread dithers across them, so the mean
        resolves the offset below one step where the median cannot.
    median_k
        Median spread (for comparison).
    iqr_k
        Interquartile range of those samples.
    n_samples
        Number of 5 s base samples used.
    hours
        Their total duration in hours.
    """

    offset_k: float
    median_k: float
    iqr_k: float
    n_samples: int
    hours: float


@dataclass(frozen=True, slots=True)
class Dataset:
    """Signals and quality flags on a regular grid.

    Parameters
    ----------
    grid
        The time grid; values are bin means over ``[edge, edge + step)``.
    columns
        Numeric columns (``NaN`` = missing/stale).
    flags
        Boolean quality flags, see the module docstring.
    calibration
        The inlet/outlet offset used for ``heat_w``.
    notes
        Provenance notes.
    events
        Known events the model does not represent (the ``event`` flag).
    """

    grid: TimeGrid
    columns: dict[str, FloatArray]
    flags: dict[str, BoolArray]
    calibration: OffsetCalibration
    notes: dict[str, str] = field(default_factory=dict)
    events: tuple[ev.Event, ...] = ()

    def event_mask(self) -> BoolArray:
        """Bins inside a known event or its recovery tail (all false without the flag)."""
        flag = self.flags.get("event")
        return np.zeros(self.grid.n, dtype=np.bool_) if flag is None else flag

    @property
    def t(self) -> FloatArray:
        """Bin start times."""
        return self.grid.edges

    def col(self, name: str) -> FloatArray:
        """Return a column (``KeyError`` when absent)."""
        return self.columns[name]

    def has(self, name: str) -> bool:
        """Whether a column exists and has any finite value."""
        return name in self.columns and bool(np.isfinite(self.columns[name]).any())

    def flag(self, name: str) -> BoolArray:
        """Return a flag."""
        return self.flags[name]

    def slice(self, start: int, stop: int) -> Dataset:
        """Return bins ``start:stop``."""
        grid = TimeGrid(self.grid.start + start * self.grid.step, self.grid.step, stop - start)
        return Dataset(
            grid,
            {k: v[start:stop] for k, v in self.columns.items()},
            {k: v[start:stop] for k, v in self.flags.items()},
            self.calibration,
            self.notes,
            self.events,
        )

    def coarsen(self, factor: int) -> Dataset:
        """Average ``factor`` consecutive bins (flags: any; trailing bins dropped)."""
        n = (self.grid.n // factor) * factor
        grid = TimeGrid(self.grid.start, self.grid.step * factor, n // factor)
        columns = {k: bin_mean(v[:n], factor) for k, v in self.columns.items()}
        flags = {k: bin_any(v[:n], factor) for k, v in self.flags.items()}
        if "compressor_on" in self.flags and "compressor_frac" in self.columns:
            flags["compressor_on"] = np.nan_to_num(columns["compressor_frac"]) >= 0.5
        return Dataset(grid, columns, flags, self.calibration, self.notes, self.events)


def calibrate_offset(
    inlet: FloatArray,
    outlet: FloatArray,
    flow: FloatArray,
    hz: FloatArray,
    defrost: BoolArray,
    step: float = BASE_STEP_S,
) -> OffsetCalibration:
    """Calibrate the outlet-minus-inlet offset on circulation-only samples.

    Samples qualify when the pump circulates (flow >= 5 l/min), the compressor has
    been stopped for at least 20 min and no defrost happened in that time: the loop
    then carries no heat from the pump, so the remaining spread is sensor offset
    plus the small loss of the unit's internal piping.

    Parameters
    ----------
    inlet, outlet, flow, hz
        Base-grid samples.
    defrost
        Base-grid defrost flag.
    step
        Base-grid step in seconds.

    Returns
    -------
    OffsetCalibration
        Mean offset (0 when no sample qualifies).
    """
    running = np.nan_to_num(hz, nan=1.0) > 0
    quiet = time_since(running | defrost, step) >= CALIBRATION_SETTLE_S
    ok = quiet & (np.nan_to_num(flow) >= CALIBRATION_MIN_FLOW)
    ok &= np.isfinite(inlet) & np.isfinite(outlet)
    spread = (outlet - inlet)[ok]
    if spread.size == 0:
        return OffsetCalibration(0.0, float("nan"), float("nan"), 0, 0.0)
    q1, med, q3 = np.percentile(spread, [25, 50, 75])
    return OffsetCalibration(
        float(spread.mean()),
        float(med),
        float(q3 - q1),
        int(spread.size),
        spread.size * step / 3600,
    )


def heat_from_loop(
    flow: FloatArray,
    inlet: FloatArray,
    outlet: FloatArray,
    hz: FloatArray,
    dhw: BoolArray,
    offset_k: float,
) -> FloatArray:
    """Vectorised space-heating power in W with core's gating.

    Parameters
    ----------
    flow, inlet, outlet, hz
        Samples (l/min, degC, degC, Hz).
    dhw
        DHW flag.
    offset_k
        Calibrated spread offset.

    Returns
    -------
    FloatArray
        0 with the compressor stopped, ``NaN`` in DHW or with missing inputs, else
        ``flow x rho x cp x (outlet - inlet - offset)``.
    """
    power = flow / 60.0 * WATER_DENSITY_KG_PER_L * WATER_CP_J_PER_KG_K * (outlet - inlet - offset_k)
    stopped = np.isfinite(hz) & (hz <= 0)
    out = np.where(stopped, 0.0, power)
    out = np.where(dhw, np.nan, out)
    return np.where(np.isfinite(hz), out, np.nan)


def _house_mean(
    columns: Mapping[str, FloatArray], names: tuple[str, ...], *, anchored: bool = False
) -> FloatArray:
    """Mean over sensors that tolerates missing ones.

    Each sensor is shifted by its median difference to the first sensor and the shifted
    values are averaged; a missing sensor then does not move the mean. Unless
    ``anchored``, the mean of the shifts is added back, so with every sensor present
    the result is the plain mean; anchored, the result stays on the first sensor's
    level (a finer-resolution stand-in for it). A bin needs at least half the sensors.

    Parameters
    ----------
    columns
        Sensor series on the common grid, by name (degC).
    names
        The sensors to average, first one being the reference level.
    anchored
        Keep the first sensor's level instead of the plain mean.

    Returns
    -------
    FloatArray
        The averaged series; NaN where fewer than half the sensors have a value.
    """
    present = [n for n in names if n in columns and np.isfinite(columns[n]).any()]
    if not present:
        first = next(iter(columns.values()))
        return np.full(first.shape, np.nan)
    stack = np.vstack([columns[n] for n in present])
    ref = stack[0]
    shifts = np.zeros(stack.shape[0])
    for i in range(1, stack.shape[0]):
        both = np.isfinite(ref) & np.isfinite(stack[i])
        if both.any():
            shifts[i] = float(np.median(stack[i][both] - ref[both]))
            stack[i] = stack[i] - shifts[i]
    count = np.isfinite(stack).sum(axis=0)
    total = np.nansum(stack, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = total / count + (0.0 if anchored else shifts.mean())
    return np.where(count * 2 >= len(present), mean, np.nan)


def fuse_outside(
    sensor: FloatArray,
    weather: FloatArray | None,
    idle: BoolArray,
    step: float,
) -> FloatArray:
    """Outside temperature from the weather series, debiased by the pump's integer sensor.

    The outdoor unit reports whole degrees and reads low while the compressor runs
    (its own cold exhaust), so its idle readings are compared with the weather series
    and the rolling 24 h median of the difference is added to the weather series. The
    long window averages the quantisation out. Without weather data the sensor's
    idle readings are smoothed with a 1 h running mean instead.

    Parameters
    ----------
    sensor
        Bin means of ``Outside_Temp``.
    weather
        Interpolated weather temperature, or ``None``.
    idle
        Bins with the compressor stopped.
    step
        Grid step in seconds.

    Returns
    -------
    FloatArray
        Fused outside temperature.
    """
    if weather is None or not np.isfinite(weather).any():
        width = max(round(3600.0 / step), 1)
        values = np.where(idle, sensor, np.nan)
        return _running_nanmean(values, width)
    diff = np.where(idle & np.isfinite(sensor), sensor - weather, np.nan)
    width = max(round(OUTSIDE_BIAS_WINDOW_S / step), 1)
    hourly = max(round(3600.0 / step), 1)
    n = (diff.size // hourly) * hourly
    blocks = diff[:n].reshape(-1, hourly)
    with np.errstate(all="ignore"):
        hour_med = np.array([np.nanmedian(b) if np.isfinite(b).any() else np.nan for b in blocks])
    k = max(width // hourly, 1)
    bias_h = np.zeros(hour_med.size)
    for i in range(hour_med.size):
        window = hour_med[max(0, i - k // 2) : i + k // 2 + 1]
        if np.isfinite(window).any():
            bias_h[i] = float(np.nanmedian(window))
    bias = np.repeat(bias_h, hourly)
    bias = np.concatenate([bias, np.full(diff.size - n, bias_h[-1] if bias_h.size else 0.0)])
    return np.where(np.isfinite(weather), weather + bias, np.nan)


def _running_nanmean(values: FloatArray, width: int) -> FloatArray:
    """Return the centred running mean over ``width`` samples, ignoring NaN."""
    finite = np.isfinite(values)
    csum = np.concatenate([[0.0], np.cumsum(np.where(finite, values, 0.0))])
    ccount = np.concatenate([[0], np.cumsum(finite)])
    idx = np.arange(values.size)
    lo = np.clip(idx - width // 2, 0, values.size)
    hi = np.clip(idx + width // 2 + 1, 0, values.size)
    count = ccount[hi] - ccount[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (csum[hi] - csum[lo]) / count
    return np.where(count > 0, out, np.nan)


def local_hours(t: FloatArray, tz: str = LOCAL_TZ) -> FloatArray:
    """Local clock hour in ``[0, 24)`` of unix times."""
    zone = ZoneInfo(tz)
    out = np.empty(t.size)
    for i, ts in enumerate(t):
        local = datetime.fromtimestamp(float(ts), zone)
        out[i] = local.hour + local.minute / 60.0 + local.second / 3600.0
    return out


def _span(series: Mapping[str, Series]) -> tuple[float, float]:
    """Return the first and last capture timestamp (Unix s), preferring the liveness signal."""
    live = series.get(cap.LIVENESS)
    if live is not None and len(live):
        return float(live.t[0]), float(live.t[-1])
    starts = [float(s.t[0]) for s in series.values() if len(s)]
    ends = [float(s.t[-1]) for s in series.values() if len(s)]
    if not starts:
        raise ValueError("the capture holds no samples")
    return min(starts), max(ends)


def assemble(
    capture: Mapping[str, Series],
    *,
    datalake: Mapping[str, Series] | None = None,
    weather: Mapping[str, Series] | None = None,
    step: float = 60.0,
    start: float | None = None,
    end: float | None = None,
) -> Dataset:
    """Assemble a dataset from loaded series (pure; see :func:`build_dataset`).

    Parameters
    ----------
    capture
        Capture series keyed as :func:`ovenbird_sim.data.capture.decode` names them.
    datalake
        Datalake series keyed by dataset column name.
    weather
        Weather series keyed ``wx/<variable>``.
    step
        Output step in seconds (a multiple of 5 s).
    start, end
        Optional span in unix seconds (defaults to the capture's liveness span).

    Returns
    -------
    Dataset
        Aligned columns and flags.
    """
    t0, t1 = _span(capture)
    t0 = t0 if start is None else start
    t1 = t1 if end is None else end
    grid = TimeGrid.covering(t0, t1, step)
    base = grid.refine(BASE_STEP_S)
    factor = round(step / BASE_STEP_S)
    times = base.mids
    columns: dict[str, FloatArray] = {}
    flags: dict[str, BoolArray] = {}

    def main(name: str, max_age: float = MAIN_MAX_AGE_S) -> FloatArray:
        """Return main signal ``name`` on the grid, expiring values older than ``max_age`` s."""
        series = capture.get(MAIN_SIGNALS[name], Series.empty())
        return hold(series, times, max_age)[0]

    live = capture.get(cap.LIVENESS, Series.empty())
    _, live_age = hold(live, times)
    gap = live_age > LIVENESS_MAX_AGE_S
    flags["gap"] = bin_any(gap, factor)

    inlet, outlet, flow, hz = main("inlet"), main("outlet"), main("flow"), main("hz")
    defrost = hold(capture.get("main/Defrosting_State", Series.empty()), times, MAIN_MAX_AGE_S)[0]
    dhw_raw = hold(capture.get("main/ThreeWay_Valve_State", Series.empty()), times, MAIN_MAX_AGE_S)[
        0
    ]
    defrost_b = np.nan_to_num(defrost) >= 1
    dhw_b = np.nan_to_num(dhw_raw) >= 1
    for arr in (inlet, outlet, flow, hz):
        arr[gap] = np.nan
    calibration = calibrate_offset(inlet, outlet, flow, hz, defrost_b)
    heat = heat_from_loop(flow, inlet, outlet, hz, dhw_b, calibration.offset_k)
    running = np.nan_to_num(hz) > 0

    columns["inlet"] = bin_mean(inlet, factor)
    columns["outlet"] = bin_mean(outlet, factor)
    columns["flow"] = bin_mean(flow, factor)
    columns["hz"] = bin_mean(hz, factor)
    columns["heat_w"] = bin_mean(heat, factor)
    columns["spread_raw"] = bin_mean(outlet - inlet, factor)
    columns["compressor_frac"] = bin_fraction(running, factor)
    columns["defrost_frac"] = bin_fraction(defrost_b, factor)
    stale_any = ~(np.isfinite(inlet) & np.isfinite(outlet) & np.isfinite(flow) & np.isfinite(hz))
    flags["stale"] = bin_fraction(stale_any, factor) > 0.5
    flags["defrost"] = bin_any(defrost_b, factor)
    flags["dhw"] = bin_any(dhw_b, factor)
    flags["compressor_on"] = columns["compressor_frac"] >= 0.5
    del inlet, outlet, flow, hz, heat

    for name in MAIN_SIGNALS:
        if name in columns:
            continue
        values = main(name)
        values[gap] = np.nan
        columns[name] = bin_mean(values, factor)
    for name, signal in ((f"cmd_{k}", f"cmd/{k}") for k in ("SetCurves", "SetMaxPumpDuty")):
        columns[name] = bin_last(hold(capture.get(signal, Series.empty()), times)[0], factor)
    columns["sp_cmd"] = columns.pop("cmd_SetCurves")
    for key in sorted(k for k in capture if k.startswith("1wire/")):
        columns["onewire_" + key.split("/", 1)[1][-4:]] = bin_mean(
            hold(capture[key], times, MAIN_MAX_AGE_S)[0], factor
        )
    mirror = capture.get(cap.ROOM_MIRROR, Series.empty())
    columns["room_mirror"] = bin_mean(hold(mirror, times, ROOM_MAX_AGE_S)[0], factor)

    lake = datalake or {}
    for name in (*ROOM_ENTITIES, *POWER_ENTITIES):
        series = lake.get(name)
        if series is None or not len(series):
            continue
        max_age = ROOM_MAX_AGE_S if name.startswith("room_") else POWER_MAX_AGE_S
        values, _ = hold(series, grid.mids, max_age)
        columns[name] = values
    _, mirror_age = hold(mirror, grid.mids)
    if "room_living_room" in columns:
        _, room_age = hold(lake["room_living_room"], grid.mids)
        room_age = np.minimum(room_age, mirror_age)
        room = np.where(
            np.isfinite(columns["room_living_room"]),
            columns["room_living_room"],
            columns["room_mirror"],
        )
    else:
        room_age = mirror_age
        room = columns["room_mirror"].copy()
    columns["room"] = room
    flags["room_stale"] = (room_age > ROOM_MAX_AGE_S) | ~np.isfinite(room)
    meter = [columns[k] for k in ("pv_meter_a_w", "pv_meter_b_w", "pv_meter_c_w") if k in columns]
    if meter:
        columns["pv_meter_w"] = np.clip(-np.sum(meter, axis=0), 0.0, None)
    if "pv_inverter_w" in columns or meter:
        parts = [
            np.nan_to_num(columns.get(k, np.zeros(grid.n))) for k in ("pv_inverter_w", "pv_meter_w")
        ]
        columns["pv_w"] = np.sum(parts, axis=0)
    return finish(grid, columns, flags, calibration, weather=weather)


def finish(
    grid: TimeGrid,
    columns: dict[str, FloatArray],
    flags: dict[str, BoolArray],
    calibration: OffsetCalibration,
    *,
    weather: Mapping[str, Series] | None = None,
    tz: str = LOCAL_TZ,
    rooms: RoomRoles = EXAMPLE_ROOMS,
    extra_events: tuple[ev.Event, ...] = (),
    notes: Mapping[str, str] | None = None,
    kept_events: tuple[ev.Event, ...] = (),
) -> Dataset:
    """Add the room composites, weather, fused outside, local hour and known events.

    Parameters
    ----------
    grid
        The dataset's grid.
    columns
        Columns with at least ``room``, ``outside_hp`` and ``compressor_frac``; the
        rooms named in ``rooms`` are used when present.
    flags
        Flags; ``event`` is added.
    calibration
        Inlet/outlet offset calibration.
    weather
        Weather series keyed ``wx/<variable>``.
    tz
        Local time zone (``local_hour``, event descriptions).
    rooms
        Room roles (the example install's rooms by default).
    extra_events
        Known events from another source (the service's wood-stove journal), merged
        with the detected ones.
    notes
        Provenance notes to add.
    kept_events
        Known events kept as given, never merged with others (days the owner left
        out, :func:`ovenbird_sim.data.events.excluded_days`).

    Returns
    -------
    Dataset
        The completed dataset.
    """
    room = columns["room"]
    living = (
        _house_mean(columns | {rooms.living[0]: room}, rooms.living, anchored=True)
        if rooms.living
        else room.copy()
    )
    columns["room_living"] = living
    columns["house_mean"] = (
        _house_mean(columns | {rooms.house[0]: room}, rooms.house) if rooms.house else room.copy()
    )
    wx = weather or {}
    for name, key in WEATHER.items():
        if key in wx:
            columns[name] = interpolate(wx[key], grid.mids, max_gap=3 * 3600.0)
    idle = columns["compressor_frac"] < 0.5
    columns["outside"] = fuse_outside(
        columns["outside_hp"], columns.get("outside_wx"), idle, grid.step
    )
    columns["local_hour"] = local_hours(grid.edges, tz)
    known = ev.merge((*ev.detect(columns, grid.mids, rooms.references), *extra_events))
    if kept_events:
        known = tuple(sorted((*known, *kept_events), key=lambda e: e.start))
    flags["event"] = ev.mask(grid.mids, known)
    out_notes = {
        "built": datetime.now(UTC).isoformat(timespec="seconds"),
        "outside": "weather temperature debiased by the idle pump sensor (24 h median)",
        "outside_hp": "integer pump sensor; bin mean of the held value",
        **(notes or {}),
    }
    if known:
        out_notes["events"] = "; ".join(line.strip() for line in ev.describe(known, tz))
    return Dataset(grid, columns, flags, calibration, out_notes, known)


def load_datalake(root: Path) -> dict[str, Series]:
    """Load the Datalake series the dataset uses, keyed by dataset column name."""
    out: dict[str, Series] = {}
    for name, entity in (*ROOM_ENTITIES.items(), *POWER_ENTITIES.items()):
        series = dl.load_state(root, entity)
        if len(series):
            out[name] = series
    return out


def build_dataset(
    captures: Path,
    *,
    step: float = 60.0,
    capture_name: str = "live",
    start: float | None = None,
    end: float | None = None,
) -> Dataset:
    """Load and align everything under a captures root.

    Parameters
    ----------
    captures
        Root holding ``<capture_name>/``, ``datalake/`` and ``weather/``; the latter
        two are optional.
    step
        Output grid step in seconds.
    capture_name
        Capture sub-directory.
    start, end
        Optional span in unix seconds.

    Returns
    -------
    Dataset
        The aligned dataset.
    """
    capture = cap.load_capture(captures / capture_name)
    datalake = load_datalake(captures / "datalake")
    weather = load_weather(captures / "weather")
    return assemble(capture, datalake=datalake, weather=weather, step=step, start=start, end=end)
