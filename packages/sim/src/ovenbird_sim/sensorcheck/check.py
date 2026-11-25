"""Propose a room sensor profile from a sensor's recorded Home Assistant states.

The Datalake stores one row per state *change* (``last_updated``), so the check
sees value changes and ``unavailable`` periods, not reports of an unchanged value:
a heartbeat that re-sends the same value is invisible here (HA's ``last_reported``
shows it live). The proposal therefore rests on the value steps and the gaps
between changes:

* **Steps**: a sensor that reports on change sends one fixed step (every change
  exactly ±0.2 K, say); a periodic sensor's changes are spread over many sizes.
* **Gaps**: a periodic sensor (or one with a heartbeat) changes at a fairly regular
  pace; a send-on-delta sensor in a slow room is silent for hours.

``periodic`` is proposed when the gaps are short and regular (median at most 1 h,
90th percentile at most 1.5 x the median), with the 90th percentile as the report
interval. Otherwise ``on_change`` with the dominant step, and the shortest silence
limit from :data:`SILENCE_CHOICES_S` that covers every recorded gap (including the
liveness signal's reports when one is given) with a 10 % margin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from ovenbird_sim.data.series import FloatArray, Series
from ovenbird_sim.evaluate.sensors import changes_per_day, reversal_share, room_grid

HOUR_S: Final = 3600.0
SILENCE_CHOICES_S: Final = (
    12 * HOUR_S,
    24 * HOUR_S,
    48 * HOUR_S,
    72 * HOUR_S,
    7 * 24 * HOUR_S,
)
SILENCE_MARGIN: Final = 1.1
REGULAR_MEDIAN_S: Final = HOUR_S
REGULAR_SPREAD: Final = 1.5
DOMINANT_SHARE: Final = 0.9
MIN_INTERVAL_S: Final = 60.0
PERCENTILES: Final = (50.0, 90.0, 99.0, 100.0)


@dataclass(frozen=True, slots=True)
class Gaps:
    """Gaps between consecutive reports in seconds.

    Parameters
    ----------
    p50, p90, p99, max
        Percentiles of the gaps.
    count
        Number of gaps.
    """

    p50: float
    p90: float
    p99: float
    max: float
    count: int

    @classmethod
    def of(cls, times: FloatArray) -> Gaps:
        """Gaps of the sorted report times ``times``."""
        gaps = np.diff(np.unique(times))
        if not gaps.size:
            return cls(math.nan, math.nan, math.nan, math.nan, 0)
        p50, p90, p99, top = (float(np.percentile(gaps, q)) for q in PERCENTILES)
        return cls(p50, p90, p99, top, int(gaps.size))

    def covered(self, times: FloatArray, limit_s: float) -> float:
        """Share of the gaps of ``times`` no longer than ``limit_s``."""
        gaps = np.diff(np.unique(times))
        return float(np.mean(gaps <= limit_s)) if gaps.size else math.nan


@dataclass(frozen=True, slots=True)
class SensorStats:
    """What the recorded states of one sensor show.

    Parameters
    ----------
    entity
        Entity id.
    states
        Valid (numeric) states.
    days
        Span of the valid states in days.
    step_k
        Most frequent non-zero step.
    step_share
        Share of the non-zero changes that are exactly that step.
    grid_offset_k
        Offset of the value grid.
    changes_per_day
        Value changes per day.
    reversal_share
        Share of consecutive changes that reverse direction.
    gaps
        Gaps between the sensor's own state changes.
    combined
        Gaps between reports of the sensor or its liveness signal (``None``
        without one).
    unavailable
        Number of ``unavailable``/``unknown`` states.
    liveness
        Liveness entity id, if any.
    times
        Report times of the sensor.
    combined_times
        Report times of the sensor and the liveness signal.
    """

    entity: str
    states: int
    days: float
    step_k: float
    step_share: float
    grid_offset_k: float
    changes_per_day: float
    reversal_share: float
    gaps: Gaps
    combined: Gaps | None
    unavailable: int
    liveness: str | None = None
    times: FloatArray = field(default_factory=lambda: np.zeros(0))
    combined_times: FloatArray = field(default_factory=lambda: np.zeros(0))


@dataclass(frozen=True, slots=True)
class Proposal:
    """A proposed room sensor profile.

    Parameters
    ----------
    profile
        ``periodic`` or ``on_change``.
    step_k
        Sensor step.
    report_interval_s
        Report interval (``periodic``).
    silence_limit_s
        Silence limit (``on_change``).
    liveness
        Liveness signal ids.
    coverage
        Share of the recorded gaps the limit covers (with liveness, and the
        sensor alone).
    reasons
        Why, in plain sentences.
    """

    profile: str
    step_k: float
    report_interval_s: float | None
    silence_limit_s: float | None
    liveness: tuple[str, ...]
    coverage: dict[str, float]
    reasons: tuple[str, ...]

    def settings(self, room_signal: str) -> dict[str, str]:
        """``OVENBIRD_CONTROL_ROOM_*`` environment settings of the proposal."""
        out = {
            "OVENBIRD_CONTROL_ROOM_SIGNAL": room_signal,
            "OVENBIRD_CONTROL_ROOM_PROFILE": self.profile,
            "OVENBIRD_CONTROL_ROOM_STEP_K": f"{self.step_k:g}",
        }
        if self.report_interval_s is not None:
            out["OVENBIRD_CONTROL_ROOM_REPORT_INTERVAL_S"] = f"{self.report_interval_s:.0f}"
        if self.silence_limit_s is not None:
            out["OVENBIRD_CONTROL_ROOM_SILENCE_LIMIT_S"] = f"{self.silence_limit_s:.0f}"
        if self.liveness:
            out["OVENBIRD_CONTROL_ROOM_LIVENESS_SIGNALS"] = ",".join(self.liveness)
        return out


def _dominant_step(values: FloatArray) -> tuple[float, float]:
    steps = np.round(np.abs(np.diff(values)), 3)
    steps = steps[steps > 0]
    if not steps.size:
        return math.nan, math.nan
    sizes, counts = np.unique(steps, return_counts=True)
    best = int(np.argmax(counts))
    return float(sizes[best]), float(counts[best] / steps.size)


def analyse(
    states: Series,
    entity: str,
    liveness: Series | None = None,
    liveness_entity: str | None = None,
) -> SensorStats:
    """Summarise the recorded states of a sensor (and its liveness signal).

    Parameters
    ----------
    states
        Numeric states at ``last_updated`` (``NaN`` = unavailable).
    entity
        Entity id.
    liveness
        States of a sibling signal of the same device.
    liveness_entity
        Its entity id.

    Returns
    -------
    SensorStats
        Steps, grid, rates and gaps.
    """
    ok = np.isfinite(states.v)
    values, times = states.v[ok], states.t[ok]
    step, share = _dominant_step(values)
    _, offset = room_grid(values) if values.size else (math.nan, math.nan)
    days = float(times[-1] - times[0]) / 86400.0 if times.size > 1 else 0.0
    combined: Gaps | None = None
    both = times
    if liveness is not None and len(liveness):
        alive = liveness.t[np.isfinite(liveness.v)]
        both = np.sort(np.concatenate([times, alive]))
        combined = Gaps.of(both)
    return SensorStats(
        entity=entity,
        states=int(values.size),
        days=days,
        step_k=step,
        step_share=share,
        grid_offset_k=offset,
        changes_per_day=changes_per_day(states),
        reversal_share=reversal_share(states),
        gaps=Gaps.of(times),
        combined=combined,
        unavailable=int((~ok).sum()),
        liveness=liveness_entity if combined is not None else None,
        times=times,
        combined_times=both,
    )


def _hours(seconds: float) -> str:
    return f"{seconds / HOUR_S:.1f} h"


def propose(stats: SensorStats, signal_prefix: str = "ha/") -> Proposal:
    """Propose a profile for the sensor (see the module docstring).

    Parameters
    ----------
    stats
        Result of :func:`analyse`.
    signal_prefix
        Prefix of the signal ids of liveness entities.

    Returns
    -------
    Proposal
        Profile, step, interval or silence limit, and the reasons.
    """
    gaps = stats.gaps
    reasons: list[str] = []
    regular = (
        math.isfinite(gaps.p50)
        and gaps.p50 <= REGULAR_MEDIAN_S
        and gaps.p90 <= REGULAR_SPREAD * gaps.p50
    )
    step = stats.step_k if math.isfinite(stats.step_k) else 0.1
    if regular:
        interval = max(MIN_INTERVAL_S, math.ceil(gaps.p90 / MIN_INTERVAL_S) * MIN_INTERVAL_S)
        reasons.append(
            f"changes arrive regularly (gap p50 {gaps.p50 / 60:.0f} min, p90 "
            f"{gaps.p90 / 60:.0f} min): periodic with a {interval:.0f} s report interval"
        )
        return Proposal(
            "periodic",
            step,
            interval,
            None,
            (),
            {"sensor": gaps.covered(stats.times, 3.0 * interval)},
            tuple(reasons),
        )
    reasons.append(
        f"{100 * stats.step_share:.0f} % of {round(stats.changes_per_day * stats.days)} changes "
        f"are exactly ±{stats.step_k:g} K ({stats.changes_per_day:.1f} changes/day, "
        f"{100 * stats.reversal_share:.0f} % reversals)"
        if math.isfinite(stats.step_share)
        else "no value changes recorded"
    )
    if math.isfinite(stats.step_share) and stats.step_share < DOMINANT_SHARE:
        reasons.append(
            "the steps are not one fixed size: check whether the sensor reports on change"
        )
    reasons.append(
        f"gaps between changes are irregular (p50 {_hours(gaps.p50)}, p90 {_hours(gaps.p90)}, "
        f"max {_hours(gaps.max)}): on_change"
    )
    longest = gaps.max
    liveness: tuple[str, ...] = ()
    if stats.combined is not None and stats.liveness is not None:
        longest = stats.combined.max
        liveness = (f"{signal_prefix}{stats.liveness}",)
        reasons.append(
            f"with {stats.liveness} as liveness the gaps shrink (p50 "
            f"{_hours(stats.combined.p50)}, max {_hours(stats.combined.max)})"
        )
    wanted = SILENCE_MARGIN * longest if math.isfinite(longest) else SILENCE_CHOICES_S[1]
    limit = next((c for c in SILENCE_CHOICES_S if c >= wanted), SILENCE_CHOICES_S[-1])
    coverage = {"sensor": gaps.covered(stats.times, limit)}
    if stats.combined is not None:
        coverage["with_liveness"] = stats.combined.covered(stats.combined_times, limit)
    covered = ", ".join(f"{100 * v:.0f} % {k.replace('_', ' ')}" for k, v in coverage.items())
    reasons.append(f"silence limit {_hours(limit)} covers the recorded gaps ({covered})")
    return Proposal("on_change", step, None, limit, liveness, coverage, tuple(reasons))
