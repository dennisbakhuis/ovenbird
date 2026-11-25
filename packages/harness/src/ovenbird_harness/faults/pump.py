"""Pump states the controller must respect: a mode change and a DHW run."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.scenario import (
    CONTROL,
    CYCLE_S,
    EPSILON,
    HOUR,
    SLACK_S,
    TICK_S,
    Check,
    Scenario,
    _iso,
    _no_trouble,
    _resumes,
    _sent_between,
    verdict,
)


@dataclass
class ModeChange(Scenario):
    """The pump is switched to compensation mode (``Heating_Mode`` 0) for 30 min."""

    name: str = "mode_change"
    window_s: float = 3 * HOUR
    changed_s: float = 1800.0

    def plan(self, run: FullRun) -> None:
        """Switch to compensation mode and back."""

        def compensation(r: FullRun, t: float) -> None:
            r.board.inject("register/heating_mode", "0")

        def direct(r: FullRun, t: float) -> None:
            r.board.inject("register/heating_mode", "1")

        self.at(0.0, compensation)
        self.at(self.changed_s, direct)

    def checks(self, run: FullRun) -> list[Check]:
        """Refuse with mode_mismatch, alarm raised and cleared, nothing sent, resume."""
        back = self.start + self.changed_s
        during = self.between(self.start + SLACK_S, back)
        wrong = [d for d in during if not (d.ladder == "refuse" and d.reason == "mode_mismatch")]
        raised = self.raised("mode_mismatch", self.start)
        cleared = [a for a in self.alarms if a.code == "mode_mismatch" and a.event == "cleared"]
        self.notes["refusals"] = len(during) - len(wrong)
        return [
            verdict(
                "every decision in compensation mode refuses (mode_mismatch)",
                bool(during) and not wrong,
                f"{len(during)} decisions, {len(wrong)} not refusing",
            ),
            verdict(
                "mode_mismatch raised during the change and cleared after it",
                bool(raised) and raised[0].ts < back and any(c.ts >= back for c in cleared),
                f"raised {[_iso(a.ts) for a in raised]}, cleared {[_iso(a.ts) for a in cleared]}",
            ),
            verdict(
                "nothing published in compensation mode",
                not _sent_between(self, self.start + CYCLE_S, back),
                f"{len(_sent_between(self, self.start + CYCLE_S, back))} sent",
            ),
            _resumes(self, back, SLACK_S + TICK_S),
            _no_trouble(self, self.start),
        ]


@dataclass
class DhwRun(Scenario):
    """The pump reports a 45 min DHW run (``ThreeWay_Valve_State`` 1)."""

    name: str = "dhw_run"
    window_s: float = 3 * HOUR
    dhw_s: float = 2700.0

    def plan(self, run: FullRun) -> None:
        """Start and end the DHW run."""

        def start(r: FullRun, t: float) -> None:
            r.board.dhw = True

        def stop(r: FullRun, t: float) -> None:
            r.board.dhw = False

        self.at(0.0, start)
        self.at(self.dhw_s, stop)

    def checks(self, run: FullRun) -> list[Check]:
        """Frozen integrator, no decrease, heat duty, narrated, normal control after."""
        end = self.start + self.dhw_s
        during = [d for d in self.between(self.start, end + EPSILON) if d.dhw]
        controlled = [d for d in during if d.ladder in CONTROL]
        integrals = {round(float(d.state.get("integral_k", 0.0)), 9) for d in controlled}
        drops = [
            (a.setpoint, b.setpoint)
            for a, b in pairwise(controlled)
            if a.setpoint is not None and b.setpoint is not None and b.setpoint < a.setpoint
        ]
        heat = run.settings.control_pump_duty_heat
        low_duty = [d for d in during if d.duty is not None and d.duty < heat]
        silent = [d for d in controlled if "DHW run in progress" not in d.note]
        after = [d for d in self.between(end + SLACK_S, self.end) if d.ladder in CONTROL]
        self.notes["dhw_decisions"] = len(during)
        return [
            verdict(
                "decisions see the DHW run",
                bool(controlled),
                f"{len(during)} decisions, {len(controlled)} controlled",
            ),
            verdict(
                "the integrator is frozen during the DHW run",
                len(integrals) <= 1,
                f"integrator values {sorted(integrals)[:4]}",
            ),
            verdict("no setpoint decrease during the DHW run", not drops, f"{drops[:3]}"),
            verdict(
                f"the pump duty never drops below the heat duty ({heat}) during DHW",
                not low_duty,
                f"{len(low_duty)} decisions below",
            ),
            verdict(
                "every controlled decision names the DHW run",
                not silent,
                f"{len(silent)} without it",
            ),
            verdict(
                "normal control after the DHW run",
                bool(after) and all(not d.dhw for d in after),
                f"{len(after)} decisions after",
            ),
        ]
