"""What the service knows about the HeishaMon envelope fallback rule (the safety net).

The rule runs on the HeishaMon board (design principle 2): from ``Outside_Temp`` it
computes the conservative envelope curve and rewrites the water setpoint only when
it lies outside ``[curve - below, curve + above]`` or above the hard maximum. The
service cannot see the rule itself; it knows

- whether the owner declared it installed (``OVENBIRD_ENVELOPE_RULE_INSTALLED``,
  environment or options file), and
- evidence of it acting: on every control tick :class:`EnvelopeWatch` compares
  ``Z1_Water_Target_Temp`` with the previous tick's. A change from a value outside
  the envelope band (by more than :data:`OUTSIDE_MARGIN_K`) to exactly the value the
  rule writes there (:meth:`~ovenbird_core.control.SafetyLimits.fallback_values`) that
  no known writer explains is recognised as the rule's correction: ovenbird did not
  send it within :data:`OWN_WINDOW_S`, and ovenbird controls the pump (``auto`` with
  publishing), so any other controller is off. In shadow or while paused another controller
  writes, so a change there is never counted. The count and the last one are kept in
  ``config.db`` (:mod:`ovenbird.system.facts`), so a proof (for example the cut-over test of
  stopping the service at night-time load) survives restarts. The command adapter's
  stricter recognition of a correction of ovenbird's own value (journalled as
  ``envelope_correction``, adopted instead of a foreign-writer hold, see
  :mod:`ovenbird.control.adapter`) counts as evidence too; one correction seen by
  both is counted once.

The rule acts only when someone else, or nothing, writes outside the envelope, so no
evidence is normal while ovenbird or another well-behaved controller controls; the proof is
the deliberate test.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.control.adapter import CommandEvent, CommandStatus
from ovenbird.control.alarms import ENVELOPE_JOURNAL_CODE, AlarmEvent
from ovenbird_core import HeishaSignal, Instant
from ovenbird_core.control import IntentKind, Mode
from ovenbird_core.control.observe import as_number

if TYPE_CHECKING:
    from ovenbird.control.loop import ControlLoop
    from ovenbird.system.facts import Facts

LOGGER = logging.getLogger("ovenbird.control.envelope")
EVIDENCE_KEY: Final = "envelope_rule"
OUTSIDE_MARGIN_K: Final = 0.5
OWN_WINDOW_S: Final = 600.0
STATES: Final = ("not_declared", "declared", "proven")


class EnvelopeWatch:
    """Recognise the envelope rule's corrections and report the safety net.

    Parameters
    ----------
    loop
        The control loop (store, controller limits, adapter).
    facts
        Where the evidence is kept.
    installed
        The owner declared the rule installed.
    """

    def __init__(self, loop: ControlLoop, facts: Facts, *, installed: bool) -> None:
        self.loop = loop
        self.facts = facts
        self.installed = installed
        self._previous: tuple[float, float, float] | None = None
        self._sent: list[tuple[float, int]] = []
        if loop.adapter is not None:
            loop.adapter.listeners.append(self._on_command)
        loop.alarms.listeners.append(self._on_alarm)
        loop.tick_hooks.append(self.on_tick)

    def _on_command(self, event: CommandEvent) -> None:
        """Remember water setpoints ovenbird sent, to tell its own writes from the rule's."""
        if event.kind is IntentKind.WATER_SETPOINT and event.status is CommandStatus.SENT:
            stamp = event.at.wall.timestamp()
            self._sent = [(t, v) for t, v in self._sent if stamp - t <= OWN_WINDOW_S]
            self._sent.append((stamp, event.value))

    def _on_alarm(self, event: AlarmEvent) -> None:
        """Take the evidence of an envelope journal row into the stored count."""
        if event.code != ENVELOPE_JOURNAL_CODE:
            return
        detail = event.detail
        values = [
            as_number(detail.get(key))
            for key in ("ovenbird_value", "seen_value", "outside_c", "low_c", "high_c")
        ]
        if any(value is None for value in values):
            return
        before, after, outside, low, high = (float(v) for v in values if v is not None)
        self._record(event.at.wall.timestamp(), before, after, outside, low, high)

    def _band(self, outside_c: float) -> tuple[float, float]:
        """Return the envelope band ``(low, high)`` in degrees Celsius at ``outside_c``."""
        bounds = self.loop.controller.config.safety.bounds(outside_c)
        return bounds.low, bounds.high

    def _readings(self, now: Instant) -> tuple[float, float] | None:
        """Return the fresh water setpoint and outside temperature, or ``None``."""
        store = self.loop.runtime.store
        target = store.view(HeishaSignal.Z1_WATER_TARGET_TEMP, now)
        outside = store.view(HeishaSignal.OUTSIDE_TEMP, now)
        if target is None or outside is None or not target.fresh or not outside.fresh:
            return None
        value = as_number(target.value)
        temp = as_number(outside.value)
        if value is None or temp is None or not math.isfinite(value) or not math.isfinite(temp):
            return None
        return float(value), float(temp)

    def on_tick(self, now: Instant, mode: Mode) -> None:
        """Compare the pump's setpoint with the previous tick's (a control-loop hook).

        Parameters
        ----------
        now
            Time of the tick.
        mode
            Control mode of the tick.
        """
        readings = self._readings(now)
        if readings is None:
            self._previous = None
            return
        value, outside = readings
        low, high = self._band(outside)
        previous = self._previous
        self._previous = (value, low, high)
        if previous is None or previous[0] == value:
            return
        before, before_low, before_high = previous
        outside_before = before < before_low - OUTSIDE_MARGIN_K or before > before_high + (
            OUTSIDE_MARGIN_K
        )
        rule_value = value == round(value) and int(value) in self._rule_values(outside)
        stamp = now.wall.timestamp()
        own = any(stamp - t <= OWN_WINDOW_S and v == round(value) for t, v in self._sent)
        sole_writer = mode is Mode.AUTO and self.loop.adapter is not None
        if outside_before and rule_value and not own and sole_writer:
            self._record(stamp, before, value, outside, low, high)

    def _rule_values(self, outside_c: float) -> frozenset[int]:
        """Return the setpoints the envelope rule can write at ``outside_c``."""
        return self.loop.controller.config.safety.fallback_values(outside_c)

    def _record(
        self, stamp: float, before: float, after: float, outside: float, low: float, high: float
    ) -> None:
        """Count one observed rule correction and store the evidence.

        Parameters
        ----------
        stamp
            Unix time of the observation.
        before
            Setpoint before the correction, in degrees Celsius.
        after
            Setpoint after the correction, in degrees Celsius.
        outside
            Outside temperature, in degrees Celsius.
        low
            Lower band edge at that outside temperature, in degrees Celsius.
        high
            Upper band edge at that outside temperature, in degrees Celsius.
        """
        stored = self.facts.get(EVIDENCE_KEY)
        count = int(stored.get("count", 0)) if isinstance(stored, dict) else 0
        first = stored.get("first_ts") if isinstance(stored, dict) else None
        previous = stored.get("last") if isinstance(stored, dict) else None
        if (
            isinstance(previous, dict)
            and previous.get("from_c") == before
            and previous.get("to_c") == after
            and abs(stamp - float(previous.get("ts") or 0.0)) <= OWN_WINDOW_S
        ):
            return
        last = {
            "ts": stamp,
            "from_c": before,
            "to_c": after,
            "outside_c": outside,
            "low_c": round(low, 2),
            "high_c": round(high, 2),
        }
        self.facts.set(EVIDENCE_KEY, {"count": count + 1, "first_ts": first or stamp, "last": last})
        LOGGER.warning(
            "envelope rule correction recognised: water setpoint %s -> %s °C at %s °C outside "
            "(band %.1f-%.1f °C)",
            before,
            after,
            outside,
            low,
            high,
        )

    def evidence(self) -> dict[str, Any]:
        """Return the recognised corrections: count, first and last."""
        stored = self.facts.get(EVIDENCE_KEY)
        if not isinstance(stored, dict) or not isinstance(stored.get("last"), dict):
            return {"count": 0, "first_at": None, "last": None}
        last = dict(stored["last"])
        stamp = last.pop("ts", None)
        first = stored.get("first_ts")
        return {
            "count": int(stored.get("count", 0)),
            "first_at": None if first is None else iso_from_unix(float(first)),
            "last": {"at": None if stamp is None else iso_from_unix(float(stamp)), **last},
        }

    def status(self, now: Instant | None = None) -> dict[str, Any]:
        """Return the ``safety_net`` block of ``GET api/v1/system/about``.

        Parameters
        ----------
        now
            Time to evaluate at; the service clock when omitted.
        """
        moment = now or self.loop.runtime.clock()
        evidence = self.evidence()
        if not self.installed:
            state = "not_declared"
        elif evidence["count"] > 0:
            state = "proven"
        else:
            state = "declared"
        safety = self.loop.controller.config.safety
        band: dict[str, Any] | None = None
        outside = self.loop.runtime.store.view(HeishaSignal.OUTSIDE_TEMP, moment)
        temp = as_number(outside.value) if outside is not None and outside.fresh else None
        if temp is not None:
            low, high = self._band(float(temp))
            band = {"outside_c": float(temp), "low_c": round(low, 2), "high_c": round(high, 2)}
        adapter = self.loop.adapter
        corrections = None
        adopted = None
        if adapter is not None:
            status = adapter.status(moment)
            corrections = {**status["corrections"], "total": status["counters"]["corrections"]}
            adopted = status["counters"]["envelope_corrections"]
        return {
            "envelope_rule": {
                "installed": self.installed,
                "state": state,
                **evidence,
                "adopted": adopted,
            },
            "envelope_now": band,
            "max_supply_c": safety.max_supply_c,
            "min_setpoint_c": safety.min_setpoint_c,
            "envelope_below_k": safety.envelope_below_k,
            "envelope_above_k": safety.envelope_above_k,
            "ovenbird_corrections": corrections,
        }
