"""Faults of the HeishaMon and broker link: a restart, a broker drop, a stale topic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from climate_manager_capture.heishamon import DUMP_INTERVAL_S
from ovenbird_core.store import HEISHAMON_MAX_AGE_S

if TYPE_CHECKING:
    from ovenbird_harness.fullrun import FullRun

from ovenbird_harness.faults.scenario import (
    HOUR,
    SLACK_S,
    TICK_S,
    Check,
    Scenario,
    _no_trouble,
    _refuses_dead,
    _resumes,
    verdict,
)


@dataclass
class HeishaMonRestart(Scenario):
    """HeishaMon reboots: 5 min off the broker (last will), then uptime 0 and a full dump."""

    name: str = "heishamon_restart"
    window_s: float = 2 * HOUR
    offline_s: float = 300.0
    will_after_s: float = 30.0

    def plan(self, run: FullRun) -> None:
        """Offline, last will, boot."""
        self.at(0.0, lambda r, t: r.heishamon_offline())
        self.at(self.will_after_s, lambda r, t: r.heishamon_will())
        self.at(self.offline_s, lambda r, t: r.heishamon_boot())

    def checks(self, run: FullRun) -> list[Check]:
        """Refuse while silent, resume after the boot, no foreign writer."""
        boot = self.start + self.offline_s
        return [
            _refuses_dead(self, self.start + TICK_S, boot),
            _resumes(self, boot, SLACK_S + TICK_S),
            _no_trouble(self, self.start),
        ]


@dataclass
class BrokerDrop(Scenario):
    """The broker is gone for 10 min (ingest, command link and HeishaMon all cut off)."""

    name: str = "broker_drop"
    window_s: float = 2 * HOUR
    down_s: float = 600.0

    def plan(self, run: FullRun) -> None:
        """Drop and restore the broker."""
        self.at(0.0, lambda r, t: r.drop_broker())
        self.at(self.down_s, lambda r, t: r.restore_broker())

    def checks(self, run: FullRun) -> list[Check]:
        """Nothing published while down, refuse while blind, resume after.

        After the reconnect the broker's retained values are not fresh (they carry no
        time); the unchanged ``main/*`` topics come live with HeishaMon's next full
        dump, so control resumes within the dump interval plus a tick.
        """
        back = self.start + self.down_s
        sent = [c for c in self.commands if c.status == "sent" and c.ts < back]
        return [
            verdict("nothing is published while the broker is down", not sent, f"{len(sent)} sent"),
            _refuses_dead(self, self.start + TICK_S, back),
            _resumes(self, back, DUMP_INTERVAL_S + SLACK_S),
            _no_trouble(self, self.start),
        ]


@dataclass
class TopicStale(Scenario):
    """HeishaMon stops publishing ``Outside_Temp`` for 30 min (the rest keeps coming)."""

    name: str = "topic_stale"
    window_s: float = 2 * HOUR
    silent_s: float = 1800.0
    topic: str = "Outside_Temp"

    def plan(self, run: FullRun) -> None:
        """Silence the topic and bring it back."""
        self.at(0.0, lambda r, t: r.board.silenced.add(self.topic))
        self.at(self.silent_s, lambda r, t: r.board.silenced.discard(self.topic))

    def checks(self, run: FullRun) -> list[Check]:
        """Hold (inputs_missing) once stale, never refuse, resume after the topic is back."""
        back = self.start + self.silent_s
        stale_from = self.start + HEISHAMON_MAX_AGE_S + DUMP_INTERVAL_S + TICK_S
        during = self.between(stale_from, back)
        wrong = [d for d in during if not (d.ladder == "hold" and d.reason == "inputs_missing")]
        refused = [d for d in self.between(self.start, back) if d.ladder == "refuse"]
        self.notes["holds"] = len(during) - len(wrong)
        return [
            verdict(
                "every decision with a stale Outside_Temp holds (inputs_missing)",
                bool(during) and not wrong,
                f"{len(during)} decisions, {len(wrong)} not holding"
                + (f" (first {wrong[0].ladder}/{wrong[0].reason})" if wrong else ""),
            ),
            verdict("no refusal (HeishaMon is alive)", not refused, f"{len(refused)} refusals"),
            _resumes(self, back, DUMP_INTERVAL_S + SLACK_S),
            _no_trouble(self, self.start),
        ]
