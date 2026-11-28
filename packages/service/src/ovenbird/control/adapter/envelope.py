"""The HeishaMon envelope rule: recognise its correction of ovenbird's water setpoint.

When the owner declared the rule installed, a read-back difference of the water
setpoint that the rule explains (ovenbird's value outside the envelope band at the
current ``Outside_Temp``, the pump now reporting what the rule writes there) is not a
foreign writer: it is journalled (``envelope_correction``), counted and adopted, and
``envelope_mismatch`` is raised when ovenbird's value already lay outside the band
when it was set.
"""

from __future__ import annotations

import math
from typing import Final

from ovenbird.control.adapter.base import AdapterBase
from ovenbird.control.adapter.model import (
    LOGGER,
    Reader,
    verify_signal,
)
from ovenbird.control.alarms import (
    ENVELOPE_JOURNAL_CODE,
    AlarmCode,
    AlarmEvent,
    AlarmEventKind,
    Severity,
)
from ovenbird_core import (
    HeishaSignal,
    Instant,
)
from ovenbird_core.control import IntentKind, SafetyLimits
from ovenbird_core.control.observe import as_number

BAND_EPSILON_K: Final = 1e-6


class EnvelopeMixin(AdapterBase):
    """Envelope-rule recognition of the command adapter."""

    def _rule_band(self) -> tuple[SafetyLimits, float, float, float] | None:
        """Return the declared rule, the outside temperature and its band, when known."""
        rule = self.config.envelope_rule
        outside = self._outside
        if rule is None or outside is None:
            return None
        bounds = rule.bounds(outside)
        return rule, outside, bounds.low, bounds.high

    @staticmethod
    def _inside(value: float, low: float, high: float) -> bool:
        """Return whether ``value`` lies in ``[low, high]``, within the band tolerance."""
        return low - BAND_EPSILON_K <= value <= high + BAND_EPSILON_K

    def _watch_envelope(self, now: Instant, read: Reader) -> None:
        """Track the outside temperature and the envelope band of ovenbird's own setpoint.

        The band is noted when ovenbird's water setpoint changes (verified or adopted);
        a value inside it clears ``envelope_mismatch``.
        """
        view = read(HeishaSignal.OUTSIDE_TEMP)
        number = as_number(view.value) if view is not None and view.fresh else None
        valid = number is not None and math.isfinite(number)
        self._outside = float(number) if valid and number is not None else None
        own = self._own.get(IntentKind.WATER_SETPOINT)
        band = self._rule_band()
        if band is None or own is None:
            return
        if self._own_band is not None and self._own_band[0] == own:
            return
        _, _, low, high = band
        self._own_band = (own, low, high)
        if self._inside(own, low, high):
            self.alarms.clear(
                AlarmCode.ENVELOPE_MISMATCH,
                now,
                f"ovenbird's water setpoint {own} °C is inside the envelope band",
            )

    def _rule_correction(self, own: int, seen: int, now: Instant) -> bool:
        """Recognise and adopt the envelope rule's correction of ovenbird's water setpoint.

        The read-back difference is the rule's when the rule is declared installed,
        ovenbird's value lies outside the band at the current outside temperature and
        the pump now reports what the rule writes there. When ovenbird's value already
        lay outside the band at the outside temperature it was set at, the controller
        did not clamp to the envelope: ``envelope_mismatch`` is raised (once).

        Parameters
        ----------
        own
            Water setpoint ovenbird last set.
        seen
            Water setpoint the pump reports now.
        now
            Time of the observation.

        Returns
        -------
        bool
            ``True`` when recognised (journalled, counted and adopted).
        """
        band = self._rule_band()
        if band is None:
            return False
        rule, outside, low, high = band
        if self._inside(own, low, high) or seen not in rule.fallback_values(outside):
            return False
        kind = IntentKind.WATER_SETPOINT
        noted = self._own_band
        set_outside = (
            noted is not None and noted[0] == own and not self._inside(own, noted[1], noted[2])
        )
        self.counters.envelope_corrections += 1
        self._verified[kind] = seen
        self._own[kind] = seen
        self._own_band = (seen, low, high)
        detail = {
            "setting": kind.value,
            "signal": verify_signal(kind),
            "ovenbird_value": own,
            "seen_value": seen,
            "outside_c": outside,
            "low_c": round(low, 2),
            "high_c": round(high, 2),
            "rule_c": round(rule.fallback_setpoint(outside), 2),
            "set_outside_band": set_outside,
        }
        message = (
            f"HeishaMon envelope rule corrected the water setpoint {own} -> {seen} °C at "
            f"{outside} °C outside (band {low:.1f}-{high:.1f} °C); ovenbird adopts it, not a "
            "foreign writer"
        )
        LOGGER.warning("%s", message)
        self.alarms.record(
            AlarmEvent(
                now,
                ENVELOPE_JOURNAL_CODE,
                Severity.INFO,
                AlarmEventKind.RECOGNISED,
                message,
                detail,
            )
        )
        if set_outside and noted is not None:
            self.alarms.raise_alarm(
                AlarmCode.ENVELOPE_MISMATCH,
                f"ovenbird's water setpoint {own} °C already lay outside the envelope band "
                f"{noted[1]:.1f}-{noted[2]:.1f} °C when it was set; the controller does not "
                "clamp to the envelope the HeishaMon rule enforces",
                now,
                detail,
            )
        return True
