"""Stepping recorded decisions again: the shared core of the preview and the replay.

A stored decision holds the inputs the controller used (``inputs_used``) and the state
it returned (``controller_state``). Two steppers feed on those ticks one at a time, so a
caller can stream a long window without holding every record:

- :class:`IdentityStepper` replays each tick with the configuration of its own version
  and compares the recorded setpoint. It re-seeds from the recorded state where the
  version changes (carried over as the apply did) and follows restarts as the service
  does (state re-anchored on the new monotonic axis, or a fresh state when the saved one
  was too old). Ticks of a version without settings are not compared.
- :class:`CandidateStepper` replays every tick with one candidate configuration from the
  recorded state just before the window (open loop: the candidate reacts to what the
  house did under the recorded control).

:class:`Tally` sums what the candidate did (setpoint changes, ladder levels, binding
constraints, safety clamps, limited room feedback).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from ovenbird.config import Settings
from ovenbird.history.journal import DecisionRow
from ovenbird_core.control import (
    DecisionRecord,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    PlanSlice,
    clock_offset,
    replay_inputs,
    shift_state,
    state_from_flat,
)
from ovenbird_core.control import (
    recorded_model_plan as core_recorded_model_plan,
)
from ovenbird_core.control.ovenbird import carry_state
from ovenbird_core.control.safety import Bound

DAY_S: Final = 86_400.0
MODEL_SLICE_S: Final = 900.0
RESTART_TOLERANCE_S: Final = 1.0
EPSILON: Final = 1e-9
SAFETY_BINDINGS: Final = frozenset(bound.value for bound in Bound)

type ConfigOf = Callable[[int | None], OvenbirdConfig | None]
type SettingsOf = Callable[[int | None], Settings | None]


@dataclass(frozen=True, slots=True)
class Tick:
    """One recorded tick ready for replay.

    Parameters
    ----------
    ts
        Wall-clock unix seconds.
    record
        The decision record.
    version
        Configuration version it ran with.
    """

    ts: float
    record: DecisionRecord
    version: int | None


def parse_row(row: DecisionRow) -> Tick | None:
    """Parse one stored decision; ``None`` when its record cannot be read."""
    try:
        record = DecisionRecord.from_json_dict(json.loads(row.record))
    except ValueError, TypeError, KeyError:
        return None
    return Tick(row.ts, record, row.config_version)


def parse_rows(rows: Sequence[DecisionRow]) -> tuple[list[Tick], int]:
    """Parse stored decisions; returns the ticks and the number of unreadable rows."""
    ticks: list[Tick] = []
    skipped = 0
    for row in rows:
        tick = parse_row(row)
        if tick is None:
            skipped += 1
            continue
        ticks.append(tick)
    return ticks, skipped


def continue_state(
    state: OvenbirdState, previous: DecisionRecord, record: DecisionRecord, max_age_s: float
) -> OvenbirdState:
    """Move ``state`` from ``previous``'s clock axis to ``record``'s (a restart in between)."""
    delta = clock_offset(previous.at) - clock_offset(record.at)
    if abs(delta) <= RESTART_TOLERANCE_S:
        return state
    gap = (record.at.wall - previous.at.wall).total_seconds()
    if gap > max_age_s or gap < 0:
        return OvenbirdState()
    return shift_state(state, delta)


def seed_state(seed: Tick | None, target: OvenbirdConfig, config_of: ConfigOf) -> OvenbirdState:
    """Return the recorded state of ``seed`` carried over to ``target`` (fresh without one)."""
    if seed is None:
        return OvenbirdState()
    state = state_from_flat(seed.record.controller_state)
    old = config_of(seed.version)
    if old is not None:
        state = carry_state(state, old, target)
    return state


def recorded_model_plan(record: DecisionRecord) -> PlanSlice | None:
    """Return the model plan slice a decision was made with, rebuilt from its record.

    Delegates to the controller core, which rebuilds a room-offset or a water-offset
    slice valid for that tick alone; ``None`` for a record made without a model slice.
    """
    return core_recorded_model_plan(record)


def step_tick(
    controller: OvenbirdController,
    state: OvenbirdState,
    record: DecisionRecord,
    settings: Settings,
) -> tuple[OvenbirdState, DecisionRecord]:
    """Step ``controller`` once on the inputs rebuilt from ``record``.

    A tick that was given a model plan slice gets it again (:func:`recorded_model_plan`),
    so replaying with the recorded configuration reproduces the recorded setpoint.
    """
    inputs = replay_inputs(
        record,
        room_signal=settings.control_room_signal,
        room_profile=controller.config.room,
    )
    plan = recorded_model_plan(record)
    if plan is not None:
        inputs = replace(inputs, plan=plan)
    result = controller.step(state, inputs)
    return result.state, result.decision


@dataclass(frozen=True, slots=True)
class VersionIdentity:
    """Identity outcome of one configuration version.

    Parameters
    ----------
    version
        The version (``None``: ticks from before the configuration store).
    ticks
        Ticks compared.
    mismatches
        Ticks whose replayed setpoint differs.
    first
        Unix time of the first mismatch.
    """

    version: int | None
    ticks: int
    mismatches: int
    first: float | None


@dataclass(frozen=True, slots=True)
class Identity:
    """Outcome of the identity check.

    Parameters
    ----------
    ok
        Every compared tick reproduced its recorded setpoint.
    ticks
        Ticks compared.
    mismatches
        Ticks whose replayed setpoint differs.
    first
        Unix time of the first mismatch.
    versions
        The same per version, in the order first met.
    unknown
        Ticks not compared (a version without settings, or not replayable).
    """

    ok: bool
    ticks: int
    mismatches: int
    first: float | None
    versions: tuple[VersionIdentity, ...] = ()
    unknown: int = 0


@dataclass(slots=True)
class _VersionCount:
    ticks: int = 0
    mismatches: int = 0
    first: float | None = None


class IdentityStepper:
    """Replays each tick with its own version's configuration and compares the setpoint.

    Parameters
    ----------
    seed
        The tick before the window (its state starts the replay).
    settings_of
        Settings of a version (``None``: not compared).
    config_of
        Controller configuration a version ran with (``None`` when unknown).
    """

    def __init__(self, seed: Tick | None, settings_of: SettingsOf, config_of: ConfigOf) -> None:
        self._settings_of = settings_of
        self._config_of = config_of
        self._known: dict[int | None, tuple[Settings, OvenbirdController] | None] = {}
        self._state: OvenbirdState | None = None
        self._version: int | None = None
        self._previous = seed
        self._counts: dict[int | None, _VersionCount] = {}
        self._unknown = 0

    def _of(self, version: int | None) -> tuple[Settings, OvenbirdController] | None:
        if version not in self._known:
            settings = self._settings_of(version)
            self._known[version] = (
                None
                if settings is None
                else (settings, OvenbirdController(settings.controller_config()))
            )
        return self._known[version]

    def feed(self, tick: Tick) -> bool | None:
        """Replay ``tick``; ``True`` when it reproduced its setpoint, ``None`` when not compared."""
        found = self._of(tick.version)
        if found is None:
            self._state = None
            self._previous = tick
            self._unknown += 1
            return None
        settings, controller = found
        state = self._state
        if state is None or tick.version != self._version:
            state = seed_state(self._previous, controller.config, self._config_of)
        if self._previous is not None:
            state = continue_state(
                state, self._previous.record, tick.record, settings.control_state_max_age_s
            )
        try:
            state, decision = step_tick(controller, state, tick.record, settings)
        except ValueError, TypeError:
            self._state = None
            self._previous = tick
            self._unknown += 1
            return None
        self._state = state
        self._version = tick.version
        self._previous = tick
        count = self._counts.setdefault(tick.version, _VersionCount())
        count.ticks += 1
        same = decision.setpoint == tick.record.setpoint
        if not same:
            count.mismatches += 1
            count.first = tick.ts if count.first is None else count.first
        return same

    def result(self) -> Identity:
        """Return the outcome so far."""
        ticks = sum(count.ticks for count in self._counts.values())
        mismatches = sum(count.mismatches for count in self._counts.values())
        firsts = [count.first for count in self._counts.values() if count.first is not None]
        return Identity(
            ok=mismatches == 0,
            ticks=ticks,
            mismatches=mismatches,
            first=min(firsts) if firsts else None,
            versions=tuple(
                VersionIdentity(version, count.ticks, count.mismatches, count.first)
                for version, count in self._counts.items()
            ),
            unknown=self._unknown,
        )


class CandidateStepper:
    """Replays every tick with one candidate configuration (open loop).

    Parameters
    ----------
    seed
        The tick before the window (its state starts the replay).
    candidate
        Candidate settings.
    config_of
        Controller configuration a version ran with (``None`` when unknown).
    """

    def __init__(self, seed: Tick | None, candidate: Settings, config_of: ConfigOf) -> None:
        self.candidate = candidate
        self.controller = OvenbirdController(candidate.controller_config())
        self._max_age = candidate.control_state_max_age_s
        self._state = seed_state(seed, self.controller.config, config_of)
        self._previous = seed.record if seed is not None else None
        self.skipped = 0

    def feed(self, tick: Tick) -> DecisionRecord | None:
        """Replay ``tick``; the candidate's decision, or ``None`` when it could not be replayed."""
        record = tick.record
        if self._previous is not None:
            self._state = continue_state(self._state, self._previous, record, self._max_age)
        self._previous = record
        try:
            self._state, decision = step_tick(self.controller, self._state, record, self.candidate)
        except ValueError, TypeError:
            self.skipped += 1
            return None
        return decision


def setpoint_changes(values: Sequence[int | None]) -> int:
    """Count the changes of a setpoint sequence, ignoring ticks without one."""
    count = 0
    last: int | None = None
    for value in values:
        if value is None:
            continue
        if last is not None and value != last:
            count += 1
        last = value
    return count


def shares(counter: Counter[str], total: int) -> dict[str, float]:
    """Return each key's share of ``total`` (three decimals), most common first."""
    if total == 0:
        return {}
    return {key: round(count / total, 3) for key, count in counter.most_common()}


@dataclass(slots=True)
class Tally:
    """What the candidate did over the replayed ticks."""

    recorded: list[int | None] = field(default_factory=list)
    replayed: list[int | None] = field(default_factory=list)
    ladders: Counter[str] = field(default_factory=Counter)
    bindings: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)
    clamped: int = 0
    safety_terms: int = 0
    limited: int = 0
    feedback_terms: int = 0

    def add(self, recorded: DecisionRecord, decision: DecisionRecord) -> None:
        """Count one replayed tick."""
        self.recorded.append(recorded.setpoint)
        self.replayed.append(decision.setpoint)
        self.ladders[decision.ladder.value] += 1
        self.reasons[decision.reason.value] += 1
        if decision.binding is not None:
            self.bindings[decision.binding] += 1
        safety = decision.term("safety")
        if safety is not None:
            self.safety_terms += 1
            if abs(safety.raw - safety.value) > EPSILON or decision.binding in SAFETY_BINDINGS:
                self.clamped += 1
        feedback = decision.term("room_feedback")
        if feedback is not None and decision.pre_round is not None:
            self.feedback_terms += 1
            if abs(feedback.raw - feedback.value) > EPSILON:
                self.limited += 1

    def summary(self, span: tuple[float, float], budget: int) -> dict[str, Any]:
        """Return the preview's summary of the replayed ticks over ``span``."""
        diffs = [
            b - a
            for a, b in zip(self.recorded, self.replayed, strict=True)
            if a is not None and b is not None
        ]
        days = max(span[1] - span[0], 1.0) / DAY_S
        changes = setpoint_changes(self.replayed)
        total = len(self.replayed)
        return {
            "mean_diff_k": round(sum(diffs) / len(diffs), 2) if diffs else 0.0,
            "min_diff_k": min(diffs) if diffs else 0,
            "max_diff_k": max(diffs) if diffs else 0,
            "changes_recorded": setpoint_changes(self.recorded),
            "changes_candidate": changes,
            "writes_per_day": round(changes / days, 1),
            "budget": budget,
            "share_safety_clamped": round(self.clamped / self.safety_terms, 3)
            if self.safety_terms
            else 0.0,
            "share_feedback_limited": round(self.limited / self.feedback_terms, 3)
            if self.feedback_terms
            else 0.0,
            "ladder": shares(self.ladders, total),
            "binding": shares(self.bindings, total),
        }


def limitations(candidate: Settings, reference: Settings) -> list[str]:
    """Return what a replay cannot show for ``candidate`` on ticks recorded under ``reference``."""
    found: list[str] = []
    if candidate.control_room_signal != reference.control_room_signal:
        found.append(
            "the candidate's room signal was not recorded with the decisions; it runs "
            "without that room input"
        )
    if candidate.room_profile() != reference.room_profile():
        found.append("the room value's freshness is as recorded under the active sensor profile")
    return found
