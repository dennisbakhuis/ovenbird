"""Wood-stove mode in a full run.

``stove_evening`` enables wood-stove mode through the configuration store and adds
heat from a wood stove to the simulated house (the board's ``extra_heat_w``, released
into the air node) for an evening; the mode is disabled again at the end of its
window, so the scenarios after it run without it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from ovenbird.configstore import Actor
from ovenbird.control.alarms import AlarmCode
from ovenbird_core.control import StoveConfig

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.scenario import (
    BAND_K,
    CONTROL,
    CYCLE_S,
    EPSILON,
    HOUR,
    TICK_S,
    Check,
    Scenario,
    Seen,
    _iso,
    verdict,
)

STOVE_RAMP_TERMS: Final = ("start_ramp", "cycling_floor", "plan", "boost", "override")


@dataclass
class StoveEvening(Scenario):
    """A wood stove heats the living room for an evening (6 kW for 5 h) in wood-stove mode.

    The mode runs with its defaults (enter 1.5 K above comfort, back-off 3 K). The
    heat goes into the house's air node and the sensor's room warms faster than the
    house (the board's stove zone), while the pump's thermostat follows the house, as
    a recorded stove evening showed.
    """

    name: str = "stove_evening"
    window_s: float = 22 * HOUR
    heat_w: float = 6000.0
    heat_s: float = 5 * HOUR
    entry_within_s: float = 2 * TICK_S
    after_s: float = 6 * HOUR
    undershoot_k: float = BAND_K
    undershoot_max_s: float = HOUR
    version: int | None = None

    def plan(self, run: FullRun) -> None:
        """Enable wood-stove mode, light the stove, put it out, and disable the mode."""

        def light(r: FullRun, t: float) -> None:
            r.board.extra_heat_w = self.heat_w

        def out(r: FullRun, t: float) -> None:
            r.board.extra_heat_w = 0.0

        self.at(0.0, self._configure(True))
        self.at(0.0, light)
        self.at(self.heat_s, out)
        self.at(self.window_s - 2 * TICK_S, self._configure(False))

    def _configure(self, enabled: bool) -> Callable[[FullRun, float], None]:
        def apply(run: FullRun, t: float) -> None:
            manager = run.system.config
            changes: dict[str, Any] = {"control_stove_enabled": True if enabled else None}
            warnings = [w.code for w in manager.validate(changes).warnings]
            result = manager.apply(
                manager.version or 0,
                changes,
                Actor("harness"),
                comment=f"harness stove_evening {'on' if enabled else 'off'}",
                acknowledge=warnings,
            )
            if enabled:
                self.version = int(result["version"])
                self.notes["integral_before_k"] = run.system.loop.state.integral_k

        return apply

    def checks(self, run: FullRun) -> list[Check]:
        """Entry, back-off within the clamps, held integrator, no implausible, recovery."""
        stove = run.system.loop.controller.config.stove or StoveConfig()
        comfort = run.settings.control_comfort_c
        enter, leave = stove.enter_c(comfort), stove.exit_c(comfort)
        backoff = stove.backoff_k
        decisions = [d for d in self.decisions if d.ladder in CONTROL]
        crossed = next(
            (
                d
                for d in decisions
                if d.room is not None and (d.room[0] or -99.0) >= enter - EPSILON
            ),
            None,
        )
        active = [d for d in decisions if d.state.get("stove_state") == "active"]
        entry = active[0] if active else None
        exit_ = None
        if entry is not None:
            exit_ = next(
                (
                    d
                    for d in decisions
                    if d.ts > entry.ts and d.state.get("stove_state") != "active"
                ),
                None,
            )
        peak = max((d.room[0] or -99.0 for d in decisions if d.room is not None), default=None)
        self.notes.update(
            {
                "enter_c": enter,
                "room_peak_c": peak,
                "crossed": None if crossed is None else _iso(crossed.ts),
                "entered": None if entry is None else _iso(entry.ts),
                "trigger": None if entry is None else entry.state.get("stove_trigger"),
                "exited": None if exit_ is None else _iso(exit_.ts),
                "exit": None if exit_ is None else exit_.state.get("stove_exit"),
                "active_decisions": len(active),
            }
        )
        late = None if crossed is None or entry is None else entry.ts - crossed.ts
        unsafe = [
            d
            for d in active
            if d.setpoint is None
            or d.state.get("safety_low_c") is None
            or d.setpoint < float(d.state["safety_low_c"]) - 0.5 - EPSILON
        ]
        plain = [
            d for d in active if all(abs(d.terms.get(n, 0.0)) < EPSILON for n in STOVE_RAMP_TERMS)
        ]
        off_target = [d for d in plain if abs(self._target(d, backoff)) > 1e-6]
        wrong_term = [d for d in active if abs(d.terms.get("stove", 0.0) + backoff) > 1e-6]
        held = {round(float(d.state.get("integral_k", math.nan)), 9) for d in active}
        snapshot = None if entry is None else entry.state.get("stove_integral_k")
        before = self._integral_before(entry)
        implausible = self.raised(AlarmCode.ROOM_IMPLAUSIBLE.value, self.start)
        after = exit_.ts if exit_ is not None else self.end
        horizon = min(after + self.after_s, self.end)
        low = [
            t
            for t, room in self.rooms
            if after <= t <= horizon and room < comfort - self.undershoot_k
        ]
        below_s = len(low) * CYCLE_S
        floor = [room for t, room in self.rooms if after <= t <= horizon]
        resumed = [
            d
            for d in decisions
            if d.ts > after and d.state.get("stove_state") != "active" and d.reason != "stove"
        ]
        self.notes["below_band_s"] = below_s
        self.notes["room_min_after_c"] = round(min(floor), 2) if floor else None
        return [
            verdict(
                "the stove lifts the room above the entry threshold",
                crossed is not None,
                f"peak {peak} °C, threshold {enter:.1f} °C",
            ),
            verdict(
                f"wood-stove mode starts within {self.entry_within_s / 60:.0f} min of the "
                "threshold (or earlier on a fast rise)",
                late is not None and late <= self.entry_within_s + EPSILON,
                "never" if late is None else f"{late:+.0f} s ({self.notes['trigger']})",
            ),
            verdict(
                "the setpoint stays at or above the safety minimum",
                bool(active) and not unsafe,
                f"{len(active)} active decisions, {len(unsafe)} below"
                + (f" (first {unsafe[0].setpoint} at {_iso(unsafe[0].ts)})" if unsafe else ""),
            ),
            verdict(
                f"the target is the curve lowered by {backoff:g} K within the clamps",
                bool(plain) and not off_target and not wrong_term,
                f"{len(plain)} decisions without ramp or cycling, {len(off_target)} off, "
                f"{len(wrong_term)} with another stove term",
            ),
            verdict(
                "the integrator is held through the episode",
                len(held) == 1
                and snapshot is not None
                and before is not None
                and abs(float(snapshot) - before) < EPSILON
                and abs(next(iter(held)) - before) < 1e-6,
                f"before {before}, snapshot {snapshot}, during {sorted(held)[:4]}",
            ),
            verdict(
                "no room_implausible alarm",
                not implausible,
                f"{len(implausible)} raised",
            ),
            verdict(
                f"the episode lasts until the room is below the exit threshold "
                f"({leave:.1f} °C) or the {stove.max_active_s / HOUR:g} h cap, then normal room "
                "feedback resumes",
                exit_ is not None
                and entry is not None
                and bool(resumed)
                and (
                    (
                        exit_.state.get("stove_exit") == "cooled"
                        and exit_.room is not None
                        and (exit_.room[0] or 99.0) < leave
                    )
                    or (
                        exit_.state.get("stove_exit") == "max_active"
                        and exit_.ts - entry.ts >= stove.max_active_s - 2 * TICK_S
                    )
                ),
                f"exit {self.notes['exit']} at {self.notes['exited']} "
                f"(room {None if exit_ is None or exit_.room is None else exit_.room[0]} °C)",
            ),
            verdict(
                f"no undershoot in the {self.after_s / HOUR:.0f} h after the episode "
                f"(at most {self.undershoot_max_s / 60:.0f} min below comfort - "
                f"{self.undershoot_k:g} K)",
                bool(floor)
                and horizon - after >= self.after_s - EPSILON
                and below_s <= self.undershoot_max_s,
                f"{below_s / 60:.0f} min below over {(horizon - after) / HOUR:.1f} h, "
                f"minimum {self.notes['room_min_after_c']} °C",
            ),
        ]

    def _integral_before(self, entry: Seen | None) -> float | None:
        if entry is None:
            return None
        prior = [d for d in self.decisions if d.ts < entry.ts and d.ladder in CONTROL]
        if not prior:
            value = self.notes.get("integral_before_k")
            return None if value is None else float(value)
        return float(prior[-1].state.get("integral_k", math.nan))

    @staticmethod
    def _target(decision: Seen, backoff: float) -> float:
        low = float(decision.state["safety_low_c"])
        high = float(decision.state.get("safety_high_c", math.inf))
        curve = decision.terms.get("curve", math.nan)
        expected = min(max(curve - backoff, low), high)
        return decision.terms.get("safety", math.nan) - expected


def _stove_mode(enabled: bool, comment: str) -> Callable[[FullRun, float], None]:
    """Return an action that switches wood-stove mode on (defaults) or off."""

    def apply(run: FullRun, t: float) -> None:
        manager = run.system.config
        changes: dict[str, Any] = {"control_stove_enabled": True if enabled else None}
        warnings = [w.code for w in manager.validate(changes).warnings]
        manager.apply(
            manager.version or 0,
            changes,
            Actor("harness"),
            comment=f"harness {comment} {'on' if enabled else 'off'}",
            acknowledge=warnings,
        )

    return apply
