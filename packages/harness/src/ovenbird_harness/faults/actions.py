"""Operator actions and restarts: an ovenbird restart, a configuration, a pump setting.

``config_apply`` is not a fault but an operator action: a new configuration (comfort
and one curve point) is applied through the configuration store mid-run and reverted
later, both through :meth:`ovenbird.configstore.ConfigManager.apply`.
``pump_setting_write`` is one as well: an admin changes the heating delta-T through
the pump settings service (:class:`ovenbird.pump.settings.PumpSettings`, what
``POST api/v1/pump/settings/heat_delta`` calls), tries again during a defrost (refused)
and restores the original value afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ovenbird.configstore import Actor
from ovenbird.control.adapter import OPERATOR_PREFIX, SettingRefusedError
from ovenbird.control.persist import STATE_KEY
from ovenbird.history.journal import CommandRow, read_state
from ovenbird_core import PUMP_SETTINGS, HeishaSignal, PumpSetting
from ovenbird_core.control import HeatingCurve

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
    _resumes,
    verdict,
)

RESTART_BURST_S: Final = 600.0
HARNESS_ADMIN: Final = "harness admin"
DEFROST_TOPIC: Final = "Defrosting_State"


@dataclass
class OvenbirdRestart(Scenario):
    """ovenbird stops for 5 min and starts again on the same data directory."""

    name: str = "ovenbird_restart"
    window_s: float = 3 * HOUR
    down_s: float = 300.0

    def plan(self, run: FullRun) -> None:
        """Stop, then start with persisted state."""
        self.at(0.0, self._stop)
        self.at(self.down_s, self._start)

    def _stop(self, run: FullRun, t: float) -> None:
        status = run.system.adapter.status(run.clock())
        self.notes["budget_used_before"] = status["budget"]["used"]
        self.notes["budget_day_before"] = status["budget"]["day"]
        self.notes["verified_before"] = dict(status["verified"])
        run.stop_service()
        row = read_state(run.settings.history_path, STATE_KEY)
        state = json.loads(row.value)["state"] if row is not None else {}
        self.notes["saved_integral_k"] = state.get("integral_k")
        self.notes["saved_setpoint"] = state.get("setpoint")

    def _start(self, run: FullRun, t: float) -> None:
        run.start_service()
        loop = run.system.loop
        self.notes["restored"] = loop.restored
        self.notes["restored_integral_k"] = loop.state.integral_k
        self.notes["restored_setpoint"] = loop.state.setpoint
        budget = run.system.adapter.status(run.clock())["budget"]
        self.notes["budget_used_after"] = budget["used"]
        self.notes["budget_day_after"] = budget["day"]

    def _resent(self, back: float) -> list[CommandRow]:
        """Commands sent within 10 min of the restart with a value already verified.

        A restart must not re-send what the pump already holds; changes the
        controller asks for (a compressor start, the ramp, the curve) are not a burst.
        """
        verified = {str(k): v for k, v in dict(self.notes.get("verified_before") or {}).items()}
        resent = []
        for command in self.commands:
            if command.status == "verified":
                verified[command.kind] = command.value
            elif (
                command.status == "sent"
                and back <= command.ts < back + RESTART_BURST_S
                and command.attempt == 1
                and verified.get(command.kind) == command.value
            ):
                resent.append(command)
        return resent

    def checks(self, run: FullRun) -> list[Check]:
        """State and budget restored, no trouble, nothing re-sent after the restart."""
        back = self.start + self.down_s
        day_before = self.notes.get("budget_day_before")
        same_day = day_before is not None and day_before == self.notes.get("budget_day_after")
        expected = self.notes.get("budget_used_before") if same_day else 0
        sent = [
            c for c in self.commands if c.status == "sent" and back <= c.ts < back + RESTART_BURST_S
        ]
        resent = self._resent(back)
        self.notes["sent_after_restart"] = len(sent)
        return [
            verdict("controller state restored", bool(self.notes.get("restored"))),
            verdict(
                "integrator and setpoint continue from the saved state",
                self.notes.get("restored_integral_k") == self.notes.get("saved_integral_k")
                and self.notes.get("restored_setpoint") == self.notes.get("saved_setpoint"),
                f"integral {self.notes.get('saved_integral_k')} → "
                f"{self.notes.get('restored_integral_k')}, setpoint "
                f"{self.notes.get('saved_setpoint')} → {self.notes.get('restored_setpoint')}",
            ),
            verdict(
                "the daily write budget is restored from the journal",
                self.notes.get("budget_used_after") == expected,
                f"{self.notes.get('budget_used_before')} on {day_before} before, "
                f"{self.notes.get('budget_used_after')} on "
                f"{self.notes.get('budget_day_after')} after (expected {expected})",
            ),
            _resumes(self, back, SLACK_S + TICK_S),
            _no_trouble(self, back),
            verdict(
                "no value the pump already holds is re-sent after the restart",
                not resent,
                f"{len(resent)} re-sent of {len(sent)} sent within "
                f"{RESTART_BURST_S / 60:.0f} min"
                + (f" (first {resent[0].kind}={resent[0].value})" if resent else ""),
            ),
        ]


@dataclass
class ConfigApply(Scenario):
    """An operator applies comfort +0.3 K and the 0 °C curve point +1 K, and reverts later."""

    name: str = "config_apply"
    window_s: float = 8 * HOUR
    revert_s: float = 6 * HOUR
    comfort_step_k: float = 0.3
    curve_step_k: float = 1.0
    version: int | None = None
    reverted: int | None = None
    applied_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Apply at the start, revert after :attr:`revert_s`."""
        self.at(0.0, self._apply)
        self.at(self.revert_s, self._revert)

    def _apply(self, run: FullRun, t: float) -> None:
        manager = run.system.config
        settings = manager.settings
        points = [[p.outside_c, p.water_c] for p in settings.controller_config().curve.points]
        index = min(range(len(points)), key=lambda i: abs(points[i][0]))
        points[index][1] += self.curve_step_k
        comfort = round(settings.control_comfort_c + self.comfort_step_k, 1)
        changes = {"control_comfort_c": comfort, "control_curve": points}
        warnings = [w.code for w in manager.validate(changes).warnings]
        loop = run.system.loop
        self.notes["before"] = {
            "setpoint": loop.state.setpoint,
            "last_change_at": loop.state.last_change_at,
            "integral_k": loop.state.integral_k,
        }
        result = manager.apply(
            manager.version or 0,
            changes,
            Actor("harness"),
            comment="harness config_apply",
            acknowledge=warnings,
        )
        self.version = int(result["version"])
        self.applied_at = t
        self.notes["version"] = self.version
        self.notes["comfort_c"] = comfort
        self.notes["curve"] = points
        self.notes["warnings"] = warnings

    def _revert(self, run: FullRun, t: float) -> None:
        manager = run.system.config
        changes = {"control_comfort_c": None, "control_curve": None}
        warnings = [w.code for w in manager.validate(changes).warnings]
        result = manager.apply(
            manager.version or 0,
            changes,
            Actor("harness"),
            comment="harness config_apply revert",
            acknowledge=warnings,
        )
        self.reverted = int(result["version"])
        self.notes["reverted_version"] = self.reverted
        events = manager.store.audit_events(self.start - HOUR, t + HOUR, 100)
        self.notes["audit_applies"] = sum(1 for e in events if e.action == "config_apply")

    def checks(self, run: FullRun) -> list[Check]:
        """Next-tick swap, version on every decision, state carried, new terms, audit."""
        if self.version is None or self.applied_at is None:
            return [Check("configuration applied", "fail", "the apply did not happen")]
        applied = self.applied_at
        revert = self.start + self.revert_s
        first = next((d for d in self.decisions if d.ts >= applied - EPSILON), None)
        window = self.between(applied - 2 * EPSILON, revert)
        under = [d for d in window if d.config_version == self.version]
        others = [d for d in window if d.config_version != self.version]
        comfort = float(self.notes["comfort_c"])
        curve = HeatingCurve.of(*(tuple(p) for p in self.notes["curve"]))
        targets = [
            float(d.state["room_target_c"])
            for d in under
            if d.state.get("room_target_c") is not None
        ]
        wrong_target = [v for v in targets if abs(v - comfort) > EPSILON]
        curve_bad = [
            d
            for d in under
            if d.curve is not None
            and d.state.get("outside_filtered_c") is not None
            and abs(d.curve - curve.water(float(d.state["outside_filtered_c"]))) > 1e-6
        ]
        before = self.notes["before"]
        carried = first is not None and (
            first.setpoint != before["setpoint"]
            or first.state.get("last_change_at") == before["last_change_at"]
        )
        audit = int(self.notes.get("audit_applies", 0))
        reverted_ok = self.reverted is not None and any(
            d.config_version == self.reverted for d in self.decisions if d.ts > revert
        )
        return [
            verdict(
                "the new configuration is in effect at the next tick",
                first is not None
                and first.config_version == self.version
                and first.ts - applied <= TICK_S + EPSILON,
                "no decision"
                if first is None
                else f"first decision {first.ts - applied:.0f} s after the apply, "
                f"version {first.config_version}",
            ),
            verdict(
                "every decision until the revert carries the new version",
                bool(under) and not others,
                f"{len(under)} with version {self.version}, {len(others)} others",
            ),
            verdict(
                "the setpoint and its dwell timer carry over the apply",
                carried,
                f"before {before}, first {first.setpoint if first else None} / "
                f"{first.state.get('last_change_at') if first else None}",
            ),
            verdict(
                "the controller uses the new comfort and curve",
                bool(targets) and not wrong_target and not curve_bad,
                f"{len(targets)} room targets ({len(wrong_target)} wrong), "
                f"{len(curve_bad)} curve terms off the new curve",
            ),
            verdict(
                "no setpoint jump on apply (invariant apply_jump)",
                run.checker.counts["apply_jump"] == 0,
                f"{run.checker.counts['apply_jump']} violations",
            ),
            verdict(
                "the apply and the revert are versioned and audited",
                audit == 2 and reverted_ok,
                f"{audit} audit rows, revert version {self.reverted} "
                f"{'in effect' if reverted_ok else 'not seen'}",
            ),
        ]


@dataclass
class PumpSettingWrite(Scenario):
    """An admin writes the heating delta-T, is refused during a defrost and restores it."""

    name: str = "pump_setting_write"
    window_s: float = 8 * HOUR
    max_wait_s: float = HOUR
    max_defrost_wait_s: float = 2 * HOUR
    setting: PumpSetting = PumpSetting.HEAT_DELTA
    original: int | None = None
    target: int | None = None
    written_at: float | None = None
    verified_at: float | None = None
    refused: SettingRefusedError | None = None
    restored_at: float | None = None

    def plan(self, run: FullRun) -> None:
        """Write as soon as no defrost or DHW run blocks it and no command is in flight.

        The scenario checks the direct path; a write that waits behind ovenbird's own
        command is covered by the adapter's tests
        (``test_a_write_behind_ovenbird_s_own_command_waits_and_is_sent_once``).
        """
        self._write(run, self.start)

    def _reported(self, run: FullRun) -> int | None:
        view = run.system.runtime.store.view(PUMP_SETTINGS[self.setting].signal, run.clock())
        if view is None or not view.fresh or type(view.value) is not int:
            return None
        return view.value

    def _request(self, run: FullRun, value: int, expect: int) -> SettingRefusedError | None:
        try:
            result = run.system.pumps.write(
                self.setting.value, {"value": value, "expect": expect}, Actor(HARNESS_ADMIN)
            )
        except SettingRefusedError as exc:
            return exc
        self.notes.setdefault("queued", []).append(result["command"]["status"])
        return None

    def _retry(self, t: float, action: Callable[[FullRun, float], None]) -> None:
        self.at(t - self.start + CYCLE_S, action)

    def _write(self, run: FullRun, t: float) -> None:
        reported = self._reported(run)
        spec = PUMP_SETTINGS[self.setting]
        status = run.system.adapter.status(run.clock())
        busy = status["in_flight"] is not None or bool(status["queued"])
        if reported is None or busy:
            if t - self.start < self.max_wait_s:
                self._retry(t, self._write)
            return
        target = reported + 1 if reported + 1 <= spec.high else reported - 1
        budget = run.system.adapter.status(run.clock())["budget"]
        self.notes["budget_before"] = budget["used"]
        self.notes["budget_day_before"] = budget["day"]
        refused = self._request(run, target, reported)
        if refused is not None:
            self.notes.setdefault("first_refusals", []).append(refused.code)
            if t - self.start < self.max_wait_s:
                self._retry(t, self._write)
            return
        self.original, self.target, self.written_at = reported, target, t
        self.notes["written"] = {"from": reported, "to": target, "at": _iso(t)}
        self._watch(run, t)

    def _command(self, row: CommandRow) -> None:
        super()._command(row)
        run = self.run
        first_sent = (
            row.kind == self.setting.value and row.status == "sent" and row.value == self.target
        )
        if run is not None and first_sent and "budget_after" not in self.notes:
            budget = run.system.adapter.status(run.clock())["budget"]
            self.notes["budget_after"] = budget["used"]
            self.notes["budget_day_after"] = budget["day"]

    def _watch(self, run: FullRun, t: float) -> None:
        verified = [
            c for c in self.commands if c.kind == self.setting.value and c.status == "verified"
        ]
        if verified:
            self.verified_at = verified[0].ts
            self.notes["register_after"] = run.board.registers.heat_delta
            self.notes["audited"] = [
                e.detail
                for e in run.system.config.store.latest_audit("pump_setting")
                if e.detail.get("setting") == self.setting.value
            ]
            self._in_defrost(run, t)
            return
        if t - self.start < self.max_wait_s:
            self._retry(t, self._watch)

    def _in_defrost(self, run: FullRun, t: float) -> None:
        view = run.system.runtime.store.view(HeishaSignal.DEFROSTING_STATE, run.clock())
        defrosting = view is not None and view.fresh and view.value == 1
        if not defrosting:
            if t - self.start < self.max_defrost_wait_s:
                self._retry(t, self._in_defrost)
            else:
                self._report_defrost(run, t)
            return
        self.notes.setdefault("defrost", "plant")
        reported = self._reported(run)
        if reported is None or self.original is None:
            return
        self.refused = self._request(run, self.original, reported)
        self.notes["defrost_attempt_at"] = _iso(t)
        if self.notes["defrost"] == "reported":
            run.board.overrides.pop(DEFROST_TOPIC, None)
        self._restore(run, t)

    def _report_defrost(self, run: FullRun, t: float) -> None:
        """Without a plant defrost in time, let the board report one for a single cycle.

        Only right after a controller tick, outside a plant defrost and a DHW run and
        with nothing queued or in flight, so no decision sees it and no command is
        dropped for it (whether the compressor runs does not matter: on a cold day
        it may run for the rest of the window).
        """
        board = run.board
        status = run.system.adapter.status(run.clock())
        idle = status["in_flight"] is None and not status["queued"]
        quiet = idle and not board.state.defrosting and not board.dhw
        if not quiet or (run.cycle + 1) % TICK_CYCLES != 1:
            if t < self.end - 2 * HOUR:
                self._retry(t, self._report_defrost)
            return
        board.overrides[DEFROST_TOPIC] = "1"
        self.notes["defrost"] = "reported"
        self._retry(t, self._in_defrost)

    def _restore(self, run: FullRun, t: float) -> None:
        reported = self._reported(run)
        if self.original is None or reported is None:
            return
        refused = self._request(run, self.original, reported)
        if refused is None:
            self.restored_at = t
            self.notes["restored_at"] = _iso(t)
            return
        if t < self.end - HOUR:
            self.at(t - self.start + 60.0, self._restore)

    def checks(self, run: FullRun) -> list[Check]:
        """Check verification, journal, audit, budget, the defrost refusal and the restore."""
        if self.written_at is None or self.target is None:
            return [
                Check(
                    "pump setting written",
                    "fail",
                    f"no write accepted ({self.notes.get('first_refusals')})",
                )
            ]
        rows = [c for c in self.commands if c.kind == self.setting.value]
        statuses = [
            *self.notes.get("queued", [])[:1],
            *(c.status for c in rows if c.value == self.target),
        ]
        first: list[str] = []
        for status in statuses:
            if not first or first[-1] != status:
                first.append(status)
        sends = statuses.count("sent")
        queued = statuses.count("queued")
        operator = [c for c in rows if not c.detail.startswith(f"{OPERATOR_PREFIX}{HARNESS_ADMIN}")]
        before, after = self.notes.get("budget_before"), self.notes.get("budget_after")
        same_day = self.notes.get("budget_day_before") == self.notes.get("budget_day_after")
        counted = (before if same_day else 0) if before is not None else None
        audits = list(self.notes.get("audited", []))
        sent_in_defrost = run.checker.counts["pump_setting"]
        refused = self.refused
        restored = [c for c in rows if c.value == self.original and c.status == "verified"]
        return [
            verdict(
                "the write is queued, sent and verified within 2 min",
                first[:3] == ["queued", "sent", "verified"]
                and self.verified_at is not None
                and self.verified_at - self.written_at <= SLACK_S,
                f"{first}, verified {self.notes.get('written')}",
            ),
            verdict(
                "the write is sent once (the request and its journal row may both say queued)",
                sends == 1 and queued <= 2,
                f"{sends} sent, {queued} queued",
            ),
            verdict(
                "the board holds the new value",
                self.notes.get("register_after") == self.target,
                f"register {self.notes.get('register_after')}, wanted {self.target}",
            ),
            verdict(
                "every journal event names the operator",
                bool(rows) and not operator,
                f"{len(rows)} events, {len(operator)} without the operator",
            ),
            verdict(
                "the write counts against the daily budget",
                after is not None and counted is not None and after >= counted + 1,
                f"budget {before} on {self.notes.get('budget_day_before')} → {after} on "
                f"{self.notes.get('budget_day_after')} when sent",
            ),
            verdict(
                "the write is audited",
                any(detail.get("to") == self.target for detail in audits),
                f"{len(audits)} audit rows",
            ),
            verdict(
                "a write during a defrost is refused (409 defrost)",
                refused is not None and (refused.status, refused.code) == (409, "defrost"),
                "no defrost seen"
                if "defrost_attempt_at" not in self.notes
                else f"{None if refused is None else (refused.status, refused.code)}",
            ),
            verdict(
                "the original value is restored and verified",
                bool(restored),
                f"restored {self.notes.get('restored_at')}",
            ),
            verdict(
                "no pump-setting invariant violated (invariant pump_setting)",
                sent_in_defrost == 0,
                f"{sent_in_defrost} violations",
            ),
            _no_trouble(self, self.start),
        ]
