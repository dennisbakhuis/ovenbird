"""Faults on the command path: foreign writer, lost command, setpoint above maximum.

The family also holds the HeishaMon envelope rule's correction.

``envelope_correction`` declares the HeishaMon envelope rule installed for its window
and emulates the rule on the simulated board (the rule is stateless, so the emulation
is a few lines: every 30 s it compares the register with the envelope band at the
published ``Outside_Temp`` and writes the envelope curve value when it lies outside).
The outside sensor then reads warmer (or colder) right after a control tick, so
ovenbird's verified setpoint lies outside the band and the rule corrects it before the
next decision.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from ovenbird.configstore import Actor
from ovenbird.control.alarms import AlarmCode
from ovenbird.history.journal import AlarmRow
from ovenbird_core.control import IntentKind

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.scenario import (
    CYCLE_S,
    EPSILON,
    HOUR,
    SLACK_S,
    TICK_CYCLES,
    TICK_S,
    Check,
    Scenario,
    _iso,
    _no_trouble,
    _sent_between,
    verdict,
)

FOREIGN_STEP_K: Final = 3
ABOVE_MAX_K: Final = 5
RULE_PERIOD_S: Final = 30.0
RULE_MARGIN_K: Final = 1.0
MAX_SHIFT_K: Final = 30
OUTSIDE_TOPIC: Final = "Outside_Temp"
ENVELOPE_ALARM: Final = "envelope_correction"


def _register(run: FullRun) -> int:
    registers = run.board.registers
    if run.system.adapter.config.setpoint_register == "setcurves_target_high":
        return registers.curve_target_high
    return registers.direct_setpoint


def _back_in_effect(scenario: Scenario, run: FullRun, expired: float) -> list[Check]:
    cleared = [
        a
        for a in scenario.alarms
        if a.code == "foreign_writer" and a.event == "cleared" and a.ts >= expired
    ]
    register = scenario.notes.get("register_at_clear")
    intent = scenario.notes.get("intent_at_clear")
    return [
        verdict(
            "ovenbird's value is in effect again within 30 min of the expiry",
            bool(cleared) and cleared[0].ts - expired <= 30 * 60,
            f"cleared {[_iso(a.ts) for a in cleared]}",
        ),
        verdict(
            "when foreign_writer clears, the board register holds ovenbird's intent",
            register is not None and register == intent,
            f"register {register}, intent {intent}",
        ),
    ]


def _verified_setpoint(run: FullRun) -> int | None:
    status = run.system.adapter.status(run.clock())
    if status["in_flight"] is not None or status["queued"]:
        return None
    value = status["verified"].get(IntentKind.WATER_SETPOINT.value)
    return value if isinstance(value, int) else None


@dataclass
class ForeignWriter(Scenario):
    """Another client writes the water setpoint (SetCurves) 3 K away from ovenbird's value.

    The write is repeated when ovenbird's own write, in flight at the same moment,
    replaced it before the adapter could read it back.
    """

    name: str = "foreign_writer"
    window_s: float = 3 * HOUR
    max_wait_s: float = HOUR
    written_at: float | None = None

    def _alarm(self, row: AlarmRow) -> None:
        super()._alarm(row)
        run = self.run
        cleared = row.code == "foreign_writer" and row.event == "cleared"
        if run is not None and cleared and self._inside(row.ts):
            self.notes.setdefault("register_at_clear", _register(run))
            self.notes.setdefault("intent_at_clear", run.system.loop.desired_setpoint)

    def plan(self, run: FullRun) -> None:
        """Write as soon as ovenbird has a verified setpoint and nothing in flight."""
        self._try(run, self.start)

    def _try(self, run: FullRun, t: float) -> None:
        if self.written_at is not None:
            self._overwritten(run, t)
            return
        adapter = run.system.adapter
        status = adapter.status(run.clock())
        verified = status["verified"].get(IntentKind.WATER_SETPOINT.value)
        if verified is None or status["in_flight"] is not None or status["queued"]:
            if t - self.start < self.max_wait_s:
                self.at(t - self.start + TICK_S / 12, lambda r, tt: self._try(r, tt))
            return
        low, high = adapter.config.setpoint_range
        value = (
            verified + FOREIGN_STEP_K
            if verified + FOREIGN_STEP_K <= high
            else verified - FOREIGN_STEP_K
        )
        value = min(max(value, low), high)
        base = run.board.config.base
        payload = json.dumps({"zone1": {"heat": {"target": {"high": value}}}})
        run.board.receive(f"{base}/commands/SetCurves", payload)
        self.written_at = t
        self.notes["ovenbird_value"] = verified
        self.notes["foreign_value"] = value
        self.notes["written_at"] = _iso(t)
        self.at(t - self.start + TICK_S / 12, lambda r, tt: self._try(r, tt))

    def _overwritten(self, run: FullRun, t: float) -> None:
        """Write again when ovenbird's own write replaced the value before it was read back.

        A foreign write that lands while ovenbird's own write is in flight is overwritten
        (the last writer wins) and never seen; the scenario then needs a new write.
        """
        written = self.written_at
        if written is None or self.raised("foreign_writer", written):
            return
        register = _register(run)
        if register not in (self.notes["foreign_value"], self.notes["ovenbird_value"]):
            self.notes["overwritten"] = int(self.notes.get("overwritten", 0)) + 1
            self.written_at = None
            self._try(run, t)
        elif t - written < SLACK_S:
            self.at(t - self.start + TICK_S / 12, lambda r, tt: self._try(r, tt))

    def checks(self, run: FullRun) -> list[Check]:
        """Alarm and hold, nothing sent while held, expiry, ovenbird's value back."""
        if self.written_at is None:
            return [Check("foreign write injected", "fail", "no verified setpoint to overwrite")]
        t0 = self.written_at
        raised = self.raised("foreign_writer", t0)
        starts = [a for a in self.alarms if a.code == "command_hold" and a.event == "started"]
        expiries = [a for a in self.alarms if a.code == "command_hold" and a.event == "expired"]
        hold_s = run.system.adapter.config.hold_s
        checks = [
            verdict(
                "foreign_writer raised within 2 min",
                bool(raised) and raised[0].ts - t0 <= SLACK_S,
                f"{[_iso(a.ts) for a in raised]}",
            ),
            verdict(
                "a foreign-writer hold starts",
                bool(starts) and "foreign writer" in starts[0].message,
                starts[0].message if starts else "none",
            ),
        ]
        if starts:
            hold_from = starts[0].ts
            hold_to = expiries[0].ts if expiries else self.end
            during = [
                c
                for c in self.commands
                if c.status == "sent" and hold_from <= c.ts < hold_to and "safety" not in c.detail
            ]
            checks.append(
                verdict("nothing published during the hold", not during, f"{len(during)} sent")
            )
            checks.append(
                verdict(
                    f"the hold expires after {hold_s / 60:.0f} min",
                    bool(expiries) and abs(expiries[0].ts - hold_from - hold_s) <= SLACK_S,
                    f"expired {[_iso(a.ts) for a in expiries]}",
                )
            )
            if expiries:
                checks.extend(_back_in_effect(self, run, expiries[0].ts))
        return checks


@dataclass
class CommandLost(Scenario):
    """Commands are lost on the way to the pump until one fails verification.

    The pump never sees ovenbird's commands (HeishaMon drops them); the adapter
    retries, gives up, raises ``verification_failed`` and holds. Commands reach the
    pump again right after the failure. The loss starts with the first command the
    controller queues. On a steady night (one long compressor run) it may queue none
    for many hours, so after :attr:`nudge_after_s` an operator raises the comfort
    temperature by :attr:`nudge_k` through the configuration store, which makes the
    controller ask for a higher setpoint; the change is reverted once commands reach
    the pump again.
    """

    name: str = "command_lost"
    window_s: float = 8 * HOUR
    nudge_after_s: float = HOUR
    nudge_k: float = 1.0
    max_wait_s: float = 3 * HOUR
    max_loss_s: float = 2 * HOUR
    lost_from: float | None = None
    restored_at: float | None = None
    nudged: bool = False

    def plan(self, run: FullRun) -> None:
        """Wait for a queued command, then lose commands; watch for the failure."""
        self.at(0.0, self._arm)

    def _arm(self, run: FullRun, t: float) -> None:
        status = run.system.adapter.status(run.clock())
        if status["queued"] and status["in_flight"] is None:
            self._lose(run, t)
            return
        if not self.nudged and t - self.start >= self.nudge_after_s:
            self._nudge(run, t)
        if t - self.start < self.max_wait_s:
            self.at(t - self.start + CYCLE_S, self._arm)

    def _configure(self, run: FullRun, comfort: float | None, comment: str) -> None:
        manager = run.system.config
        changes = {"control_comfort_c": comfort}
        warnings = [w.code for w in manager.validate(changes).warnings]
        manager.apply(
            manager.version or 0, changes, Actor("harness"), comment=comment, acknowledge=warnings
        )

    def _nudge(self, run: FullRun, t: float) -> None:
        comfort = round(run.system.config.settings.control_comfort_c + self.nudge_k, 1)
        self._configure(run, comfort, "harness command_lost nudge")
        self.nudged = True
        self.notes["nudged_at"] = _iso(t)
        self.notes["nudged_comfort_c"] = comfort

    def _lose(self, run: FullRun, t: float) -> None:
        run.commands_lost = True
        self.lost_from = t
        self.notes["lost_from"] = _iso(t)
        self.notes["dropped_before"] = run.commands_dropped
        self._watch(run, t)

    def _watch(self, run: FullRun, t: float) -> None:
        failed = any(c.status == "failed" for c in self.commands)
        if failed or t - (self.lost_from or self.start) >= self.max_loss_s:
            run.commands_lost = False
            self.restored_at = t
            self.notes["commands_lost"] = run.commands_dropped - self.notes["dropped_before"]
            if self.nudged:
                self._configure(run, None, "harness command_lost nudge reverted")
            return
        self.at(t - self.start + CYCLE_S, self._watch)

    def checks(self, run: FullRun) -> list[Check]:
        """Retries, failure, alarm, hold, nothing sent during the hold, recovery."""
        retries = [c for c in self.commands if c.status == "retry"]
        failed = [c for c in self.commands if c.status == "failed"]
        self.notes["retries"] = len(retries)
        self.notes["failed"] = len(failed)
        checks = [
            verdict(
                "commands were lost",
                int(self.notes.get("commands_lost", 0)) > 0,
                f"{self.notes.get('commands_lost', 0)} publishes lost"
                if self.lost_from is not None
                else f"no command queued within {self.max_wait_s / HOUR:.0f} h",
            ),
            verdict(
                "the adapter retried before giving up",
                bool(retries) and bool(failed) and retries[0].ts < failed[0].ts,
                f"{len(retries)} retries, {len(failed)} failed",
            ),
        ]
        if not failed:
            return checks
        t0 = failed[0].ts
        raised = self.raised("verification_failed", t0 - EPSILON)
        starts = [a for a in self.alarms if a.code == "command_hold" and a.event == "started"]
        expiries = [a for a in self.alarms if a.code == "command_hold" and a.event == "expired"]
        hold_to = expiries[0].ts if expiries else self.end
        cleared = [
            a
            for a in self.alarms
            if a.code == "verification_failed" and a.event == "cleared" and a.ts >= hold_to
        ]
        checks += [
            verdict(
                "verification_failed raised with the failure",
                bool(raised) and raised[0].ts - t0 <= SLACK_S,
                f"{[_iso(a.ts) for a in raised]}",
            ),
            verdict(
                "a verification hold starts",
                bool(starts) and "verification failed" in starts[0].message,
                starts[0].message if starts else "none",
            ),
            verdict(
                "nothing published during the hold",
                bool(starts) and not _sent_between(self, starts[0].ts, hold_to),
                f"{len(_sent_between(self, starts[0].ts, hold_to)) if starts else 0} sent",
            ),
            verdict(
                "the alarm clears once ovenbird's value is in effect after the hold",
                bool(expiries) and bool(cleared) and cleared[0].ts - hold_to <= 30 * 60,
                f"hold expired {[_iso(a.ts) for a in expiries]}, cleared "
                f"{[_iso(a.ts) for a in cleared]}",
            ),
        ]
        return checks


@dataclass
class SetpointAboveMax(Scenario):
    """Another client writes a water setpoint 5 K above the maximum supply."""

    name: str = "setpoint_above_max"
    window_s: float = 3 * HOUR
    max_wait_s: float = HOUR
    written_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Write once ovenbird has a verified setpoint and nothing in flight."""
        self._try(run, self.start)

    def _try(self, run: FullRun, t: float) -> None:
        if self.written_at is not None:
            return
        verified = _verified_setpoint(run)
        if verified is None:
            if t - self.start < self.max_wait_s:
                self.at(t - self.start + TICK_S / 12, lambda r, tt: self._try(r, tt))
            return
        value = run.system.adapter.config.setpoint_range[1] + ABOVE_MAX_K
        payload = json.dumps({"zone1": {"heat": {"target": {"high": value}}}})
        run.board.receive(f"{run.board.config.base}/commands/SetCurves", payload)
        self.written_at = t
        self.notes["ovenbird_value"] = verified
        self.notes["foreign_value"] = value

    def _alarm(self, row: AlarmRow) -> None:
        super()._alarm(row)
        run = self.run
        cleared = row.code == "foreign_writer" and row.event == "cleared"
        if run is not None and cleared and self._inside(row.ts):
            self.notes.setdefault("register_at_clear", _register(run))
            self.notes.setdefault("intent_at_clear", run.system.loop.desired_setpoint)

    def _cycle(self, run: FullRun, t: float) -> None:
        super()._cycle(run, t)
        high = run.system.adapter.config.setpoint_range[1]
        written = self.written_at
        if (
            written is not None
            and "back_within_limit" not in self.notes
            and t > written + CYCLE_S
            and _register(run) <= high
        ):
            self.notes["back_within_limit"] = t - written

    def checks(self, run: FullRun) -> list[Check]:
        """Safety correction, register back in range, alarms raised and cleared."""
        if self.written_at is None:
            return [Check("write above the maximum injected", "fail", "no verified setpoint")]
        t0 = self.written_at
        queued = [
            c
            for c in self.commands
            if c.status == "queued" and c.detail.startswith("safety correction")
        ]
        above = self.raised("setpoint_above_max", t0)
        above_cleared = [
            a for a in self.alarms if a.code == "setpoint_above_max" and a.event == "cleared"
        ]
        foreign = self.raised("foreign_writer", t0)
        expiries = [a for a in self.alarms if a.code == "command_hold" and a.event == "expired"]
        back = self.notes.get("back_within_limit")
        self.notes["safety_corrections"] = len(queued)
        checks = [
            verdict(
                "a safety correction is published within 2 min",
                bool(queued) and queued[0].ts - t0 <= SLACK_S,
                f"{[_iso(c.ts) for c in queued]}: {queued[0].detail if queued else ''}",
            ),
            verdict(
                "the register is back within the limit within 3 min",
                back is not None and float(back) <= 3 * 60,
                f"after {back} s",
            ),
            verdict(
                "setpoint_above_max raised and cleared",
                bool(above) and any(a.ts > above[0].ts for a in above_cleared),
                f"raised {[_iso(a.ts) for a in above]}, cleared "
                f"{[_iso(a.ts) for a in above_cleared]}",
            ),
            verdict(
                "foreign_writer raised",
                bool(foreign) and foreign[0].ts - t0 <= SLACK_S,
                f"{[_iso(a.ts) for a in foreign]}",
            ),
        ]
        if expiries:
            checks.extend(_back_in_effect(self, run, expiries[0].ts))
        else:
            checks.append(verdict("the foreign-writer hold expires", False, "no expiry"))
        return checks


@dataclass
class EnvelopeCorrection(Scenario):
    """The HeishaMon envelope rule corrects ovenbird's setpoint after an outside-sensor jump."""

    name: str = "envelope_correction"
    window_s: float = 1.5 * HOUR
    max_wait_s: float = HOUR
    shifted_s: float = 45 * 60.0
    shifted_at: float | None = None
    rule_wrote_at: float = -math.inf
    corrected_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Declare the rule, shift the outside sensor a control tick later, undo both."""
        self._declare(run, installed=True)
        self._try(run, self.start)
        self.at(self.window_s, lambda r, t: self._declare(r, installed=False))

    @staticmethod
    def _declare(run: FullRun, *, installed: bool) -> None:
        adapter = run.system.adapter
        safety = run.system.loop.controller.config.safety
        adapter.config = replace(adapter.config, envelope_rule=safety if installed else None)
        watch = run.system.loop.envelope
        if watch is not None:
            watch.installed = installed
        if not installed:
            run.board.overrides.pop(OUTSIDE_TOPIC, None)

    def _outside(self, run: FullRun) -> float | None:
        published = run.board.overrides.get(OUTSIDE_TOPIC)
        if published is not None:
            return float(published)
        observation = run.board.observation
        return None if observation is None else float(observation.outside_temp)

    def _shift(self, run: FullRun, verified: int, outside: float) -> float | None:
        safety = run.system.loop.controller.config.safety
        for step in range(1, MAX_SHIFT_K + 1):
            for shifted in (outside + step, outside - step):
                bounds = safety.bounds(shifted)
                clear = (
                    verified > bounds.high + RULE_MARGIN_K or verified < bounds.low - RULE_MARGIN_K
                )
                if clear and verified not in safety.fallback_values(shifted):
                    return shifted
        return None

    def _try(self, run: FullRun, t: float) -> None:
        if self.shifted_at is not None:
            return
        verified = _verified_setpoint(run)
        outside = self._outside(run)
        settled = t - self.start >= TICK_S
        if not settled or verified is None or outside is None or run.cycle % TICK_CYCLES != 0:
            if t - self.start < self.max_wait_s:
                self.at(t - self.start + CYCLE_S, lambda r, tt: self._try(r, tt))
            return
        shifted = self._shift(run, verified, outside)
        if shifted is None:
            self.notes["no_shift"] = f"no outside temperature puts {verified} outside the band"
            return
        run.board.overrides[OUTSIDE_TOPIC] = str(int(shifted))
        self.shifted_at = t
        self.notes["ovenbird_value"] = verified
        self.notes["outside_c"] = outside
        self.notes["shifted_outside_c"] = shifted
        self.at(t - self.start + self.shifted_s, lambda r, tt: self._unshift(r))

    @staticmethod
    def _unshift(run: FullRun) -> None:
        run.board.overrides.pop(OUTSIDE_TOPIC, None)

    def _cycle(self, run: FullRun, t: float) -> None:
        super()._cycle(run, t)
        if not self._inside(t) or self.shifted_at is None:
            return
        self._rule(run, t)
        if self.corrected_at is not None and "in_effect_after" not in self.notes:
            desired = run.system.loop.desired_setpoint
            if desired is not None and _register(run) == desired:
                self.notes["in_effect_after"] = t - self.corrected_at

    def _rule(self, run: FullRun, t: float) -> None:
        if t - self.rule_wrote_at < RULE_PERIOD_S:
            return
        outside = self._outside(run)
        if outside is None:
            return
        safety = run.system.loop.controller.config.safety
        bounds = safety.bounds(outside)
        register = _register(run)
        if bounds.low <= register <= bounds.high:
            return
        value = round(safety.fallback_setpoint(outside))
        payload = json.dumps({"zone1": {"heat": {"target": {"high": value}}}})
        run.board.receive(f"{run.board.config.base}/commands/SetCurves", payload)
        self.rule_wrote_at = t
        self.notes["rule_writes"] = int(self.notes.get("rule_writes", 0)) + 1

    def _alarm(self, row: AlarmRow) -> None:
        super()._alarm(row)
        if row.code == ENVELOPE_ALARM and self._inside(row.ts) and self.corrected_at is None:
            self.corrected_at = row.ts

    def checks(self, run: FullRun) -> list[Check]:
        """Recognised and adopted, no foreign writer, ovenbird's value back, evidence kept."""
        if self.shifted_at is None:
            reason = self.notes.get("no_shift", "no verified setpoint after a control tick")
            return [Check("outside sensor shifted", "fail", str(reason))]
        t0 = self.shifted_at
        recognised = [a for a in self.alarms if a.code == ENVELOPE_ALARM and a.ts >= t0]
        mismatch = self.raised(AlarmCode.ENVELOPE_MISMATCH.value, t0)
        after = self.notes.get("in_effect_after")
        watch = run.system.loop.envelope
        evidence = watch.evidence()["count"] if watch is not None else 0
        adopted = run.system.adapter.counters.envelope_corrections
        self.notes["recognised"] = len(recognised)
        self.notes["evidence"] = evidence
        return [
            verdict(
                "the rule's correction is recognised within 2 min",
                bool(recognised) and recognised[0].ts - t0 <= SLACK_S,
                f"{[_iso(a.ts) for a in recognised]}: "
                f"{recognised[0].message if recognised else ''}",
            ),
            _no_trouble(self, self.start),
            verdict("no envelope_mismatch", not mismatch, f"{[_iso(a.ts) for a in mismatch]}"),
            verdict(
                "ovenbird's intent is in effect within 5 min of the correction",
                after is not None and float(after) <= 5 * 60,
                f"after {after} s",
            ),
            verdict(
                "the correction is adopted and kept as evidence of the rule",
                adopted >= 1 and evidence >= 1,
                f"adopted {adopted}, evidence {evidence}",
            ),
        ]
