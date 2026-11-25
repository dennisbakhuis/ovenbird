"""Golden drills: operator and plant paths the fault catalogue does not reach.

Each drill is a :class:`~ovenbird_harness.faults.Scenario` that the golden decision log
(:mod:`ovenbird_harness.golden`) runs alone on the example house, so the decisions,
command events, alarm transitions and persisted state of these paths are part of the
byte comparison. The drills are not in :data:`~ovenbird_harness.faults.SCENARIOS`; their
checks only document what each drill reached (the golden header carries them). The
run's invariants assume uninterrupted automatic control, so a drill that pauses control
or overrides the setpoint shows the expected ``mode`` or ``dwell`` violations there.

``defrost_hold``
    The pump reports a defrost (longer than the ``defrost_stuck`` limit, so that alarm
    is raised and cleared as well) while an operator lowers the comfort temperature,
    and later a DHW run while it is lowered again: the setpoint is held (bindings
    ``defrost_hold`` and ``dhw_hold``) until each ends.
``manual_override``
    A manual water setpoint for an hour, then a boost for an hour, handed to the
    controller through the loop's manual request slot (the service has no API for
    these override kinds; the slot is the path its wood-stove request takes).
``latched_hold``
    A foreign writer three times in a row (with ten-minute holds) latches the command
    hold; ovenbird restarts with the latch, then an operator releases it.
``go_live_restore``
    An operator raises the comfort temperature, then releases control: the go-live
    snapshot's water setpoint is restored through the adapter and control pauses;
    later the operator reverts the comfort and resumes.
``stuck_warm_flagged``
    A house that has learned a large positive integrator: the room sensor sticks at a
    warm reading that keeps the PI unsaturated (so the integrator winds down on it)
    and far enough from the pump's thermostat that the cross-check flags it within
    its sustain time, before the alive ramp acts. The flag undoes the cooling since
    the last proof of life (``room_lost_rollback``) and the held offset applies until
    the sensor reports again.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from ovenbird.configstore import Actor
from ovenbird.control.adapter import RESTORE_PREFIX
from ovenbird.control.alarms import AlarmCode
from ovenbird.history.journal import DecisionRow
from ovenbird.stove.request import StoveRequest
from ovenbird_core import Instant
from ovenbird_core.control import IntentKind, Override, OverrideKind
from ovenbird_harness.faults import (
    CYCLE_S,
    DEFROST_TOPIC,
    FOREIGN_STEP_K,
    HARNESS_ADMIN,
    HOUR,
    Check,
    Scenario,
    verdict,
)
from ovenbird_harness.faults.scenario import Seen

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

DRILL_ACTOR: Final = "harness drill"
DRILL_HOLD_S: Final = 600.0
SETTLING: Final = ("start_ramp", "dwell")
LOWER_ROOM_K: Final = 2.0


def _wall(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def _verified_idle(run: FullRun) -> int | None:
    """Return ovenbird's verified water setpoint when nothing is queued or in flight."""
    status = run.system.adapter.status(run.clock())
    if status["in_flight"] is not None or status["queued"]:
        return None
    value = status["verified"].get(IntentKind.WATER_SETPOINT.value)
    return value if isinstance(value, int) else None


def _comfort(run: FullRun, comfort: float | None, comment: str) -> None:
    manager = run.system.config
    changes = {"control_comfort_c": comfort}
    warnings = [w.code for w in manager.validate(changes).warnings]
    manager.apply(
        manager.version or 0, changes, Actor(DRILL_ACTOR), comment=comment, acknowledge=warnings
    )


@dataclass(frozen=True, slots=True)
class ManualRequest(StoveRequest):
    """A manual setpoint or boost request in the loop's manual request slot.

    Parameters
    ----------
    kind
        ``setpoint`` or ``boost``.
    value
        The water setpoint (°C) or the boost (K).
    """

    kind: OverrideKind = OverrideKind.SETPOINT
    value: float = 0.0

    def override(self, now: Instant) -> Override:
        """Return the controller override of the request at ``now``."""
        until = StoveRequest.override(self, now).until
        return Override(self.kind, self.value, until, self.actor)


@dataclass
class Drill(Scenario):
    """A scenario that also keeps the binding of every decision in its window."""

    bindings: list[tuple[float, str | None]] = field(default_factory=list)
    latest: dict[str, Any] = field(default_factory=dict)

    def _decision(self, row: DecisionRow) -> None:
        super()._decision(row)
        record = json.loads(row.record)
        self.latest = record
        if self._inside(row.ts):
            self.bindings.append((row.ts, record["binding"]))

    def bound(self, binding: str, a: float, b: float) -> int:
        """Count the decisions with ``a <= ts < b`` that ``binding`` determined."""
        return sum(1 for ts, seen in self.bindings if a <= ts < b and seen == binding)

    def retry(self, t: float, action: Callable[[FullRun, float], None]) -> None:
        """Run ``action`` again at the next cycle."""
        self.at(t - self.start + CYCLE_S, action)


@dataclass
class DefrostHold(Drill):
    """A reported defrost and a DHW run, each while the comfort temperature is lowered.

    The DHW run starts when no start ramp or dwell holds the setpoint and the room
    feedback's cooling authority can still lower it by a few kelvin, so the lowered
    comfort asks for a lower setpoint while the run lasts.
    """

    name: str = "defrost_hold"
    window_s: float = 5 * HOUR
    max_wait_s: float = HOUR
    defrost_s: float = 1500.0
    dhw_after_s: float = 2 * HOUR
    dhw_s: float = 1500.0
    lower_k: float = 2.0
    defrost_at: float | None = None
    dhw_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Wait for a verified setpoint outside a defrost and a DHW run, then start."""
        self._arm(run, self.start)

    def _arm(self, run: FullRun, t: float) -> None:
        board = run.board
        quiet = not board.state.defrosting and not board.dhw
        if _verified_idle(run) is None or not quiet:
            if t - self.start < self.max_wait_s:
                self.retry(t, self._arm)
            return
        board.overrides[DEFROST_TOPIC] = "1"
        self.defrost_at = t
        offset = t - self.start
        self.at(offset + 60.0, self._lower)
        self.at(offset + self.defrost_s, self._defrost_end)
        self.at(offset + HOUR, self._revert)
        self.at(offset + self.dhw_after_s, self._arm_dhw)

    def _arm_dhw(self, run: FullRun, t: float) -> None:
        """Start the DHW run once no start ramp or dwell holds the setpoint, then lower."""
        ready = self._room_to_lower(run) and _verified_idle(run) is not None
        if run.board.state.defrosting or not ready:
            assert self.defrost_at is not None
            if t - self.defrost_at - self.dhw_after_s < self.max_wait_s:
                self.retry(t, self._arm_dhw)
            return
        self._dhw_start(run, t)
        offset = t - self.start
        self.at(offset + 60.0, self._lower)
        self.at(offset + self.dhw_s, self._dhw_end)
        self.at(offset + self.dhw_s + HOUR, self._revert)

    def _room_to_lower(self, run: FullRun) -> bool:
        """Whether the latest setpoint is settled and the room feedback can still lower it.

        Neither a start ramp nor a dwell holds it, and it lies at least
        :data:`LOWER_ROOM_K` above the curve minus the room feedback's clamp.
        """
        record = self.latest
        if not record or record.get("binding") in SETTLING or record.get("setpoint") is None:
            return False
        terms = {t.get("name"): t.get("value") for t in record.get("terms", [])}
        curve = terms.get("curve")
        if not isinstance(curve, int | float):
            return False
        floor = curve - run.system.loop.controller.config.feedback.output_limit_k
        return bool(record["setpoint"] >= floor + LOWER_ROOM_K)

    def _lower(self, run: FullRun, t: float) -> None:
        comfort = round(run.settings.control_comfort_c - self.lower_k, 1)
        _comfort(run, comfort, "golden drill: comfort lowered")
        self.notes.setdefault("comfort_c", []).append(comfort)

    def _defrost_end(self, run: FullRun, t: float) -> None:
        run.board.overrides.pop(DEFROST_TOPIC, None)

    def _dhw_start(self, run: FullRun, t: float) -> None:
        run.board.dhw = True
        self.dhw_at = t

    def _dhw_end(self, run: FullRun, t: float) -> None:
        run.board.dhw = False

    def _revert(self, run: FullRun, t: float) -> None:
        _comfort(run, None, "golden drill: comfort reverted")

    def checks(self, run: FullRun) -> list[Check]:
        """Check that the holds bind during the defrost and the DHW run."""
        if self.defrost_at is None or self.dhw_at is None:
            return [Check("drill started", "fail", "no verified setpoint to start from")]
        defrost = self.bound("defrost_hold", self.defrost_at, self.defrost_at + self.defrost_s)
        dhw = self.bound("dhw_hold", self.dhw_at, self.dhw_at + self.dhw_s)
        self.notes["defrost_hold"] = defrost
        self.notes["dhw_hold"] = dhw
        return [
            verdict("defrost_hold binds during the defrost", defrost > 0, f"{defrost} decisions"),
            verdict("dhw_hold binds during the DHW run", dhw > 0, f"{dhw} decisions"),
        ]


@dataclass
class ManualOverride(Drill):
    """A manual water setpoint for an hour, then a boost for an hour."""

    name: str = "manual_override"
    window_s: float = 4 * HOUR
    max_wait_s: float = HOUR
    hold_s: float = HOUR
    step_k: int = 3
    boost_k: float = 2.0
    set_at: float | None = None
    boost_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Wait for a verified setpoint, then request the manual setpoint."""
        self._set(run, self.start)

    def _request(self, run: FullRun, t: float, kind: OverrideKind, value: float) -> None:
        wall = _wall(t)
        request = ManualRequest(True, _wall(t + self.hold_s), DRILL_ACTOR, wall, kind, value)
        run.system.loop.stove_request = request
        self.notes.setdefault("requests", []).append({"kind": kind.value, "value": value})

    def _set(self, run: FullRun, t: float) -> None:
        verified = _verified_idle(run)
        if verified is None:
            if t - self.start < self.max_wait_s:
                self.retry(t, self._set)
            return
        low, high = run.system.adapter.config.setpoint_range
        value = min(max(verified + self.step_k, low), high)
        self._request(run, t, OverrideKind.SETPOINT, float(value))
        self.set_at = t
        self.at(t - self.start + self.hold_s + 120.0, self._boost)

    def _boost(self, run: FullRun, t: float) -> None:
        self._request(run, t, OverrideKind.BOOST, self.boost_k)
        self.boost_at = t

    def checks(self, run: FullRun) -> list[Check]:
        """Check that the manual setpoint and the boost reach the decisions and expire."""
        if self.set_at is None or self.boost_at is None:
            return [Check("drill started", "fail", "no verified setpoint to start from")]
        manual = self.bound("override", self.set_at, self.set_at + self.hold_s)
        boosted = [
            d
            for d in self.between(self.boost_at, self.boost_at + self.hold_s)
            if "boost" in d.terms
        ]
        after = [d for d in self.decisions if d.ts > self.boost_at + self.hold_s + 120.0]
        left = [d for d in after if "boost" in d.terms or "override" in d.terms]
        self.notes["override_bound"] = manual
        self.notes["boosted"] = len(boosted)
        return [
            verdict("the manual setpoint binds", manual > 0, f"{manual} decisions"),
            verdict("the boost term is applied", bool(boosted), f"{len(boosted)} decisions"),
            verdict("both expire", bool(after) and not left, f"{len(left)} after the end"),
        ]


@dataclass
class LatchedHold(Drill):
    """Three foreign writes latch the hold; a restart keeps it; an operator releases it.

    A foreign write that lands while ovenbird's own write is in flight is overwritten
    before the adapter reads it back (the last writer wins); the drill then writes again.
    """

    name: str = "latched_hold"
    window_s: float = 5 * HOUR
    writes: int = 0
    pending: bool = False
    latched_at: float | None = None
    released_at: float | None = None
    restart_after_s: float = 1200.0
    down_s: float = 300.0
    release_after_s: float = 2400.0
    give_up_s: float = 3 * HOUR

    def plan(self, run: FullRun) -> None:
        """Shorten the holds, then start writing."""
        adapter = run.system.adapter
        adapter.config = replace(adapter.config, hold_s=DRILL_HOLD_S)
        self._write(run, self.start)

    def _write(self, run: FullRun, t: float) -> None:
        adapter = run.system.adapter
        hold = adapter.hold
        if hold is not None and hold.latched:
            self.latched_at = t
            offset = t - self.start
            self.at(offset + self.restart_after_s, self._stop)
            self.at(offset + self.restart_after_s + self.down_s, self._start)
            self.at(offset + self.release_after_s, self._release)
            return
        verified = _verified_idle(run)
        if hold is not None or (verified is not None and self._overwritten(run, verified)):
            self.pending = False
        if hold is None and verified is not None and not self.pending:
            low, high = adapter.config.setpoint_range
            up = verified + FOREIGN_STEP_K
            value = min(max(up if up <= high else verified - FOREIGN_STEP_K, low), high)
            payload = json.dumps({"zone1": {"heat": {"target": {"high": value}}}})
            run.board.receive(f"{run.board.config.base}/commands/SetCurves", payload)
            self.writes += 1
            self.pending = True
            self.notes.setdefault("foreign", []).append(value)
        if t - self.start < self.give_up_s:
            self.retry(t, self._write)

    def _overwritten(self, run: FullRun, verified: int) -> bool:
        """Whether ovenbird's own write replaced the foreign value before it was read back."""
        return self.pending and run.board.registers.curve_target_high == verified

    def _stop(self, run: FullRun, t: float) -> None:
        run.stop_service()

    def _start(self, run: FullRun, t: float) -> None:
        run.start_service()
        hold = run.system.adapter.hold
        self.notes["latched_after_restart"] = hold is not None and hold.latched

    def _release(self, run: FullRun, t: float) -> None:
        released = run.system.adapter.release_hold(run.clock(), HARNESS_ADMIN)
        self.released_at = t
        self.notes["released"] = None if released is None else released.to_json()

    def checks(self, run: FullRun) -> list[Check]:
        """Check that the hold latches, survives the restart and is released."""
        latched = [a for a in self.alarms if a.code == "hold_latched" and a.event == "raised"]
        return [
            verdict("the hold latches", self.latched_at is not None, f"{self.writes} writes"),
            verdict(
                "the latch survives a restart",
                bool(self.notes.get("latched_after_restart")) and len(latched) >= 2,
                f"{len(latched)} hold_latched raised",
            ),
            verdict(
                "an operator releases it",
                self.notes.get("released") is not None,
                f"{self.notes.get('released')}",
            ),
        ]


@dataclass
class GoLiveRestore(Drill):
    """An operator releases control (the go-live snapshot is restored) and resumes later."""

    name: str = "go_live_restore"
    window_s: float = 5 * HOUR
    raise_k: float = 2.0
    release_after_s: float = 1.5 * HOUR
    resume_after_s: float = 3 * HOUR
    released: dict[str, Any] | None = None

    def plan(self, run: FullRun) -> None:
        """Raise the comfort, release, then revert and resume."""
        self.at(0.0, self._raise)
        self.at(self.release_after_s, self._release)
        self.at(self.resume_after_s, self._resume)

    def _raise(self, run: FullRun, t: float) -> None:
        comfort = round(run.settings.control_comfort_c + self.raise_k, 1)
        _comfort(run, comfort, "golden drill: comfort raised")

    def _release(self, run: FullRun, t: float) -> None:
        release = run.system.loop.release
        assert release is not None
        release.config = run.system.config
        release.start(Actor(HARNESS_ADMIN), rehearsal=True, reason="golden drill")

    def _resume(self, run: FullRun, t: float) -> None:
        release = run.system.loop.release
        assert release is not None
        self.released = release.last()
        self.notes["release"] = self.released
        _comfort(run, None, "golden drill: comfort reverted")
        run.system.config.resume(Actor(HARNESS_ADMIN))

    def checks(self, run: FullRun) -> list[Check]:
        """Check that the release restores the snapshot and finishes, and control resumes."""
        body = self.released or {}
        restored = [c for c in self.commands if c.detail.startswith(RESTORE_PREFIX)]
        resumed = [d for d in self.decisions if d.ts > self.start + self.resume_after_s]
        self.notes["restore_events"] = len(restored)
        return [
            verdict(
                "the release finishes",
                body.get("done") is True,
                f"outcome {body.get('outcome')}",
            ),
            verdict("the snapshot is restored", bool(restored), f"{len(restored)} events"),
            verdict(
                "control resumes",
                any(d.ladder != "refuse" for d in resumed),
                f"{len(resumed)} decisions after the resume",
            ),
        ]


@dataclass
class StuckWarmFlagged(Drill):
    """A stuck warm reading the cross-check flags while the integrator is well positive."""

    name: str = "stuck_warm_flagged"
    window_s: float = 5 * HOUR
    stuck_s: float = 4 * HOUR
    learned_k: float = 2.5
    warm_k: float = 2.5
    rollback_slack_k: float = 0.1

    def plan(self, run: FullRun) -> None:
        """Set the learned integrator and stick the sensor at the warm reading."""
        assert run.feed is not None
        loop = run.system.loop
        loop.state = replace(loop.state, integral_k=self.learned_k)
        value = round(run.config.profile.comfort_c + self.warm_k, 1)
        self.notes["stuck_value_c"] = value
        run.feed.stick(value, self.start, self.start + self.stuck_s)

    def checks(self, run: FullRun) -> list[Check]:
        """Check the flag, the rollback to the learned value and the held offset."""
        resume = self.start + self.stuck_s
        during = self.between(self.start, resume)
        rolled = [d for d in during if "room_lost_rollback" in str(d.state.get("frozen_by"))]
        lowest = min((float(d.state["integral_k"]) for d in during), default=math.nan)
        flagged = self.raised(AlarmCode.ROOM_IMPLAUSIBLE.value, self.start)
        lost = [d for d in during if d.state.get("room_lost_at") is not None]
        restored = [float(d.state["integral_k"]) for d in rolled]
        floor = self.learned_k - self.rollback_slack_k
        config = run.system.loop.controller.config
        fb = config.feedback
        step = min(fb.held_step_max_k, fb.kp * config.room.quantum_k)
        held = min(fb.output_limit_k, self.learned_k + step)
        off = [d for d in lost if d.feedback is None or d.feedback > held + 1e-6]
        self.notes["integral_low_k"] = lowest
        back = [d for d in self.between(resume, self.end) if d.ladder != "curve_only"]
        return [
            verdict(
                "the integrator winds down on the stuck reading",
                lowest < self.learned_k - 0.1,
                f"lowest {lowest:.3f} K from {self.learned_k:g} K",
            ),
            verdict(
                "the cross-check flags it",
                bool(flagged),
                f"room_implausible raised {[_wall(a.ts).isoformat() for a in flagged]}",
            ),
            verdict(
                "room_lost_rollback restores the integrator at the last proof of life",
                bool(rolled)
                and all(
                    abs(float(d.state["integral_k"]) - self._integral_alive(d)) < 1e-9
                    for d in rolled
                ),
                f"{len(rolled)} decisions",
            ),
            verdict(
                f"the restored integrator is within {self.rollback_slack_k:g} K below the "
                f"learned {self.learned_k:g} K",
                bool(restored) and all(floor <= v <= self.learned_k + 1e-9 for v in restored),
                f"restored {min(restored, default=math.nan):.3f}"
                f" to {max(restored, default=math.nan):.3f} K",
            ),
            verdict(
                f"while lost the feedback is the held offset (at most {held:.2f} K)",
                bool(lost) and not off,
                f"{len(lost)} decisions, {len(off)} above",
            ),
            verdict("feedback resumes after the sensor reports", bool(back), f"{len(back)}"),
        ]

    def _integral_alive(self, rolled: Seen) -> float:
        """Return the integrator of the last decision at or before the last proof of life.

        The proof of life may follow the stuck start by a report, so the integrator then
        can already differ from :attr:`learned_k` by that report's wind-down.
        """
        alive_at = rolled.ts - float(rolled.state["room_alive_s"])
        before = [d for d in self.decisions if d.ts <= alive_at + 1e-6]
        return float(before[-1].state["integral_k"]) if before else self.learned_k


DRILLS: Final[dict[str, Callable[[], Drill]]] = {
    "defrost_hold": DefrostHold,
    "manual_override": ManualOverride,
    "latched_hold": LatchedHold,
    "go_live_restore": GoLiveRestore,
    "stuck_warm_flagged": StuckWarmFlagged,
}
