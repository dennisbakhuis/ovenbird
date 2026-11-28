"""State the controller carries from tick to tick, and the enums it holds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ovenbird_core.control.record import StateValue


class RampPhase(StrEnum):
    """Phase of the start ramp."""

    IDLE = "idle"
    HOLD = "hold"
    RELEASE = "release"


class StoveSource(StrEnum):
    """Who started the wood-stove episode."""

    AUTO = "auto"
    MANUAL = "manual"


class StoveTrigger(StrEnum):
    """What started the wood-stove episode.

    ``level``: the room reached the entry threshold; ``rise``: the fast-rise trigger;
    ``manual``: a request; ``handover``: a manual episode ended while the room was
    still above the exit threshold, so the automatic detection took over.
    """

    LEVEL = "level"
    RISE = "rise"
    MANUAL = "manual"
    HANDOVER = "handover"


@dataclass(frozen=True, slots=True)
class OvenbirdState:
    """Controller state carried from tick to tick (monotonic seconds for times).

    Parameters
    ----------
    setpoint
        Last desired integer water setpoint.
    last_change_at
        When the desired setpoint last changed.
    integral_k
        PI integrator in K water.
    outside_filtered
        Filtered outside temperature.
    outside_at
        When the filter last took a sample.
    last_tick_at
        When the previous tick ran.
    running
        Compressor running at the previous tick (``None`` before it was known).
    run_started_at
        Detected start of the current run (``None`` when unknown or stopped).
    stopped_at
        Detected end of the previous run.
    ramp_phase
        Start-ramp phase.
    ramp_elapsed_s
        Non-defrost run time since the ramp started.
    ramp_cap
        Current ramp cap in °C.
    pump_duty
        Last desired max pump duty.
    quiet_level
        Last desired quiet level.
    crosscheck_offset_k
        Learned offset of the cross-check signal over the room value.
    crosscheck_since
        When the room value and the cross-check started to disagree.
    crosscheck_latched
        Room value at which the cross-check declared it implausible; the verdict
        holds until the room value changes.
    room_lost_at
        When the room value went stale or implausible (the held offset fades
        from then).
    integral_at_life_k
        Integrator at the room sensor's last proof of life (``on_change``), kept
        while the value is lost; a device silent beyond ``alive_decay_start_s``,
        or whose value went stale or implausible, keeps no cooling integrated
        since then.
    stove_source
        Who started the active wood-stove episode (``None``: inactive).
    stove_trigger
        What started it.
    stove_since
        When it started.
    stove_entry_c
        Room value at the start (``None`` when unknown, e.g. a manual start).
    stove_integral_k
        Integrator at the start (held through the episode).
    stove_blocked
        The automatic detection waits until the room has cooled below the exit
        threshold (after a manual stop).
    stove_level_blocked
        The level trigger waits until the room has cooled below the exit threshold
        (after an episode reached ``max_active_s``); a new fast rise may still enter.
    stove_reentry_wait, stove_trusted_since
        After an episode ended because the room value lost its trust: no automatic
        entry until the value has been trusted again for ``reentry_hold_s``, and
        since when it is.
    stove_low_c, stove_low_at
        Lowest trusted room value of the fast-rise window and when it was seen.
    stove_high_c, stove_high_at
        Highest trusted room value of the fast-rise window and when it was seen.
    stove_predip_c
        Highest value of the window when its low was last set (the level before a
        dip); a fast rise must go above it.
    stove_step_low_c, stove_step_low_at
        Lowest plausible room value of the sensor-fault window and when it was seen.
    stove_fault
        A sensor-fault step was seen: the automatic detection waits until the room has
        cooled below the exit threshold.
    summer_mean_c, summer_mean_at
        Slow outside mean of the summer switch and when it last took a sample (``None``
        without the switch).
    summer_mean_from
        When the slow mean took its first sample (the switch waits one time constant).
    summer_active
        The summer switch is on.
    """

    setpoint: int | None = None
    last_change_at: float | None = None
    integral_k: float = 0.0
    outside_filtered: float | None = None
    outside_at: float | None = None
    last_tick_at: float | None = None
    running: bool | None = None
    run_started_at: float | None = None
    stopped_at: float | None = None
    ramp_phase: RampPhase = RampPhase.IDLE
    ramp_elapsed_s: float = 0.0
    ramp_cap: float | None = None
    pump_duty: int | None = None
    quiet_level: int | None = None
    crosscheck_offset_k: float | None = None
    crosscheck_since: float | None = None
    crosscheck_latched: float | None = None
    room_lost_at: float | None = None
    integral_at_life_k: float | None = None
    stove_source: StoveSource | None = None
    stove_trigger: StoveTrigger | None = None
    stove_since: float | None = None
    stove_entry_c: float | None = None
    stove_integral_k: float | None = None
    stove_blocked: bool = False
    stove_level_blocked: bool = False
    stove_reentry_wait: bool = False
    stove_trusted_since: float | None = None
    stove_low_c: float | None = None
    stove_low_at: float | None = None
    stove_high_c: float | None = None
    stove_high_at: float | None = None
    stove_predip_c: float | None = None
    stove_step_low_c: float | None = None
    stove_step_low_at: float | None = None
    stove_fault: bool = False
    summer_mean_c: float | None = None
    summer_mean_at: float | None = None
    summer_mean_from: float | None = None
    summer_active: bool = False

    @property
    def stove_active(self) -> bool:
        """Whether a wood-stove episode is active."""
        return self.stove_source is not None

    @property
    def held_integral_k(self) -> float:
        """Integrator kept when the room value is not trusted (its positive part)."""
        return max(0.0, self.integral_k)

    def as_flat(self) -> dict[str, StateValue]:
        """Return the state as a flat, JSON-friendly mapping.

        The summer switch's entries are present only once its slow mean has a value,
        so a configuration without the switch records exactly what it did before.
        """
        flat: dict[str, StateValue] = {
            "setpoint": self.setpoint,
            "last_change_at": self.last_change_at,
            "integral_k": self.integral_k,
            "outside_filtered_c": self.outside_filtered,
            "outside_at": self.outside_at,
            "last_tick_at": self.last_tick_at,
            "running": self.running,
            "run_started_at": self.run_started_at,
            "stopped_at": self.stopped_at,
            "ramp_phase": self.ramp_phase.value,
            "ramp_elapsed_s": self.ramp_elapsed_s,
            "ramp_cap_c": self.ramp_cap,
            "pump_duty": self.pump_duty,
            "quiet_level": self.quiet_level,
            "crosscheck_offset_k": self.crosscheck_offset_k,
            "crosscheck_since": self.crosscheck_since,
            "crosscheck_latched_c": self.crosscheck_latched,
            "room_lost_at": self.room_lost_at,
            "integral_at_life_k": self.integral_at_life_k,
            "stove_source": None if self.stove_source is None else self.stove_source.value,
            "stove_trigger": None if self.stove_trigger is None else self.stove_trigger.value,
            "stove_since": self.stove_since,
            "stove_entry_c": self.stove_entry_c,
            "stove_integral_k": self.stove_integral_k,
            "stove_blocked": self.stove_blocked,
            "stove_level_blocked": self.stove_level_blocked,
            "stove_reentry_wait": self.stove_reentry_wait,
            "stove_trusted_since": self.stove_trusted_since,
            "stove_low_c": self.stove_low_c,
            "stove_low_at": self.stove_low_at,
            "stove_high_c": self.stove_high_c,
            "stove_high_at": self.stove_high_at,
            "stove_predip_c": self.stove_predip_c,
            "stove_step_low_c": self.stove_step_low_c,
            "stove_step_low_at": self.stove_step_low_at,
            "stove_fault": self.stove_fault,
        }
        if self.summer_mean_c is not None or self.summer_active:
            flat |= {
                "summer_mean_c": self.summer_mean_c,
                "summer_mean_at": self.summer_mean_at,
                "summer_mean_from": self.summer_mean_from,
                "summer_active": self.summer_active,
            }
        return flat
