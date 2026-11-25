"""The scenario catalogue and the scheduler that places scenarios in a run.

The scenarios are spread over the span, one per slot after a warm-up day, or start at
given times (``--fault NAME --at TIME``). None depends on its slot: the sweep
(:mod:`ovenbird_harness.sweep`) runs each one alone at start times spread over the
recorded span and the hours of the day.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from ovenbird_harness.settings import ROOM_ENTITY

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.actions import (
    ConfigApply,
    OvenbirdRestart,
    PumpSettingWrite,
)
from ovenbird_harness.faults.commands import (
    CommandLost,
    EnvelopeCorrection,
    ForeignWriter,
    SetpointAboveMax,
)
from ovenbird_harness.faults.link import (
    BrokerDrop,
    HeishaMonRestart,
    TopicStale,
)
from ovenbird_harness.faults.pump import (
    DhwRun,
    ModeChange,
)
from ovenbird_harness.faults.room import (
    HaLinkDown,
    HaRereadFails,
    RoomSensorDiesWarm,
    RoomSensorFailsHigh,
    RoomSensorSilent,
)
from ovenbird_harness.faults.scenario import (
    HOUR,
    TAIL_S,
    TICK_S,
    WARMUP_S,
    Scenario,
    _iso,
)
from ovenbird_harness.faults.stove import StoveEvening

SCENARIOS: Final[dict[str, Callable[[], Scenario]]] = {
    "heishamon_restart": HeishaMonRestart,
    "broker_drop": BrokerDrop,
    "ha_link_down": HaLinkDown,
    "room_sensor_silent": RoomSensorSilent,
    "room_sensor_dies_warm": RoomSensorDiesWarm,
    "foreign_writer": ForeignWriter,
    "ovenbird_restart": OvenbirdRestart,
    "config_apply": ConfigApply,
    "pump_setting_write": PumpSettingWrite,
    "command_lost": CommandLost,
    "mode_change": ModeChange,
    "topic_stale": TopicStale,
    "dhw_run": DhwRun,
    "setpoint_above_max": SetpointAboveMax,
    "ha_reread_fails": HaRereadFails,
    "stove_evening": StoveEvening,
    "envelope_correction": EnvelopeCorrection,
    "room_sensor_fails_high": RoomSensorFailsHigh,
}
HA_SCENARIOS: Final = frozenset(
    {
        "ha_link_down",
        "room_sensor_silent",
        "room_sensor_dies_warm",
        "ha_reread_fails",
        "room_sensor_fails_high",
    }
)


@dataclass
class Scheduler:
    """Places the scenarios over the span and runs their actions.

    Parameters
    ----------
    scenarios
        Scenarios with their start times set.
    run
        The run the actions act on.
    """

    scenarios: list[Scenario]
    run: FullRun | None = None

    @classmethod
    def build(
        cls, run: FullRun, names: tuple[str, ...], at: Mapping[str, float] | None = None
    ) -> Scheduler:
        """Place ``names`` one per slot after a warm-up day, or at the given start times.

        Parameters
        ----------
        run
            The run.
        names
            Scenarios to inject.
        at
            Start times (unix seconds) of scenarios that do not take a slot.

        Raises
        ------
        ValueError
            For unknown names, HA scenarios without the HA room path, a start time
            whose window does not fit the span, or a span too short for the scenarios.
        """
        at = dict(at or {})
        unknown = [name for name in [*names, *at] if name not in SCENARIOS]
        if unknown:
            raise ValueError(f"unknown fault scenarios: {', '.join(unknown)}")
        stray = [name for name in at if name not in names]
        if stray:
            raise ValueError(f"start times for scenarios that do not run: {', '.join(stray)}")
        if run.ha is None and HA_SCENARIOS & set(names):
            raise ValueError("the room-sensor and HA scenarios need the HA room path")
        scenarios = [SCENARIOS[name]() for name in names]
        if not scenarios:
            return cls([], run)
        for scenario in scenarios:
            start = at.get(scenario.name)
            if start is None:
                continue
            if not run.start_ts <= start <= run.end_ts - scenario.window_s:
                raise ValueError(
                    f"{scenario.name} at {_iso(start)} does not fit the span "
                    f"({_iso(run.start_ts)} to {_iso(run.end_ts)}, window "
                    f"{scenario.window_s / HOUR:g} h)"
                )
            scenario.start = start
        placed = [s for s in scenarios if s.name not in at]
        if placed:
            cls._slots(run, placed)
        for scenario in scenarios:
            scenario.attach(run)
            if isinstance(scenario, RoomSensorSilent):
                run.on_cycle.append(_first_report_tracker(run, scenario))
        return cls(scenarios, run)

    @staticmethod
    def _slots(run: FullRun, scenarios: list[Scenario]) -> None:
        """Give each of ``scenarios`` a slot after the warm-up."""
        span = run.end_ts - run.start_ts
        warmup = min(WARMUP_S, 0.1 * span)
        slot = (span - warmup - TAIL_S) / len(scenarios)
        longest = max(s.window_s for s in scenarios)
        if slot < longest:
            raise ValueError(
                f"the span is too short for {len(scenarios)} fault scenarios "
                f"({slot / HOUR:.1f} h per slot, {longest / HOUR:.1f} h needed)"
            )
        for index, scenario in enumerate(scenarios):
            scenario.start = run.start_ts + warmup + index * slot

    def before(self, t: float) -> None:
        """Run every action due at ``t``."""
        if self.run is None:
            return
        for scenario in self.scenarios:
            scenario.before(self.run, t)

    def outcomes(self) -> list[dict[str, Any]]:
        """Return the outcome of every scenario."""
        if self.run is None:
            return []
        return [s.outcome(self.run) for s in self.scenarios]


def _first_report_tracker(run: FullRun, scenario: RoomSensorSilent) -> Callable[[float], None]:
    def track(t: float) -> None:
        if "first_report_after" in scenario.notes or run.ha is None:
            return
        resume = scenario.start + scenario.silent_s
        state = run.ha.states.get(ROOM_ENTITY)
        reported = state is not None and resume <= state.last_reported <= scenario.end - TICK_S
        if t >= resume and state is not None and reported:
            scenario.notes["first_report_after"] = state.last_reported

    return track
