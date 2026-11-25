"""Key figures of a run: ladder, commands, plant cycling, comfort, alarms and holds."""

from __future__ import annotations

import itertools
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow

SHORT_RUN_S: Final = 20 * 60.0
RUN_BINS_MIN: Final = (0, 10, 20, 30, 45, 60, 90, 120, 180, 240, 360)
BAND_BELOW_K: Final = 0.5
FLOOR_BELOW_K: Final = 1.5
HOLD_CODE: Final = "command_hold"


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).date().isoformat()


def _share(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values())
    return {key: value / total for key, value in sorted(counter.items())} if total else {}


@dataclass
class PlantSample:
    """What the plant does over one cycle.

    Parameters
    ----------
    ts
        End of the cycle (unix s).
    dt
        Cycle length.
    running
        Compressor on (defrost included).
    room_c
        True room air temperature.
    """

    ts: float
    dt: float
    running: bool
    room_c: float


@dataclass
class Kpis:
    """Accumulates the figures of a run from its journal rows and plant samples.

    Parameters
    ----------
    comfort_c
        Comfort room temperature.
    room_max_age_s
        A fresh room value unchanged for longer than this counts as held (it would be
        stale under the 1800 s rule of a ``periodic`` sensor).
    daily_budget
        Commands per UTC day.
    """

    comfort_c: float
    room_max_age_s: float = 1800.0
    daily_budget: int = 150
    ladder: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)
    refusals: Counter[str] = field(default_factory=Counter)
    setpoints: Counter[int] = field(default_factory=Counter)
    room_fresh: int = 0
    room_held: int = 0
    room_reduced: int = 0
    decisions: int = 0
    commands: Counter[str] = field(default_factory=Counter)
    sent_per_day: Counter[str] = field(default_factory=Counter)
    sent_kinds: Counter[str] = field(default_factory=Counter)
    refused_commands: Counter[str] = field(default_factory=Counter)
    alarms_raised: Counter[str] = field(default_factory=Counter)
    holds: Counter[str] = field(default_factory=Counter)
    alarm_log: list[dict[str, Any]] = field(default_factory=list)
    runs_s: list[float] = field(default_factory=list)
    _run_start: float | None = None
    _running: bool | None = None
    room_sum: float = 0.0
    room_time: float = 0.0
    room_min: float = math.inf
    room_max: float = -math.inf
    below_band_s: float = 0.0
    below_floor_s: float = 0.0
    first_ts: float | None = None
    last_ts: float | None = None
    starts: int = 0

    def decision(self, row: DecisionRow) -> None:
        """Count one decision."""
        self.decisions += 1
        self.ladder[row.ladder] += 1
        self.reasons[row.reason] += 1
        if row.ladder == "refuse":
            self.refusals[row.reason] += 1
        if row.ladder not in ("refuse", "hold") and row.setpoint is not None:
            self.setpoints[row.setpoint] += 1
        record = json.loads(row.record)
        room = next(
            (ref for ref in record.get("inputs_used", []) if ref.get("source") == "room"),
            None,
        )
        if room is not None and room.get("fresh"):
            self.room_fresh += 1
            state = record.get("controller_state", {})
            held = state.get("room_held_s", room.get("age"))
            if held is not None and held > self.room_max_age_s:
                self.room_held += 1
            authority = state.get("room_authority")
            if authority is not None and authority < 1.0:
                self.room_reduced += 1

    def command(self, row: CommandRow) -> None:
        """Count one command event."""
        self.commands[row.status] += 1
        if row.status == "sent":
            self.sent_per_day[_day(row.ts)] += 1
            self.sent_kinds[row.kind] += 1
        elif row.status == "refused":
            self.refused_commands[row.detail.split(":")[0]] += 1

    def alarm(self, row: AlarmRow) -> None:
        """Count one alarm or hold transition."""
        if row.code == HOLD_CODE and row.event == "started":
            self.holds[row.message.split("(", 1)[-1].split(")", 1)[0]] += 1
        if row.event == "raised":
            self.alarms_raised[row.code] += 1
        if len(self.alarm_log) < 500:
            self.alarm_log.append(
                {
                    "at": datetime.fromtimestamp(row.ts, UTC).isoformat(),
                    "code": row.code,
                    "event": row.event,
                    "severity": row.severity,
                    "message": row.message,
                }
            )

    def plant(self, sample: PlantSample) -> None:
        """Account one plant cycle."""
        if self.first_ts is None:
            self.first_ts = sample.ts - sample.dt
        self.last_ts = sample.ts
        if sample.running and self._running is False:
            self._run_start = sample.ts
            self.starts += 1
        elif not sample.running and self._running and self._run_start is not None:
            self.runs_s.append(sample.ts - self._run_start)
            self._run_start = None
        self._running = sample.running
        room = sample.room_c
        self.room_sum += room * sample.dt
        self.room_time += sample.dt
        self.room_min = min(self.room_min, room)
        self.room_max = max(self.room_max, room)
        if room < self.comfort_c - BAND_BELOW_K:
            self.below_band_s += sample.dt
        if room < self.comfort_c - FLOOR_BELOW_K:
            self.below_floor_s += sample.dt

    @property
    def days(self) -> float:
        """Simulated days accounted."""
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return (self.last_ts - self.first_ts) / 86400.0

    def run_histogram(self) -> dict[str, int]:
        """Completed compressor runs per length bin (minutes)."""
        bins: dict[str, int] = {}
        edges = [*RUN_BINS_MIN, math.inf]
        for low, high in itertools.pairwise(edges):
            label = f"{low}-{high:g}" if math.isfinite(high) else f"{low}+"
            bins[label] = sum(1 for run in self.runs_s if low * 60 <= run < high * 60)
        return bins

    def summary(self) -> dict[str, Any]:
        """Return the JSON summary."""
        days = self.days or math.nan
        runs = sorted(self.runs_s)
        per_day = list(self.sent_per_day.values())
        fresh = self.room_fresh
        return {
            "days": self.days,
            "decisions": self.decisions,
            "ladder_shares": _share(self.ladder),
            "reason_shares": _share(self.reasons),
            "refusals": dict(sorted(self.refusals.items())),
            "room_feedback_share": self.ladder["schedule_curve_feedback"] / self.decisions
            if self.decisions
            else math.nan,
            "room_fresh_share": fresh / self.decisions if self.decisions else math.nan,
            "held_value_share": self.room_held / self.decisions if self.decisions else math.nan,
            "reduced_authority_share": self.room_reduced / self.decisions
            if self.decisions
            else math.nan,
            "setpoint_histogram": {str(k): v for k, v in sorted(self.setpoints.items())},
            "commands": {
                "events": dict(sorted(self.commands.items())),
                "sent_per_day_mean": sum(per_day) / days if per_day else 0.0,
                "sent_per_day_max": max(per_day, default=0),
                "daily_budget": self.daily_budget,
                "budget_share_max": max(per_day, default=0) / self.daily_budget,
                "sent_by_kind_per_day": {k: v / days for k, v in sorted(self.sent_kinds.items())},
                "refused_by_reason": dict(sorted(self.refused_commands.items())),
            },
            "plant": {
                "starts": self.starts,
                "starts_per_day": self.starts / days,
                "runs_completed": len(runs),
                "run_median_min": runs[len(runs) // 2] / 60 if runs else math.nan,
                "share_runs_below_20_min": sum(1 for r in runs if r < SHORT_RUN_S) / len(runs)
                if runs
                else math.nan,
                "run_histogram_min": self.run_histogram(),
            },
            "room": {
                "mean_c": self.room_sum / self.room_time if self.room_time else math.nan,
                "min_c": self.room_min,
                "max_c": self.room_max,
                "band_c": self.comfort_c - BAND_BELOW_K,
                "hours_below_band": self.below_band_s / 3600.0,
                "floor_c": self.comfort_c - FLOOR_BELOW_K,
                "hours_below_floor": self.below_floor_s / 3600.0,
            },
            "alarms_raised": dict(sorted(self.alarms_raised.items())),
            "holds": dict(sorted(self.holds.items())),
        }
