"""Simulated sensors: integer sensors that dither, and the living-room sensor device.

The pump reports the outside temperature and the remote's room thermostat as whole
degrees, and both readings flip between neighbouring integers far more often than the
smooth temperatures behind them cross a threshold (measurement noise); every flip a
controller sees can move a setpoint. :class:`SensorModel` adds seeded Gaussian noise
before the rounding, and a thermostat offset (per day or one value). Both runs of a
paired comparison see the same noise sequence (common random numbers).

The living-room sensor ovenbird controls on is one model shared by the closed loop
(:mod:`~ovenbird_sim.evaluate.closedloop`) and the simulated HeishaMon board
(:mod:`~ovenbird_sim.heishamon.board`): :class:`RoomSensorModel` describes the
device, :class:`RoomSensorDevice` runs it.

* **Send-on-delta on a grid**: once per sample interval (60 s) the device measures
  the air temperature plus seeded noise and reports when the measurement left the
  last reported grid cell by more than a hysteresis margin; the value sent is the
  grid point (for example 0.1 K steps on the round grid: 21.0, 21.1, ...). Noise
  and hysteresis are calibrated together (:func:`calibrate_room`) so the reports
  change as often per day and reverse direction as often as the recorded states.
* **Heartbeat**: an unchanged value is re-sent every ``confirm_s`` (``0``: every
  sample, the ideal sensor; ``inf``: never, as the recorded device).
* **Liveness**: a sibling signal of the same device proves it alive. In the
  closed loop these are recorded humidity report times (exogenous: they do
  not follow the simulated room); on the board a companion humidity with its own
  send-on-delta rule (:class:`HumidityModel`).
* **Dropouts**: the recorded ``unavailable`` periods are replayed at their times.
* **Profile**: what ovenbird is configured with (:class:`~ovenbird_core.control.
  RoomSensorProfile`): it sets the staleness rule (``periodic``: 1800 s;
  ``on_change``: held up to the silence limit while alive) through the same store
  the service uses.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace
from typing import Final

import numpy as np

from ovenbird_core.control.config import RoomSensorProfile
from ovenbird_core.control.types import RoomProfile
from ovenbird_sim import local
from ovenbird_sim.data.series import BoolArray, FloatArray, Series

OUTSIDE_SIGNAL: Final = "main/Outside_Temp"
CALIBRATION_SEED: Final = 12345
IDEAL_ROOM_STEP_K: Final = 0.2
SAMPLE_S: Final = 60.0
HYSTERESIS_GRID_K: Final = tuple(round(0.01 * k, 2) for k in range(21))
RATE_TOLERANCE: Final = 0.05
FIT_STEPS: Final = 20
EXAMPLE_STEP_K: Final = 0.1
EXAMPLE_GRID_OFFSET_K: Final = 0.0
EXAMPLE_NOISE_K: Final = 0.02
EXAMPLE_HYSTERESIS_K: Final = 0.08
EXAMPLE_CHANGES_PER_DAY: Final = 30.0
EXAMPLE_REVERSAL_SHARE: Final = 0.35
HUMIDITY_SIGNAL: Final = "ha/sensor.living_room_humidity"


@dataclass(frozen=True, slots=True)
class HumidityModel:
    """Companion humidity of the room sensor's device (a liveness signal).

    An Ornstein-Uhlenbeck process around ``mean_pct`` reported with its own
    send-on-delta rule: a report when it moved ``step_pct`` from the last report,
    the value rounded to the step. The defaults give about 6 reports per day, as a
    typical Zigbee humidity sensor.

    Parameters
    ----------
    mean_pct
        Mean relative humidity.
    sd_pct
        Stationary standard deviation.
    tau_s
        Correlation time.
    step_pct
        Send-on-delta step (and value grid).
    """

    mean_pct: float = 55.0
    sd_pct: float = 2.5
    tau_s: float = 44 * 3600.0
    step_pct: float = 1.0


@dataclass(frozen=True, slots=True)
class RoomSensorModel:
    """The living-room sensor device (see the module docstring).

    The default is the ideal sensor of earlier versions (0.2 K steps, re-sent every
    sample, never stale); :func:`calibrate_room` fits one to recorded states and
    :func:`example_room_sensor` the example install's device (:func:`install_room_sensor`
    the recorded install's, from the local settings).

    Parameters
    ----------
    step_k
        Value grid step.
    grid_offset_k
        Grid offset (values are ``grid_offset_k + n step_k``).
    noise_k
        Standard deviation of the measurement noise before quantisation.
    confirm_s
        Interval at which an unchanged value is re-sent (``0``: every sample;
        ``inf``: never, only changes are reported).
    hysteresis_k
        A report needs the measurement this far beyond the edge of the last
        reported grid cell.
    sample_s
        Measurement interval of the device.
    profile
        The room sensor profile ovenbird is configured with (staleness rule).
    dropouts
        ``(start, end)`` periods in which the entity is unavailable.
    liveness_times
        Recorded report times of a liveness signal (sorted unix seconds).
    humidity
        Modelled companion humidity (when no recorded liveness times are given).
    changes_per_day
        Recorded value changes per day (calibration target).
    reversal_share
        Recorded share of consecutive changes that reverse direction (calibration
        target).
    """

    step_k: float = IDEAL_ROOM_STEP_K
    grid_offset_k: float = 0.0
    noise_k: float = 0.0
    confirm_s: float = 0.0
    hysteresis_k: float = 0.0
    sample_s: float = SAMPLE_S
    profile: RoomSensorProfile = field(default_factory=lambda: RoomSensorProfile(step_k=0.2))
    dropouts: tuple[tuple[float, float], ...] = ()
    liveness_times: tuple[float, ...] = ()
    humidity: HumidityModel | None = None
    changes_per_day: float = math.nan
    reversal_share: float = math.nan

    @property
    def max_age_s(self) -> float:
        """Staleness limit of the configured profile while the link is up."""
        return self.profile.max_age_s

    def quantise(self, value: float) -> float:
        """Snap ``value`` to the sensor grid."""
        n = round((value - self.grid_offset_k) / self.step_k)
        return round(self.grid_offset_k + n * self.step_k, 6)

    def unavailable(self, t: float) -> bool:
        """Whether ``t`` falls in a dropout."""
        return any(a <= t < b for a, b in self.dropouts)

    def leaves_cell(self, measured: float, reported: float) -> bool:
        """Whether ``measured`` is far enough from ``reported`` to send a new value."""
        return abs(measured - reported) >= 0.5 * self.step_k + self.hysteresis_k


def example_profile(liveness: tuple[str, ...] = (HUMIDITY_SIGNAL,)) -> RoomSensorProfile:
    """Return the example room sensor profile: ``on_change``, 0.1 K, humidity liveness."""
    return RoomSensorProfile(kind=RoomProfile.ON_CHANGE, step_k=EXAMPLE_STEP_K, liveness=liveness)


def install_profile(liveness: tuple[str, ...] = (HUMIDITY_SIGNAL,)) -> RoomSensorProfile:
    """Return the recorded install's room sensor profile (local ``ROOM_SENSOR_STEP_K``)."""
    step = local.number("ROOM_SENSOR_STEP_K", EXAMPLE_STEP_K)
    return RoomSensorProfile(kind=RoomProfile.ON_CHANGE, step_k=step, liveness=liveness)


def example_room_sensor(
    profile: RoomSensorProfile | None = None, humidity: HumidityModel | None = None
) -> RoomSensorModel:
    """Return the example install's send-on-delta room sensor (a generic Zigbee sensor).

    A typical consumer temperature and humidity sensor: 0.1 K resolution on the round
    0.1 K grid, a report when the value moves by one step (hysteresis a little below a
    step, noise a fifth of a step), no heartbeat, and a modelled companion humidity
    (the board has no recorded liveness times). About 30 reports a day with a third of
    them reversing the previous one is what such a sensor gives in a room swinging a
    few tenths of a kelvin; both are descriptive only.
    """
    return RoomSensorModel(
        step_k=EXAMPLE_STEP_K,
        grid_offset_k=EXAMPLE_GRID_OFFSET_K,
        noise_k=EXAMPLE_NOISE_K,
        confirm_s=math.inf,
        hysteresis_k=EXAMPLE_HYSTERESIS_K,
        profile=profile or example_profile(),
        humidity=humidity or HumidityModel(),
        changes_per_day=EXAMPLE_CHANGES_PER_DAY,
        reversal_share=EXAMPLE_REVERSAL_SHARE,
    )


def install_room_sensor(
    profile: RoomSensorProfile | None = None, humidity: HumidityModel | None = None
) -> RoomSensorModel:
    """Return the recorded install's room sensor: the local ``ROOM_SENSOR_*`` constants.

    The constants come from :func:`calibrate_room` on the recording and are kept in the local
    settings (:mod:`ovenbird_sim.local`); missing ones are the example's.
    """
    return RoomSensorModel(
        step_k=local.number("ROOM_SENSOR_STEP_K", EXAMPLE_STEP_K),
        grid_offset_k=local.number("ROOM_SENSOR_GRID_OFFSET_K", EXAMPLE_GRID_OFFSET_K),
        noise_k=local.number("ROOM_SENSOR_NOISE_K", EXAMPLE_NOISE_K),
        confirm_s=math.inf,
        hysteresis_k=local.number("ROOM_SENSOR_HYSTERESIS_K", EXAMPLE_HYSTERESIS_K),
        profile=profile or install_profile(),
        humidity=humidity or HumidityModel(),
        changes_per_day=local.number("ROOM_SENSOR_CHANGES_PER_DAY", EXAMPLE_CHANGES_PER_DAY),
        reversal_share=local.number("ROOM_SENSOR_REVERSAL_SHARE", EXAMPLE_REVERSAL_SHARE),
    )


@dataclass(slots=True)
class RoomSensorDevice:
    """One simulated room sensor device: what it reports, and when.

    Parameters
    ----------
    model
        Device model.
    seed
        Seed of the humidity process.
    """

    model: RoomSensorModel
    seed: int = 0
    value: float | None = None
    reported_at: float | None = None
    sampled_at: float | None = None
    humidity_value: float | None = None
    _humidity_state: float = 0.0
    _humidity_at: float | None = None
    _rng: np.random.Generator | None = None
    _liveness_index: int = 0

    def temperature(
        self, t: float, t_air: float, draw: float, *, force: bool = False
    ) -> float | None:
        """Return the temperature the device sends at ``t``, or ``None``.

        Parameters
        ----------
        t
            Time in seconds.
        t_air
            True air temperature.
        draw
            Standard-normal draw of the measurement noise.
        force
            Send the current value regardless (the device re-joined after a dropout).

        Returns
        -------
        float or None
            The reported grid value, or ``None`` when the device stays silent.
        """
        m = self.model
        if not force and self.sampled_at is not None and t - self.sampled_at < m.sample_s - 1e-9:
            return None
        self.sampled_at = t
        measured = t_air + m.noise_k * draw
        if self.value is None or force or m.leaves_cell(measured, self.value):
            send = m.quantise(measured)
        elif self.reported_at is not None and t - self.reported_at >= m.confirm_s:
            send = self.value
        else:
            return None
        self.value, self.reported_at = send, t
        return send

    def liveness(self, t: float) -> float | None:
        """Return the latest recorded liveness report time up to ``t`` not yet returned."""
        times = self.model.liveness_times
        end = bisect.bisect_right(times, t, lo=self._liveness_index)
        if end == self._liveness_index:
            return None
        self._liveness_index = end
        return times[end - 1]

    def humidity(self, t: float) -> float | None:
        """Return the humidity the device sends at ``t`` (modelled), or ``None``.

        Parameters
        ----------
        t
            Unix time (s); must advance between calls.
        """
        model = self.model.humidity
        if model is None:
            return None
        if self._rng is None:
            self._rng = np.random.default_rng(self.seed)
        if self._humidity_at is None:
            self._humidity_state = model.sd_pct * float(self._rng.standard_normal())
            self._humidity_at = t
        else:
            dt = t - self._humidity_at
            if dt <= 0.0:
                return None
            decay = math.exp(-dt / model.tau_s)
            spread = model.sd_pct * math.sqrt(1.0 - decay * decay)
            self._humidity_state = self._humidity_state * decay + spread * float(
                self._rng.standard_normal()
            )
            self._humidity_at = t
        level = model.mean_pct + self._humidity_state
        last = self.humidity_value
        if last is not None and abs(level - last) < model.step_pct:
            return None
        self.humidity_value = round(level / model.step_pct) * model.step_pct
        return self.humidity_value


@dataclass(frozen=True, slots=True)
class SensorModel:
    """Noise and offsets of the simulated sensors in closed loop.

    Parameters
    ----------
    outside_noise_k
        Standard deviation of the noise before rounding ``Outside_Temp``.
    thermostat_noise_k
        Same for ``Room_Thermostat_Temp`` read once per tick (the HeishaMon snapshot).
    thermostat_offset_k
        Thermostat reading minus the living-room temperature (median over the period).
    seed
        Seed of the noise sequence.
    offset_t0
        Start of day 0 of :attr:`offset_by_day` (unix s).
    offset_by_day
        Thermostat offset per UTC day (empty: :attr:`thermostat_offset_k` throughout).
    room
        The living-room sensor model.
    """

    outside_noise_k: float = 0.0
    thermostat_noise_k: float = 0.0
    thermostat_offset_k: float = 0.0
    seed: int = 0
    offset_t0: float = 0.0
    offset_by_day: tuple[float, ...] = ()
    room: RoomSensorModel = field(default_factory=RoomSensorModel)

    def thermostat_offset(self, t: float | None = None) -> float:
        """Thermostat offset at ``t`` (the period median without a per-day table)."""
        if t is None or not self.offset_by_day:
            return self.thermostat_offset_k
        index = int((t - self.offset_t0) // 86400.0)
        return self.offset_by_day[min(max(index, 0), len(self.offset_by_day) - 1)]


def room_grid(values: FloatArray) -> tuple[float, float]:
    """Step and offset of the grid the recorded sensor values sit on."""
    v = values[np.isfinite(values)]
    steps = np.round(np.abs(np.diff(v)), 3)
    steps = steps[steps > 0]
    if not steps.size:
        return IDEAL_ROOM_STEP_K, 0.0
    uniq, counts = np.unique(steps, return_counts=True)
    step = float(uniq[np.argmax(counts)])
    phase = np.round(np.mod(v, step), 3) % step
    uniq_p, counts_p = np.unique(phase, return_counts=True)
    return step, float(uniq_p[np.argmax(counts_p)])


def dropouts(states: Series) -> tuple[tuple[float, float], ...]:
    """``unavailable`` periods of a state series (``NaN`` until the next valid state)."""
    out: list[tuple[float, float]] = []
    bad = ~np.isfinite(states.v)
    for k in np.flatnonzero(bad):
        later = np.flatnonzero(~bad[k + 1 :])
        end = float(states.t[k + 1 + later[0]]) if later.size else float(states.t[-1])
        if not out or float(states.t[k]) >= out[-1][1]:
            out.append((float(states.t[k]), end))
    return tuple(out)


def _outside(t: FloatArray, exclude: tuple[tuple[float, float], ...]) -> BoolArray:
    """Return a mask of the samples outside every ``(start, end)`` interval of ``exclude``."""
    keep = np.ones(t.shape, dtype=np.bool_)
    for a, b in exclude:
        keep &= (t < a) | (t >= b)
    return keep


def changes_per_day(states: Series, exclude: tuple[tuple[float, float], ...] = ()) -> float:
    """Value changes per day of a state series over its span (``exclude`` periods left out)."""
    ok = np.isfinite(states.v)
    if ok.sum() < 2:
        return math.nan
    v, t = states.v[ok], states.t[ok]
    left_out = sum(max(0.0, min(b, t[-1]) - max(a, t[0])) for a, b in exclude)
    days = (t[-1] - t[0] - left_out) / 86400.0
    changed = (np.diff(v) != 0) & _outside(t[1:], exclude)
    return float(np.sum(changed)) / days if days > 0 else math.nan


def reversal_share(states: Series, exclude: tuple[tuple[float, float], ...] = ()) -> float:
    """Share of consecutive value changes that reverse direction (``exclude`` left out)."""
    ok = np.isfinite(states.v)
    t = states.t[ok]
    steps = np.diff(states.v[ok])
    steps = steps[_outside(t[1:], exclude)]
    signs = np.sign(steps[steps != 0])
    if signs.size < 2:
        return math.nan
    return float(np.mean(signs[1:] != signs[:-1]))


def report_stats(
    reference: FloatArray, noise: FloatArray, sensor: RoomSensorModel
) -> tuple[int, int]:
    """Value changes and direction reversals the device reports on a reference series.

    Parameters
    ----------
    reference
        Air temperature per sample.
    noise
        Standard-normal draws per sample.
    sensor
        Device model (grid, noise level, hysteresis).

    Returns
    -------
    tuple of int
        Number of reported value changes and of reversals between them.
    """
    measured = reference + sensor.noise_k * noise
    half = 0.5 * sensor.step_k + sensor.hysteresis_k
    step, offset = sensor.step_k, sensor.grid_offset_k
    value = math.nan
    changes = reversals = 0
    previous = 0.0
    for m in measured.tolist():
        if value != value:
            value = offset + round((m - offset) / step) * step
            continue
        if abs(m - value) >= half:
            new = offset + round((m - offset) / step) * step
            direction = new - value
            if previous and (direction > 0.0) != (previous > 0.0):
                reversals += 1
            previous = direction
            value = new
            changes += 1
    return changes, reversals


def _fit_noise(
    reference: FloatArray, noise: FloatArray, sensor: RoomSensorModel, target: float, days: float
) -> float:
    """Return the sensor noise (K) at which the change rate per day matches ``target``.

    Parameters
    ----------
    reference
        Air temperature per sample (degC).
    noise
        Standard-normal draws per sample, scaled by the fitted noise.
    sensor
        Sensor model whose noise is fitted.
    target
        Wanted number of reported changes per day.
    days
        Length of the series in days.
    """

    def rate(sigma: float) -> float:
        """Return the reported changes per day with noise of ``sigma`` K."""
        changes, _ = report_stats(reference, noise, replace(sensor, noise_k=sigma))
        return changes / days

    if rate(0.0) >= target:
        return 0.0
    lo, hi = 0.0, 0.5
    for _ in range(FIT_STEPS):
        mid = 0.5 * (lo + hi)
        if rate(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fit_report_model(
    reference: FloatArray,
    sensor: RoomSensorModel,
    changes_target: float,
    reversal_target: float,
    days: float,
    seed: int = CALIBRATION_SEED + 2,
) -> RoomSensorModel:
    """Fit noise and hysteresis so the reports match the recorded rates.

    For every hysteresis on :data:`HYSTERESIS_GRID_K` the noise level matching the
    change rate is found by bisection; among the pairs that match the rate within
    :data:`RATE_TOLERANCE`, the one whose reversal share is closest to the recorded
    one wins (otherwise the one closest in rate).

    Parameters
    ----------
    reference
        Smooth air temperature per sample.
    sensor
        Device model with its grid.
    changes_target
        Recorded value changes per day.
    reversal_target
        Recorded share of reversing changes (``NaN``: no hysteresis).
    days
        Length of the reference in days.
    seed
        Seed of the noise draws.

    Returns
    -------
    RoomSensorModel
        ``sensor`` with the fitted ``noise_k`` and ``hysteresis_k``.
    """
    if not math.isfinite(changes_target) or days <= 0 or not reference.size:
        return sensor
    noise = np.random.default_rng(seed).standard_normal(reference.size)
    grid = HYSTERESIS_GRID_K if math.isfinite(reversal_target) else (0.0,)
    best: tuple[bool, float, RoomSensorModel] | None = None
    for h in grid:
        candidate = replace(sensor, hysteresis_k=h)
        sigma = _fit_noise(reference, noise, candidate, changes_target, days)
        candidate = replace(candidate, noise_k=sigma)
        changes, reversals = report_stats(reference, noise, candidate)
        rate_miss = abs(changes / days - changes_target) / changes_target
        share = reversals / (changes - 1) if changes > 1 else math.nan
        miss = abs(share - reversal_target) if math.isfinite(reversal_target) else rate_miss
        key = (rate_miss > RATE_TOLERANCE, rate_miss if rate_miss > RATE_TOLERANCE else miss)
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], candidate)
    return best[2] if best is not None else sensor


def liveness_times(states: Series | None, start: float | None = None) -> tuple[float, ...]:
    """Report times of a liveness signal (valid states only), from ``start`` on."""
    if states is None or not len(states):
        return ()
    ok = np.isfinite(states.v)
    times = states.t[ok]
    if start is not None:
        times = times[times >= start]
    return tuple(float(x) for x in np.sort(times))


def calibrate_room(
    states: Series | None,
    reference: FloatArray,
    times: FloatArray,
    confirm_s: float = math.inf,
    profile: RoomSensorProfile | None = None,
    liveness: Series | None = None,
    exclude: tuple[tuple[float, float], ...] = (),
) -> RoomSensorModel:
    """Calibrate the living-room sensor on its recorded states.

    Parameters
    ----------
    states
        Recorded Home Assistant states of the sensor (``NaN`` = unavailable).
    reference
        Smooth room temperature per tick (the filtered air state).
    times
        Tick times of ``reference``.
    confirm_s
        Assumed heartbeat of unchanged values (``inf``: as recorded, none).
    profile
        The profile ovenbird is configured with (default: ``periodic``).
    liveness
        Recorded states of a liveness signal (their times prove the device alive).
    exclude
        ``(start, end)`` periods left out of the change rate, the reversal share and
        the fit (known events; ``NaN`` reference ticks are left out too).

    Returns
    -------
    RoomSensorModel
        Grid, noise, hysteresis, dropouts and liveness of the recorded sensor.
    """
    chosen = profile or RoomSensorProfile()
    lively = liveness_times(liveness)
    if states is None or not len(states):
        return RoomSensorModel(confirm_s=confirm_s, profile=chosen, liveness_times=lively)
    step, offset = room_grid(states.v)
    target = changes_per_day(states, exclude)
    reversals = reversal_share(states, exclude)
    ok = np.isfinite(states.v)
    span = (times >= states.t[ok][0]) & (times <= states.t[ok][-1]) & np.isfinite(reference)
    days = float(span.sum()) * float(np.median(np.diff(times))) / 86400.0 if span.any() else 0.0
    base = RoomSensorModel(step_k=step, grid_offset_k=offset)
    fitted = fit_report_model(reference[span], base, target, reversals, days)
    return RoomSensorModel(
        step_k=step,
        grid_offset_k=offset,
        noise_k=fitted.noise_k,
        confirm_s=confirm_s,
        hysteresis_k=fitted.hysteresis_k,
        profile=chosen,
        dropouts=dropouts(states),
        liveness_times=lively,
        changes_per_day=target,
        reversal_share=reversals,
    )
