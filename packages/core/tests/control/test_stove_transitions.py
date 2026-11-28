"""Characterisation of the wood-stove state machine, one transition at a time.

Each case feeds :func:`ovenbird_core.control.stove.advance` a carried state and one
tick's inputs and compares the whole :class:`StoveStep` it returns.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from ovenbird_core.control import (
    OvenbirdConfig,
    OvenbirdState,
    Override,
    OverrideKind,
    RoomInput,
    RoomProfile,
    RoomSensorProfile,
    StoveConfig,
    StoveExit,
    StoveSource,
    StoveTrigger,
)
from ovenbird_core.control.stove import StoveStep, advance
from ovenbird_core.control.synthetic import ROOM_SIGNAL
from ovenbird_core.instant import Instant

NOW = 100_000.0
HOUR = 3600.0
COMFORT = 21.0
HALL = "ha/sensor.hall_temperature"
UNTIL = Instant.from_unix(1_794_528_000.0)
IDLE = OvenbirdState(integral_k=0.7)
AUTO = OvenbirdState(
    integral_k=0.4,
    stove_source=StoveSource.AUTO,
    stove_trigger=StoveTrigger.LEVEL,
    stove_since=NOW - 2 * HOUR,
    stove_entry_c=22.6,
    stove_integral_k=0.4,
)
MANUAL = OvenbirdState(
    integral_k=0.3,
    stove_source=StoveSource.MANUAL,
    stove_trigger=StoveTrigger.MANUAL,
    stove_since=NOW - 600.0,
    stove_entry_c=22.8,
    stove_integral_k=0.3,
)
AUTO_EPISODE: dict[str, Any] = {
    "source": StoveSource.AUTO,
    "trigger": StoveTrigger.LEVEL,
    "since": NOW - 2 * HOUR,
    "entry_c": 22.6,
    "integral_k": 0.4,
}
MANUAL_EPISODE: dict[str, Any] = {
    "source": StoveSource.MANUAL,
    "trigger": StoveTrigger.MANUAL,
    "since": NOW - 600.0,
    "entry_c": 22.8,
    "integral_k": 0.3,
}


def config(stove: StoveConfig | None = None, *, on_change: bool = False) -> OvenbirdConfig:
    """Return the ``mixed`` preset at the test comfort target with ``stove``."""
    room = RoomSensorProfile(kind=RoomProfile.ON_CHANGE) if on_change else RoomSensorProfile()
    return OvenbirdConfig.preset(
        "mixed", comfort_room_c=COMFORT, stove=StoveConfig() if stove is None else stove, room=room
    )


def trusted(value: float) -> RoomInput:
    """Return a fresh periodic room value (full cooling authority)."""
    return RoomInput(value, 10.0, True, ROOM_SIGNAL)


def untrusted(value: float) -> RoomInput:
    """Return an on-change room value without a proof of life for 4 h (reduced authority)."""
    return RoomInput(
        value,
        4 * HOUR,
        True,
        ROOM_SIGNAL,
        quantum_k=0.2,
        held_s=4 * HOUR,
        profile=RoomProfile.ON_CHANGE,
    )


def fresh_window(value: float) -> dict[str, Any]:
    """Return the window fields after a first trusted ``value`` at ``NOW``."""
    return {
        "low_c": value,
        "low_at": NOW,
        "high_c": value,
        "high_at": NOW,
        "predip_c": value,
        "step_low_c": value,
        "step_low_at": NOW,
    }


def manual(value: float = 1.0, until: Instant | None = UNTIL) -> Override:
    """Return a wood-stove override (``0`` is a stop)."""
    return Override(OverrideKind.STOVE, value, until)


def step(
    state: OvenbirdState,
    room: RoomInput | None,
    *,
    cfg: OvenbirdConfig | None = None,
    override: Override | None = None,
    reference_c: float | None = None,
    entry_shift_k: float = 0.0,
) -> StoveStep:
    """Advance the state machine once at ``NOW``."""
    return advance(
        config() if cfg is None else cfg, state, room, override, NOW, reference_c, entry_shift_k
    )


class TestDisabled:
    """Without a stove configuration."""

    def test_idle_stays_empty(self) -> None:
        """No configuration and no episode give an empty step."""
        cfg = OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT)
        assert step(IDLE, trusted(25.0), cfg=cfg, override=manual()) == StoveStep()

    def test_an_episode_ends(self) -> None:
        """No configuration ends a carried episode."""
        cfg = OvenbirdConfig.preset("mixed", comfort_room_c=COMFORT)
        assert step(AUTO, trusted(25.0), cfg=cfg) == StoveStep(
            event="exited", ended=StoveExit.DISABLED
        )


class TestLevelEntry:
    """The level trigger and the entry shift of an active plan slice."""

    def test_at_the_threshold(self) -> None:
        """The room at the entry threshold enters with the integrator of the state."""
        assert step(IDLE, trusted(22.5)) == StoveStep(
            source=StoveSource.AUTO,
            trigger=StoveTrigger.LEVEL,
            since=NOW,
            entry_c=22.5,
            integral_k=0.7,
            **fresh_window(22.5),
            event="entered",
            rise_k=0.0,
        )

    def test_just_below(self) -> None:
        """Just below the threshold nothing happens but the window."""
        assert step(IDLE, trusted(22.4)) == StoveStep(**fresh_window(22.4), rise_k=0.0)

    def test_untrusted_value_clears_the_window(self) -> None:
        """A value with reduced authority keeps only the fault-step low."""
        state = replace(IDLE, stove_low_c=21.0, stove_low_at=NOW - 60.0, stove_predip_c=21.0)
        assert step(state, untrusted(23.7), cfg=config(on_change=True)) == StoveStep(
            step_low_c=23.7, step_low_at=NOW
        )

    def test_no_room_value(self) -> None:
        """Without a room value the step is empty."""
        assert step(IDLE, None) == StoveStep()

    def test_shift_lifts_the_threshold(self) -> None:
        """A plan raise of 1 K moves the entry from 22.5 to 23.5 °C."""
        assert step(IDLE, trusted(23.0), entry_shift_k=1.0) == StoveStep(
            **fresh_window(23.0), rise_k=0.0, entry_shift_k=1.0
        )
        entered = step(IDLE, trusted(23.5), entry_shift_k=1.0)
        assert (entered.trigger, entered.entry_shift_k) == (StoveTrigger.LEVEL, 1.0)

    def test_negative_shift_counts_as_zero(self) -> None:
        """A negative shift does not lower the threshold."""
        entered = step(IDLE, trusted(22.5), entry_shift_k=-2.0)
        assert (entered.trigger, entered.entry_shift_k) == (StoveTrigger.LEVEL, 0.0)

    def test_shift_leaves_the_exit(self) -> None:
        """The exit keeps the comfort target while a plan raises the entry."""
        held = step(AUTO, trusted(21.6), entry_shift_k=2.0)
        assert held == StoveStep(
            **AUTO_EPISODE, **fresh_window(21.6), rise_k=21.6 - 23.0, entry_shift_k=2.0
        )
        assert step(AUTO, trusted(21.4), entry_shift_k=2.0).ended is StoveExit.COOLED

    def test_other_overrides_are_ignored(self) -> None:
        """A boost override is no stove request."""
        entered = step(IDLE, trusted(23.0), override=Override(OverrideKind.BOOST, 2.0, UNTIL))
        assert (entered.trigger, entered.until) == (StoveTrigger.LEVEL, None)


RISING = replace(
    IDLE,
    stove_low_c=21.2,
    stove_low_at=NOW - 600.0,
    stove_high_c=21.2,
    stove_high_at=NOW - 600.0,
    stove_predip_c=21.0,
    stove_step_low_c=21.2,
    stove_step_low_at=NOW - 600.0,
)
RISEN: dict[str, Any] = {
    "low_c": 21.2,
    "low_at": NOW - 600.0,
    "high_c": 22.3,
    "high_at": NOW,
    "predip_c": 21.0,
    "step_low_c": 21.2,
    "step_low_at": NOW - 600.0,
    "rise_k": 22.3 - 21.2,
    "jump_k": 22.3 - 21.2,
}


class TestRiseEntry:
    """The fast-rise trigger and its window."""

    def test_fast_rise_enters(self) -> None:
        """A rise of 1.1 K within the window enters below the level threshold."""
        assert step(RISING, trusted(22.3)) == StoveStep(
            source=StoveSource.AUTO,
            trigger=StoveTrigger.RISE,
            since=NOW,
            entry_c=22.3,
            integral_k=0.7,
            event="entered",
            **RISEN,
        )

    def test_not_above_the_level_before_a_dip(self) -> None:
        """A rebound to below the level before a dip does not enter."""
        state = replace(RISING, stove_predip_c=22.4)
        assert step(state, trusted(22.3)) == StoveStep(
            **{**RISEN, "predip_c": 22.4, "jump_k": 22.3 - 22.4}
        )

    def test_switched_off(self) -> None:
        """Without ``rise_k`` the fast rise does not enter."""
        cfg = config(StoveConfig(rise_k=None))
        assert step(RISING, trusted(22.3), cfg=cfg) == StoveStep(**RISEN)

    def test_measured_from_the_shifted_target(self) -> None:
        """With a plan raise the rise counts from the raised target."""
        assert step(RISING, trusted(22.3), entry_shift_k=0.5) == StoveStep(
            **{**RISEN, "rise_k": 22.3 - 21.5}, entry_shift_k=0.5
        )

    def test_enters_while_the_level_is_blocked(self) -> None:
        """After the cap the fast rise still enters."""
        entered = step(replace(RISING, stove_level_blocked=True), trusted(22.3))
        assert (entered.trigger, entered.level_blocked) == (StoveTrigger.RISE, True)

    def test_blocked_level_does_not_enter(self) -> None:
        """After the cap the level alone does not enter."""
        state = replace(IDLE, stove_level_blocked=True)
        assert step(state, trusted(23.0)) == StoveStep(
            **fresh_window(23.0), level_blocked=True, rise_k=0.0
        )

    def test_window_restarts_with_the_recent_high_as_predip(self) -> None:
        """An old low restarts the window and keeps the recent high as the predip level."""
        state = replace(
            IDLE,
            stove_low_c=21.0,
            stove_low_at=NOW - 1900.0,
            stove_high_c=22.0,
            stove_high_at=NOW - 100.0,
        )
        assert step(state, trusted(21.8)) == StoveStep(
            low_c=21.8,
            low_at=NOW,
            high_c=22.0,
            high_at=NOW - 100.0,
            predip_c=22.0,
            step_low_c=21.8,
            step_low_at=NOW,
            rise_k=0.0,
        )


class TestArming:
    """What keeps the detection from entering and what re-arms it."""

    def test_sensor_fault_step(self) -> None:
        """A 2 K step within the fault window is a fault, not a stove."""
        state = replace(IDLE, stove_step_low_c=21.0, stove_step_low_at=NOW - 300.0)
        assert step(state, trusted(23.0)) == StoveStep(
            **{**fresh_window(23.0), "step_low_c": 21.0, "step_low_at": NOW - 300.0},
            fault=True,
            rise_k=0.0,
            jump_k=2.0,
        )

    def test_blocks_hold_while_warm(self) -> None:
        """Fault, manual-stop block and level block hold while the room is warm."""
        state = replace(IDLE, stove_fault=True, stove_blocked=True, stove_level_blocked=True)
        assert step(state, trusted(23.0)) == StoveStep(
            **fresh_window(23.0), fault=True, blocked=True, level_blocked=True, rise_k=0.0
        )

    def test_blocks_clear_once_cooled(self) -> None:
        """Fault, manual-stop block and level block clear below the exit threshold."""
        state = replace(IDLE, stove_fault=True, stove_blocked=True, stove_level_blocked=True)
        assert step(state, trusted(21.4)) == StoveStep(**fresh_window(21.4), rise_k=0.0)

    def test_reentry_wait_starts_counting(self) -> None:
        """The first trusted tick starts the re-entry hold."""
        state = replace(IDLE, stove_reentry_wait=True)
        assert step(state, trusted(23.0)) == StoveStep(
            **fresh_window(23.0), reentry_wait=True, trusted_since=NOW, rise_k=0.0
        )

    def test_reentry_wait_restarts_without_trust(self) -> None:
        """An untrusted tick restarts the re-entry hold."""
        state = replace(IDLE, stove_reentry_wait=True, stove_trusted_since=NOW - 600.0)
        assert step(state, None) == StoveStep(reentry_wait=True)

    def test_reentry_wait_ends_and_enters(self) -> None:
        """After the hold the detection enters on the same tick."""
        state = replace(IDLE, stove_reentry_wait=True, stove_trusted_since=NOW - 900.0)
        assert step(state, trusted(23.0)) == StoveStep(
            source=StoveSource.AUTO,
            trigger=StoveTrigger.LEVEL,
            since=NOW,
            entry_c=23.0,
            integral_k=0.7,
            **fresh_window(23.0),
            event="entered",
            rise_k=0.0,
        )

    def test_reference_gap_too_small(self) -> None:
        """With a fresh reference room the room must be 1 K above it."""
        cfg = config(StoveConfig(reference=HALL))
        assert step(IDLE, trusted(23.0), cfg=cfg, reference_c=22.5) == StoveStep(
            **fresh_window(23.0), rise_k=0.0, gap_k=0.5, gap_short=True
        )

    def test_reference_gap_large_enough(self) -> None:
        """A room 2 K above the reference room enters."""
        cfg = config(StoveConfig(reference=HALL))
        entered = step(IDLE, trusted(23.0), cfg=cfg, reference_c=21.0)
        assert (entered.trigger, entered.gap_k, entered.gap_short) == (
            StoveTrigger.LEVEL,
            2.0,
            False,
        )

    def test_auto_off_does_not_enter(self) -> None:
        """With the detection off a warm room does not enter."""
        cfg = config(StoveConfig(auto=False))
        assert step(IDLE, trusted(23.0), cfg=cfg) == StoveStep(**fresh_window(23.0), rise_k=0.0)


class TestAutoEpisode:
    """Hold and exits of an automatic episode."""

    def test_holds_while_warm(self) -> None:
        """Above the exit threshold the episode continues."""
        assert step(AUTO, trusted(22.0)) == StoveStep(
            **AUTO_EPISODE, **fresh_window(22.0), rise_k=0.0
        )

    def test_cooled_before_the_minimum_holds(self) -> None:
        """A cooled room does not end the episode before ``min_active_s``."""
        state = replace(AUTO, stove_since=NOW - 1800.0)
        assert step(state, trusted(21.4)) == StoveStep(
            **{**AUTO_EPISODE, "since": NOW - 1800.0}, **fresh_window(21.4), rise_k=0.0
        )

    def test_cooled(self) -> None:
        """A cooled room ends the episode after ``min_active_s``."""
        assert step(AUTO, trusted(21.4)) == StoveStep(
            **fresh_window(21.4), event="exited", ended=StoveExit.COOLED, rise_k=0.0
        )

    def test_reference_warm(self) -> None:
        """A reference room within half the gap ends the episode."""
        cfg = config(StoveConfig(reference=HALL))
        assert step(AUTO, trusted(22.0), cfg=cfg, reference_c=21.6) == StoveStep(
            **fresh_window(22.0),
            event="exited",
            ended=StoveExit.REFERENCE_WARM,
            rise_k=0.0,
            gap_k=22.0 - 21.6,
            gap_short=True,
        )

    def test_reference_warm_before_the_minimum_holds(self) -> None:
        """A warm reference room does not end the episode before ``min_active_s``."""
        cfg = config(StoveConfig(reference=HALL))
        state = replace(AUTO, stove_since=NOW - 1800.0)
        assert step(state, trusted(22.0), cfg=cfg, reference_c=21.6).source is StoveSource.AUTO

    def test_max_active_blocks_the_level_and_restarts_the_window(self) -> None:
        """The cap ends the episode, blocks the level and restarts the rise window."""
        state = replace(
            AUTO,
            stove_since=NOW - 8 * HOUR,
            stove_low_c=21.0,
            stove_low_at=NOW - 600.0,
            stove_high_c=23.0,
            stove_high_at=NOW - 60.0,
            stove_predip_c=21.0,
        )
        assert step(state, trusted(23.0)) == StoveStep(
            **{**fresh_window(23.0), "step_low_c": 23.0},
            level_blocked=True,
            event="exited",
            ended=StoveExit.MAX_ACTIVE,
            rise_k=2.0,
        )

    def test_max_active_before_cooled(self) -> None:
        """The cap wins over a cooled room and still blocks the level."""
        state = replace(AUTO, stove_since=NOW - 8 * HOUR)
        ended = step(state, trusted(21.4))
        assert (ended.ended, ended.level_blocked) == (StoveExit.MAX_ACTIVE, True)

    def test_room_untrusted(self) -> None:
        """A lost room value ends the episode and starts the re-entry hold."""
        assert step(AUTO, None) == StoveStep(
            reentry_wait=True, event="exited", ended=StoveExit.ROOM_UNTRUSTED
        )

    def test_room_untrusted_without_hold(self) -> None:
        """With ``reentry_hold_s`` 0 there is no re-entry hold."""
        cfg = config(StoveConfig(reentry_hold_s=0.0))
        assert step(AUTO, None, cfg=cfg) == StoveStep(
            event="exited", ended=StoveExit.ROOM_UNTRUSTED
        )

    def test_room_untrusted_resets_the_trust_timer(self) -> None:
        """A value with reduced authority ends the episode and forgets the trust timer."""
        state = replace(AUTO, stove_trusted_since=NOW - 60.0)
        assert step(state, untrusted(23.0), cfg=config(on_change=True)) == StoveStep(
            step_low_c=23.0,
            step_low_at=NOW,
            reentry_wait=True,
            event="exited",
            ended=StoveExit.ROOM_UNTRUSTED,
        )

    def test_room_jump(self) -> None:
        """A sensor-fault step ends the episode."""
        state = replace(AUTO, stove_step_low_c=21.0, stove_step_low_at=NOW - 300.0)
        assert step(state, trusted(23.5)) == StoveStep(
            **{**fresh_window(23.5), "step_low_c": 21.0, "step_low_at": NOW - 300.0},
            fault=True,
            event="exited",
            ended=StoveExit.ROOM_JUMP,
            rise_k=0.0,
            jump_k=2.5,
        )

    def test_room_jump_wins_over_untrusted(self) -> None:
        """A step on an untrusted value is a jump, without a re-entry hold."""
        state = replace(AUTO, stove_step_low_c=21.0, stove_step_low_at=NOW - 300.0)
        ended = step(state, untrusted(23.5), cfg=config(on_change=True))
        assert (ended.ended, ended.reentry_wait, ended.fault) == (StoveExit.ROOM_JUMP, False, True)

    def test_auto_off_wins_over_a_jump(self) -> None:
        """Switching the detection off ends the episode first."""
        state = replace(AUTO, stove_step_low_c=21.0, stove_step_low_at=NOW - 300.0)
        ended = step(state, trusted(23.5), cfg=config(StoveConfig(auto=False)))
        assert (ended.ended, ended.fault) == (StoveExit.AUTO_OFF, True)


class TestManual:
    """Manual start, keep, stop and the hand-over to the detection."""

    def test_start(self) -> None:
        """A request starts an episode on a cool room with the state's integrator."""
        assert step(IDLE, trusted(21.0), override=manual()) == StoveStep(
            source=StoveSource.MANUAL,
            trigger=StoveTrigger.MANUAL,
            since=NOW,
            entry_c=21.0,
            integral_k=0.7,
            **fresh_window(21.0),
            event="entered",
            rise_k=0.0,
            until=UNTIL,
        )

    def test_start_without_a_trusted_value(self) -> None:
        """A request starts without an entry temperature when the value is not trusted."""
        assert step(IDLE, None, override=manual(until=None)) == StoveStep(
            source=StoveSource.MANUAL,
            trigger=StoveTrigger.MANUAL,
            since=NOW,
            integral_k=0.7,
            event="entered",
        )

    def test_takes_over_an_automatic_episode(self) -> None:
        """A request during an automatic episode keeps its trigger and start."""
        assert step(AUTO, trusted(23.0), override=manual()) == StoveStep(
            **{**AUTO_EPISODE, "source": StoveSource.MANUAL},
            **fresh_window(23.0),
            rise_k=0.0,
            until=UNTIL,
        )

    def test_keeps_a_manual_episode(self) -> None:
        """A request keeps a manual episode through a fault step."""
        state = replace(MANUAL, stove_step_low_c=21.0, stove_step_low_at=NOW - 300.0)
        assert step(state, trusted(23.5), override=manual()) == StoveStep(
            **MANUAL_EPISODE,
            **{**fresh_window(23.5), "step_low_c": 21.0, "step_low_at": NOW - 300.0},
            fault=True,
            rise_k=0.0,
            jump_k=2.5,
            until=UNTIL,
        )

    def test_stop(self) -> None:
        """A stop ends the episode and blocks the detection."""
        assert step(AUTO, trusted(23.0), override=manual(0.0)) == StoveStep(
            **fresh_window(23.0),
            blocked=True,
            event="exited",
            ended=StoveExit.MANUAL_STOP,
            rise_k=0.0,
        )

    def test_stop_without_an_episode(self) -> None:
        """A stop without an episode only blocks the detection, even on a cool room."""
        assert step(IDLE, trusted(21.0), override=manual(0.0)) == StoveStep(
            **fresh_window(21.0), blocked=True, rise_k=0.0
        )

    def test_hand_over(self) -> None:
        """A manual episode ending on a warm room continues as an automatic one."""
        assert step(MANUAL, trusted(22.0)) == StoveStep(
            **{
                **MANUAL_EPISODE,
                "source": StoveSource.AUTO,
                "trigger": StoveTrigger.HANDOVER,
                "since": NOW,
            },
            **fresh_window(22.0),
            rise_k=0.0,
        )

    @pytest.mark.parametrize(
        ("state", "room", "stove", "reference_c"),
        [
            (MANUAL, 21.4, StoveConfig(), None),
            (replace(MANUAL, stove_entry_c=None), 23.0, StoveConfig(), None),
            (replace(MANUAL, stove_blocked=True), 23.0, StoveConfig(), None),
            (replace(MANUAL, stove_fault=True), 23.0, StoveConfig(), None),
            (MANUAL, 23.0, StoveConfig(reference=HALL), 22.5),
            (MANUAL, 23.0, StoveConfig(auto=False), None),
        ],
        ids=["cooled", "no_entry_value", "blocked", "fault", "gap_short", "auto_off"],
    )
    def test_no_hand_over(
        self, state: OvenbirdState, room: float, stove: StoveConfig, reference_c: float | None
    ) -> None:
        """Without the hand-over conditions the episode ends and nothing enters this tick."""
        ended = step(state, trusted(room), cfg=config(stove), reference_c=reference_c)
        assert (ended.source, ended.trigger, ended.since, ended.entry_c, ended.integral_k) == (
            None,
            None,
            None,
            None,
            None,
        )
        assert (ended.event, ended.ended, ended.until) == ("exited", StoveExit.MANUAL_ENDED, None)

    def test_no_hand_over_without_a_trusted_value(self) -> None:
        """A manual episode ending without a trusted value ends."""
        assert step(MANUAL, None) == StoveStep(event="exited", ended=StoveExit.MANUAL_ENDED)
