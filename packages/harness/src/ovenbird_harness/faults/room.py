"""Faults of the room temperature: the HA link, a silent, dead or failing sensor.

``room_sensor_fails_high`` enables wood-stove mode the same way as ``stove_evening``
and makes the room sensor read 3.7 K above the room for 8 h (the step is reported at
once, as a failing sensor does): the controller must take the step for a sensor
fault, not for a stove, and the cross-check against the pump's thermostat must flag
the value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ovenbird.control.alarms import AlarmCode
from ovenbird_core import SourceKind
from ovenbird_core.control import RoomSensorProfile
from ovenbird_core.store import HA_LINK_WINDOW_S

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.scenario import (
    BAND_K,
    COMFORT_FLOOR_K,
    CONTROL,
    CYCLE_S,
    EPSILON,
    HOUR,
    SLACK_S,
    TICK_S,
    Check,
    Scenario,
    _iso,
    verdict,
)
from ovenbird_harness.faults.stove import _stove_mode

HA_LINK_ALARM: Final = "ha_link_down"
SILENT_ALARM: Final = "room_sensor_silent"
HOLD_START_S: Final = 6 * HOUR
STUCK_MAX_DROP_K: Final = 0.8
QUIET_ALARM: Final = AlarmCode.ROOM_SENSOR_QUIET.value


def _room_limit(run: FullRun) -> tuple[float, str]:
    """Return the room-value age limit in s and the room profile name the run uses."""
    settings = run.settings
    profile = settings.control_room_profile
    if profile == "on_change":
        return float(settings.control_room_silence_limit_s), profile
    return float(run.system.runtime.store.policy.ha_max_age_s), profile


def _band_check(scenario: Scenario, run: FullRun, end: float, what: str) -> Check:
    """Check that the room stays in the band, or within one sensor step of where it started.

    A room already at or below the band edge when the fault begins (the P part
    carrying it on a cold night) may drift by the sensor's step, which the
    controller cannot resolve; the band hours are reported.

    Parameters
    ----------
    scenario
        Scenario holding the room samples; the band statistics are written to its notes.
    run
        The full run, for the comfort target and the room quantum.
    end
        End of the examined window, unix seconds.
    what
        Phrase completing the verdict text (the period examined).

    Returns
    -------
    Check
        Pass if the room never fell below the band less one sensor step.
    """
    comfort = run.config.profile.comfort_c
    band = comfort - BAND_K
    step = run.system.loop.controller.config.room.quantum_k
    rooms = [room for t, room in scenario.rooms if t < end]
    start = rooms[0] if rooms else math.nan
    floor = min(band, start) - step
    below = [room for room in rooms if room < band]
    scenario.notes["room_start_c"] = start if rooms else None
    scenario.notes["room_min_c"] = min(rooms) if rooms else None
    scenario.notes["hours_below_band"] = len(below) * CYCLE_S / HOUR
    return verdict(
        f"the room stays inside the comfort band ({band:.1f} °C, or the room at the start) "
        f"less one sensor step ({step:g} K) {what}",
        bool(rooms) and min(rooms) >= floor - EPSILON,
        f"room {start:.2f} °C at the start, min {min(rooms):.2f} °C, "
        f"{len(below) * CYCLE_S / HOUR:.2f} h below the band"
        if rooms
        else "no samples",
    )


@dataclass
class HaLinkDown(Scenario):
    """The Home Assistant connection is down for 2 h; the device keeps reporting into HA."""

    name: str = "ha_link_down"
    window_s: float = 4 * HOUR
    down_s: float = 2 * HOUR

    def plan(self, run: FullRun) -> None:
        """Disconnect and reconnect the HA input."""

        def down(r: FullRun, t: float) -> None:
            """Disconnect the HA input."""
            assert r.ha is not None
            r.ha.disconnect()

        def up(r: FullRun, t: float) -> None:
            """Reconnect the HA input."""
            assert r.ha is not None
            r.ha.connect(t)

        self.at(0.0, down)
        self.at(self.down_s, up)

    def checks(self, run: FullRun) -> list[Check]:
        """No room value older than the HA limit while the link is down; the alarm when present."""
        back = self.start + self.down_s
        limit = float(run.system.runtime.store.policy.ha_max_age_s)
        during = self.between(self.start, back)
        too_old = [
            d for d in during if d.room and d.room[2] and (d.room[1] or 0.0) > limit + EPSILON
        ]
        stale_from = self.start + limit + TICK_S
        late = self.between(stale_from, back)
        fresh_late = [d for d in late if d.room and d.room[2]]
        not_curve = [d for d in late if d.ladder != "curve_only"]
        raised = self.raised(HA_LINK_ALARM, self.start)
        cleared = [a for a in self.alarms if a.code == HA_LINK_ALARM and a.event == "cleared"]
        self.notes["curve_only_decisions"] = len(late)
        return [
            verdict(
                f"no room value older than {limit:.0f} s is used while the HA link is down",
                not too_old,
                f"{len(too_old)} of {len(during)} decisions",
            ),
            verdict(
                "room input stale from link-down + limit + one tick, curve only",
                bool(late) and not fresh_late and not not_curve,
                f"{len(late)} decisions, {len(fresh_late)} fresh, {len(not_curve)} not curve_only",
            ),
            verdict(
                "the HA input is connected again after the outage",
                run.ha is not None and run.ha.connected and run.system.runtime.ha_connected,
            ),
            verdict(
                "ha_link_down raised during the outage and cleared after it",
                bool(raised) and raised[0].ts < back and any(c.ts >= back for c in cleared),
                f"raised {[_iso(a.ts) for a in raised]}, cleared {[_iso(a.ts) for a in cleared]}",
            ),
            _band_check(self, run, self.end, "while the link is down and after"),
        ]


def _last_life(run: FullRun) -> float:
    """Return the time of the latest state report in HA, or NaN if there is none."""
    if run.ha is None:
        return math.nan
    times = [state.last_reported for state in run.ha.states.values()]
    return max(times) if times else math.nan


def _ramp(value: float | None, full: float, zero: float) -> float:
    """Return a linear ramp from 1 at ``full`` down to 0 at ``zero``.

    Parameters
    ----------
    value
        Age or duration in s; ``None`` counts as fresh.
    full
        Value up to which the result is 1.
    zero
        Value from which the result is 0.
    """
    if value is None or value <= full:
        return 1.0
    if value >= zero:
        return 0.0
    return (zero - value) / (zero - full)


def expected_authority(
    held_s: float | None, alive_s: float | None, profile: RoomSensorProfile
) -> float:
    """Return the stuck-warm authority, written out independently of the controller.

    The smaller of a ramp on the proof-of-life age (full up to
    ``alive_decay_start_s``, zero from ``alive_decay_end_s``) and a ramp on the held
    time (full up to ``decay_start_s``, zero at the silence limit).
    """
    alive = _ramp(alive_s, profile.alive_decay_start_s, profile.alive_decay_end_s)
    held = _ramp(held_s, profile.decay_start_s, profile.silence_limit_s)
    return min(alive, held)


def _quiet_warning(scenario: Scenario, run: FullRun, life: float) -> Check:
    """Check that the early warning comes once the proof of life is ``alive_decay_end_s`` old."""
    limit = run.system.loop.room_profile.alive_decay_end_s
    due = life + limit
    raised = scenario.raised(QUIET_ALARM, scenario.start)
    if due < scenario.start:
        return verdict(
            f"{QUIET_ALARM} active when the window starts (no proof of life for "
            f"{(scenario.start - life) / HOUR:.1f} h)",
            bool(scenario.notes.get("quiet_active_at_start")),
        )
    on_time = bool(raised) and due - EPSILON <= raised[0].ts <= due + SLACK_S
    return verdict(
        f"{QUIET_ALARM} raised {limit / HOUR:.0f} h after the last proof of life (early warning)",
        on_time,
        f"raised {[_iso(a.ts) for a in raised]}, due {_iso(due)}",
    )


@dataclass
class RoomSensorSilent(Scenario):
    """The room device (temperature and humidity) sends nothing for 30 h."""

    name: str = "room_sensor_silent"
    window_s: float = 32 * HOUR
    silent_s: float = 30 * HOUR

    def plan(self, run: FullRun) -> None:
        """Mute the device."""
        assert run.feed is not None
        self.notes["last_proof_of_life"] = _iso(_last_life(run))
        self.notes["last_life_ts"] = _last_life(run)
        self.notes["quiet_active_at_start"] = run.system.loop.alarms.is_active(
            AlarmCode.ROOM_SENSOR_QUIET
        )
        run.feed.mute(self.start, self.start + self.silent_s)

    def checks(self, run: FullRun) -> list[Check]:
        """Value used only within the limit, curve only after it, the alarm when present.

        Parameters
        ----------
        run
            The finished full run.

        Returns
        -------
        list[Check]
            One verdict per checked behaviour.
        """
        limit, profile = _room_limit(run)
        self.notes["room_limit_s"] = limit
        self.notes["room_profile"] = profile
        life = float(self.notes["last_life_ts"])
        resume = self.start + self.silent_s
        during = self.between(self.start, resume)
        beyond = [
            d for d in during if d.room and d.room[2] and (d.room[1] or 0.0) > limit + EPSILON
        ]
        after_limit = self.between(life + limit + TICK_S, resume)
        not_curve = [d for d in after_limit if d.ladder != "curve_only"]
        raised = self.raised(SILENT_ALARM, self.start)
        due = life + limit + SLACK_S
        stale_from = life + limit
        comfort = run.config.profile.comfort_c
        band = comfort - BAND_K
        held = [room for t, room in self.rooms if t < min(stale_from, resume)]
        stale = [room for t, room in self.rooms if stale_from <= t < resume]
        self.notes["curve_only_decisions"] = len(after_limit)
        self.notes["held_phase_min_c"] = min(held) if held else None
        self.notes["held_phase_hours_below_band"] = (
            sum(1 for room in held if room < band) * CYCLE_S / HOUR
        )
        self.notes["stale_phase_min_c"] = min(stale) if stale else None
        self.notes["stale_phase_hours_below_band"] = (
            sum(1 for room in stale if room < band) * CYCLE_S / HOUR
        )
        stale_start = stale[0] if stale else math.nan
        alive_end = run.system.loop.room_profile.alive_decay_end_s
        gone = [
            d
            for d in during
            if d.room is not None and d.room[2] and (d.room[1] or 0.0) >= alive_end
        ]
        cooling = [d for d in gone if d.feedback is not None and d.feedback < -EPSILON]
        fallback = [(d, d.feedback) for d in after_limit if d.feedback is not None]
        config = run.system.loop.controller.config
        step = min(config.feedback.held_step_max_k, config.feedback.kp * config.room.quantum_k)
        output = config.feedback.output_limit_k
        not_held = [
            d
            for d, value in fallback
            if not -EPSILON
            <= value
            <= min(output, max(0.0, float(d.state.get("integral_k", 0.0))) + step) + EPSILON
        ]
        return [
            verdict(
                f"the silent sensor's value is not used beyond its limit ({limit:.0f} s)",
                not beyond,
                f"{len(beyond)} of {len(during)} decisions",
            ),
            verdict(
                "curve only from the last proof of life + limit + one tick",
                bool(after_limit) and not not_curve,
                f"{len(after_limit)} decisions, {len(not_curve)} not curve_only",
            ),
            verdict(
                f"while the value is held, the house stays above the comfort floor "
                f"({comfort - COMFORT_FLOOR_K:.1f} °C)",
                bool(held) and min(held) >= comfort - COMFORT_FLOOR_K,
                f"held-phase min {min(held):.2f} °C" if held else "no samples",
            ),
            verdict(
                "once stale, the house stays above the comfort floor",
                bool(stale) and min(stale) >= comfort - COMFORT_FLOOR_K,
                f"stale-phase min {min(stale):.2f} °C" if stale else "no samples",
            ),
            _quiet_warning(self, run, life),
            verdict(
                f"no cooling on the held value once it has had no proof of life for "
                f"{alive_end / HOUR:.0f} h",
                not cooling,
                f"{len(gone)} decisions, {len(cooling)} cooling",
            ),
            verdict(
                "once stale, the room feedback is the held offset (positive integrator plus "
                "one sensor step, fading)",
                bool(fallback) and not not_held,
                f"{len(fallback)} decisions, {len(not_held)} off; band {band:.1f} °C: stale from "
                f"{_iso(stale_from)}, room {stale_start:.2f} °C then, min "
                f"{min(stale):.2f} °C, {self.notes['stale_phase_hours_below_band']:.2f} h below "
                f"the band; held phase min {self.notes['held_phase_min_c']:.2f} °C, "
                f"{self.notes['held_phase_hours_below_band']:.2f} h below"
                if stale and held
                else "no samples",
            ),
            _feedback_back(self, run, resume),
            verdict(
                "room_sensor_silent raised by the silence limit",
                bool(raised) and raised[0].ts <= due,
                f"raised {[_iso(a.ts) for a in raised]}, due by {_iso(due)}",
            ),
        ]


def _feedback_back(scenario: Scenario, run: FullRun, resume: float) -> Check:
    """Check that the next room report makes the room usable again within one tick."""
    first_report = scenario.notes.get("first_report_after")
    if first_report is None:
        return Check(
            "room feedback resumes after the next report",
            "pass",
            "the room did not move a full step before the window ended (no report)",
        )
    after = scenario.between(first_report, first_report + 2 * TICK_S + EPSILON)
    fresh = [d for d in after if d.room and d.room[2]]
    return verdict(
        "the next report makes the room usable within one tick",
        bool(fresh),
        f"report at {_iso(first_report)}, {len(after)} decisions after it",
    )


@dataclass
class RoomSensorDiesWarm(Scenario):
    """The room sensor reports a warm value (comfort + 1.5 K) once and dies for 30 h."""

    name: str = "room_sensor_dies_warm"
    window_s: float = 32 * HOUR
    silent_s: float = 30 * HOUR
    warm_k: float = 1.5

    def plan(self, run: FullRun) -> None:
        """Stick the sensor at a warm reading."""
        assert run.feed is not None
        value = round(run.config.profile.comfort_c + self.warm_k, 1)
        self.notes["stuck_value_c"] = value
        self.notes["quiet_active_at_start"] = False
        run.feed.stick(value, self.start, self.start + self.silent_s)

    def checks(self, run: FullRun) -> list[Check]:
        """Stuck value used only within the limit, no cool-down, decay when present.

        Parameters
        ----------
        run
            The finished full run.

        Returns
        -------
        list[Check]
            One verdict per checked behaviour.
        """
        limit, profile = _room_limit(run)
        self.notes["room_limit_s"] = limit
        self.notes["room_profile"] = profile
        stuck = float(self.notes["stuck_value_c"])
        resume = self.start + self.silent_s
        during = self.between(self.start, resume)
        using = [
            d
            for d in during
            if d.room and d.room[2] and d.room[0] is not None and abs(d.room[0] - stuck) < 1e-6
        ]
        late_use = [d for d in using if d.ts - self.start > limit + TICK_S]
        rooms = [room for t, room in self.rooms if t < resume]
        start_room = rooms[0] if rooms else math.nan
        comfort = run.config.profile.comfort_c
        lowest = min(start_room, comfort) - STUCK_MAX_DROP_K
        floor = comfort - COMFORT_FLOOR_K
        band = comfort - BAND_K
        below = [t for t, room in self.rooms if t < resume and room < band]
        hours_below = len(below) * CYCLE_S / HOUR
        coldest = min(((room, t) for t, room in self.rooms if t < resume), default=None)
        if coldest is not None:
            self.notes["room_min_c"] = coldest[0]
            self.notes["room_min_at"] = _iso(coldest[1])
            self.notes["hours_below_band"] = hours_below
        stale_from = self.start + limit
        residual = sum(1 for t in below if t >= stale_from) * CYCLE_S / HOUR
        self.notes["hours_below_band_while_held"] = hours_below - residual
        self.notes["hours_below_band_once_stale"] = residual
        room_profile = run.system.loop.controller.config.room
        gone = [
            d
            for d in using
            if d.room is not None
            and d.room[1] is not None
            and d.room[1] >= room_profile.alive_decay_end_s
        ]
        cooling = [d for d in gone if d.feedback is not None and d.feedback < -EPSILON]
        checks = [
            verdict(
                f"the stuck value is used at most for its limit ({limit:.0f} s)",
                not late_use,
                f"used on {len(using)} ticks, {len(late_use)} beyond the limit",
            ),
            verdict(
                f"the stuck warm reading costs the room at most {STUCK_MAX_DROP_K:g} K "
                f"(from the room at the start or comfort, whichever is lower: {lowest:.2f} °C) "
                f"and never the comfort floor ({floor:.1f} °C)",
                bool(rooms) and min(rooms) >= max(lowest, floor) - EPSILON,
                f"room {start_room:.2f} °C at the start, min {min(rooms):.2f} °C at "
                f"{self.notes.get('room_min_at')}, {hours_below:.1f} h below the {band:.1f} °C "
                f"band ({residual:.1f} h once stale)"
                if rooms
                else "no samples",
            ),
            verdict(
                f"no cooling once the device has been silent for "
                f"{room_profile.alive_decay_end_s / HOUR:.0f} h (curve plus the held offset)",
                bool(gone) and not cooling,
                f"{len(gone)} decisions, {len(cooling)} cooling"
                + (f" (first {cooling[0].feedback:+.2f} K)" if cooling else ""),
            ),
            _quiet_warning(self, run, self.start),
        ]
        held = [d for d in using if (d.held_s or 0.0) > HOLD_START_S]
        self.notes["held_decisions"] = len(held)
        if profile != "on_change":
            checks.append(Check("cooling authority (on_change only)", "pass", f"profile {profile}"))
            return checks
        output = run.system.loop.controller.config.feedback.output_limit_k
        bad = [
            d
            for d in held
            if d.feedback is not None
            and d.feedback
            < -output * expected_authority(d.held_s, d.room[1] if d.room else None, room_profile)
            - EPSILON
        ]
        checks.append(
            verdict(
                "cooling authority follows the proof-of-life and held-time ramps",
                bool(held) and not bad,
                f"{len(held)} decisions held longer than {HOLD_START_S / HOUR:.0f} h, "
                f"{len(bad)} with too much cooling",
            )
        )
        return checks


@dataclass
class HaRereadFails(Scenario):
    """Home Assistant answers every ``get_states`` re-read with an error for 2 h."""

    name: str = "ha_reread_fails"
    window_s: float = 4 * HOUR
    failing_s: float = 2 * HOUR

    def plan(self, run: FullRun) -> None:
        """Fail the re-reads, then let them succeed again."""

        def fail(r: FullRun, t: float) -> None:
            """Make the HA re-reads fail."""
            assert r.ha is not None
            r.ha.reads_fail = True
            self.notes["failed_before"] = r.ha.failed_reads

        def heal(r: FullRun, t: float) -> None:
            """Let the HA re-reads succeed again and count the failed ones."""
            assert r.ha is not None
            r.ha.reads_fail = False
            self.notes["failed_reads"] = r.ha.failed_reads - self.notes["failed_before"]

        self.at(0.0, fail)
        self.at(self.failing_s, heal)

    def checks(self, run: FullRun) -> list[Check]:
        """Alarm raised and cleared; held values fall back to the 1800 s limit."""
        back = self.start + self.failing_s
        limit = float(run.system.runtime.store.policy.ha_max_age_s)
        unconfirmed = self.between(self.start + HA_LINK_WINDOW_S + TICK_S, back)
        too_old = [
            d for d in unconfirmed if d.room and d.room[2] and (d.room[1] or 0.0) > limit + EPSILON
        ]
        raised = self.raised(HA_LINK_ALARM, self.start)
        cleared = [a for a in self.alarms if a.code == HA_LINK_ALARM and a.event == "cleared"]
        return [
            verdict(
                "re-reads failed",
                int(self.notes.get("failed_reads", 0)) > 0,
                f"{self.notes.get('failed_reads', 0)} failed re-reads",
            ),
            verdict(
                "ha_link_down raised while the re-reads fail and cleared after",
                bool(raised) and raised[0].ts < back and any(c.ts >= back for c in cleared),
                f"raised {[_iso(a.ts) for a in raised]}, cleared {[_iso(a.ts) for a in cleared]}",
            ),
            verdict(
                f"without a confirmed link no room value older than {limit:.0f} s is used",
                bool(unconfirmed) and not too_old,
                f"{len(unconfirmed)} decisions, {len(too_old)} too old",
            ),
            verdict(
                "the link is confirmed again after the re-reads succeed",
                run.system.runtime.store.link_up(SourceKind.HA, run.clock()),
            ),
        ]


@dataclass
class RoomSensorFailsHigh(Scenario):
    """The room sensor fails high (3.7 K above the room for 8 h) while wood-stove mode is on.

    A step of several K within one report is a sensor fault, not a stove (a stove warms
    the room by about 1 K per 10 min at most): wood-stove mode must not start (it would
    back off and widen the cross-check for up to 24 h), the cross-check against
    ``main/Room_Thermostat_Temp`` must flag the value within its sustain time, and while
    it does the room feedback must not cool.
    """

    name: str = "room_sensor_fails_high"
    window_s: float = 12 * HOUR
    offset_k: float = 3.7
    fault_at_s: float = HOUR
    fault_s: float = 8 * HOUR
    recognise_within_s: float = 2 * TICK_S
    recover_s: float = HOUR

    def plan(self, run: FullRun) -> None:
        """Enable wood-stove mode, make the sensor fail high, heal it, disable the mode."""

        def fail(r: FullRun, t: float) -> None:
            """Bias the room sensor high for the fault duration."""
            assert r.feed is not None
            start = self.start + self.fault_at_s
            r.feed.bias(self.offset_k, start, start + self.fault_s)

        self.at(0.0, _stove_mode(True, self.name))
        self.at(0.0, fail)
        self.at(self.window_s - 2 * TICK_S, _stove_mode(False, self.name))

    def checks(self, run: FullRun) -> list[Check]:
        """Fault recognised, no stove episode, implausible flagged, no cooling, recovery.

        Parameters
        ----------
        run
            The finished full run.

        Returns
        -------
        list[Check]
            One verdict per checked behaviour.
        """
        profile = run.system.loop.controller.config.room
        comfort = run.settings.control_comfort_c
        start = self.start + self.fault_at_s
        end = start + self.fault_s
        decisions = [d for d in self.decisions if d.ladder in CONTROL]
        during = [d for d in decisions if start <= d.ts < end]
        fault = next((d for d in during if d.state.get("stove_fault") is True), None)
        active = [d for d in decisions if d.state.get("stove_state") == "active"]
        raised = self.raised(AlarmCode.ROOM_IMPLAUSIBLE.value, start)
        flagged = [d for d in during if d.state.get("room_plausible") is False]
        cooling = [d for d in flagged if d.feedback is not None and d.feedback < -EPSILON]
        rooms = [room for _, room in self.rooms]
        floor = comfort - COMFORT_FLOOR_K
        events = [
            a
            for a in self.alarms
            if a.code == AlarmCode.ROOM_IMPLAUSIBLE.value and a.ts <= end + self.recover_s
        ]
        last = events[-1] if events else None
        self.notes.update(
            {
                "fault_from": _iso(start),
                "fault_to": _iso(end),
                "recognised": None if fault is None else _iso(fault.ts),
                "jump_k": None if fault is None else fault.state.get("stove_jump_k"),
                "implausible_raised": [_iso(a.ts) for a in raised],
                "implausible_decisions": len(flagged),
                "decisions_in_fault": len(during),
                "room_min_c": round(min(rooms), 2) if rooms else None,
            }
        )
        sustain = profile.crosscheck_sustain_s
        first = raised[0].ts - start if raised else None
        return [
            verdict(
                "the room sensor has the pump's thermostat as its cross-check",
                profile.crosscheck is not None,
                str(profile.crosscheck),
            ),
            verdict(
                f"the step is taken for a sensor fault within "
                f"{self.recognise_within_s / 60:.0f} min",
                fault is not None and fault.ts - start <= self.recognise_within_s + EPSILON,
                "never" if fault is None else f"after {fault.ts - start:.0f} s",
            ),
            verdict(
                "no wood-stove episode",
                not active,
                f"{len(active)} active decisions"
                + (f" (first at {_iso(active[0].ts)})" if active else ""),
            ),
            verdict(
                f"room_implausible is raised within the cross-check's sustain time "
                f"({sustain / 60:.0f} min) plus {SLACK_S / 60:.0f} min",
                first is not None and first <= sustain + SLACK_S + EPSILON,
                "never" if first is None else f"after {first / 60:.0f} min",
            ),
            verdict(
                "no cooling feedback while the value is implausible",
                bool(flagged) and not cooling,
                f"{len(flagged)} implausible decisions, {len(cooling)} cooling",
            ),
            verdict(
                f"the room never drops below comfort - {COMFORT_FLOOR_K:g} K ({floor:.1f} °C)",
                bool(rooms) and min(rooms) >= floor - EPSILON,
                f"minimum {self.notes['room_min_c']} °C",
            ),
            verdict(
                f"room_implausible clears within {self.recover_s / 60:.0f} min after the "
                "sensor recovers",
                last is not None and last.event == "cleared" and last.ts >= end - EPSILON,
                "no event" if last is None else f"{last.event} at {_iso(last.ts)}",
            ),
        ]
