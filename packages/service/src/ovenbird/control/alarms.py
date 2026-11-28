"""Alarms of the control path (adapter, safety monitors), journalled on every transition.

An alarm is raised when its condition appears and cleared only when the condition is
gone; every transition is logged, kept in a bounded in-memory history and handed to
the journal (``history.db`` table ``alarm``) so the history survives restarts.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ovenbird.clock import iso_z
from ovenbird_core import Instant

LOGGER = logging.getLogger("ovenbird.control.alarms")
HISTORY_SIZE: Final = 200


class Severity(StrEnum):
    """How bad an alarm is.

    ``critical`` concerns the safety of the plant (readiness turns false);
    ``warning`` means ovenbird does not control as intended; ``info`` is a notice.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


SEVERITY_RANK: Final = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


class AlarmCode(StrEnum):
    """Closed set of control alarms."""

    MODE_MISMATCH = "mode_mismatch"
    VERIFICATION_FAILED = "verification_failed"
    WRITE_BUDGET = "write_budget"
    FOREIGN_WRITER = "foreign_writer"
    HOLD_LATCHED = "hold_latched"
    HEISHAMON_RESTARTED = "heishamon_restarted"
    CORRECTION_FAILED = "correction_failed"
    SETPOINT_ABOVE_MAX = "setpoint_above_max"
    OUTLET_OVERSHOOT = "outlet_overshoot"
    LOW_FLOW = "low_flow"
    LOW_FLOW_DEFROST = "low_flow_defrost"
    PUMP_ERROR = "pump_error"
    BACKUP_HEATER = "backup_heater"
    BACKUP_HEATER_ALLOWED = "backup_heater_allowed"
    HEATING_OFF_OUTDOOR = "heating_off_outdoor"
    DEFROST_STUCK = "defrost_stuck"
    ROOM_BELOW_FLOOR = "room_below_floor"
    ROOM_SENSOR_SILENT = "room_sensor_silent"
    ROOM_SENSOR_QUIET = "room_sensor_quiet"
    ROOM_REPORT_OVERDUE = "room_report_overdue"
    ROOM_IMPLAUSIBLE = "room_implausible"
    ROOM_UNIT_REFUSED = "room_unit_refused"
    HA_LINK_DOWN = "ha_link_down"
    CONFIG_RESET = "config_reset"
    PUMP_SETTING_CHANGED = "pump_setting_changed"
    ENVELOPE_MISMATCH = "envelope_mismatch"
    STOVE_REFERENCE_MISSING = "stove_reference_missing"
    OUTSIDE_SENSOR_STALE = "outside_sensor_stale"
    OUTSIDE_SENSOR_IMPLAUSIBLE = "outside_sensor_implausible"
    MQTT_CONNECTION_REVERTED = "mqtt_connection_reverted"
    MQTT_REVERT_FAILED = "mqtt_revert_failed"
    RELEASE_INTERRUPTED = "release_interrupted"
    NOTIFY_FAILING = "notify_failing"
    ARCHIVE_FAILING = "archive_failing"
    ARCHIVE_REBUILT = "archive_rebuilt"
    COMPRESSOR_STARTS = "compressor_starts"


SEVERITY: Final[dict[AlarmCode, Severity]] = {
    AlarmCode.MODE_MISMATCH: Severity.WARNING,
    AlarmCode.VERIFICATION_FAILED: Severity.WARNING,
    AlarmCode.WRITE_BUDGET: Severity.WARNING,
    AlarmCode.FOREIGN_WRITER: Severity.WARNING,
    AlarmCode.HOLD_LATCHED: Severity.WARNING,
    AlarmCode.HEISHAMON_RESTARTED: Severity.INFO,
    AlarmCode.CORRECTION_FAILED: Severity.CRITICAL,
    AlarmCode.SETPOINT_ABOVE_MAX: Severity.CRITICAL,
    AlarmCode.OUTLET_OVERSHOOT: Severity.CRITICAL,
    AlarmCode.LOW_FLOW: Severity.CRITICAL,
    AlarmCode.LOW_FLOW_DEFROST: Severity.WARNING,
    AlarmCode.PUMP_ERROR: Severity.CRITICAL,
    AlarmCode.BACKUP_HEATER: Severity.WARNING,
    AlarmCode.BACKUP_HEATER_ALLOWED: Severity.INFO,
    AlarmCode.HEATING_OFF_OUTDOOR: Severity.INFO,
    AlarmCode.DEFROST_STUCK: Severity.WARNING,
    AlarmCode.ROOM_BELOW_FLOOR: Severity.WARNING,
    AlarmCode.ROOM_SENSOR_SILENT: Severity.WARNING,
    AlarmCode.ROOM_SENSOR_QUIET: Severity.WARNING,
    AlarmCode.ROOM_REPORT_OVERDUE: Severity.WARNING,
    AlarmCode.ROOM_IMPLAUSIBLE: Severity.WARNING,
    AlarmCode.ROOM_UNIT_REFUSED: Severity.WARNING,
    AlarmCode.HA_LINK_DOWN: Severity.WARNING,
    AlarmCode.CONFIG_RESET: Severity.WARNING,
    AlarmCode.PUMP_SETTING_CHANGED: Severity.INFO,
    AlarmCode.ENVELOPE_MISMATCH: Severity.WARNING,
    AlarmCode.STOVE_REFERENCE_MISSING: Severity.WARNING,
    AlarmCode.OUTSIDE_SENSOR_STALE: Severity.WARNING,
    AlarmCode.OUTSIDE_SENSOR_IMPLAUSIBLE: Severity.WARNING,
    AlarmCode.MQTT_CONNECTION_REVERTED: Severity.WARNING,
    AlarmCode.MQTT_REVERT_FAILED: Severity.CRITICAL,
    AlarmCode.RELEASE_INTERRUPTED: Severity.WARNING,
    AlarmCode.NOTIFY_FAILING: Severity.WARNING,
    AlarmCode.ARCHIVE_FAILING: Severity.WARNING,
    AlarmCode.ARCHIVE_REBUILT: Severity.WARNING,
    AlarmCode.COMPRESSOR_STARTS: Severity.WARNING,
}

HOLD_JOURNAL_CODE: Final = "command_hold"
ENVELOPE_JOURNAL_CODE: Final = "envelope_correction"


class AlarmEventKind(StrEnum):
    """Journalled transitions."""

    RAISED = "raised"
    CLEARED = "cleared"
    STARTED = "started"
    EXPIRED = "expired"
    RELEASED = "released"
    RECOGNISED = "recognised"


@dataclass(frozen=True, slots=True)
class Alarm:
    """One active alarm.

    Parameters
    ----------
    code
        Alarm code.
    message
        Human explanation.
    since
        When it was raised.
    detail
        Machine-readable extras (for a foreign writer: the setting, the value
        ovenbird set, the value seen and what happens when the hold ends).
    """

    code: AlarmCode
    message: str
    since: Instant
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        """Severity of the code."""
        return SEVERITY[self.code]

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "message": self.message,
            "since": iso_z(self.since.wall),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    """A journalled alarm or hold transition.

    Parameters
    ----------
    at
        When it happened.
    code
        Alarm code, or ``command_hold`` for hold life-cycle events.
    severity
        Severity at the time.
    event
        Transition.
    message
        Human explanation.
    detail
        Machine-readable extras (hold end, latch flag).
    """

    at: Instant
    code: str
    severity: Severity
    event: AlarmEventKind
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "at": iso_z(self.at.wall),
            "code": self.code,
            "severity": self.severity.value,
            "event": self.event.value,
            "message": self.message,
            "detail": self.detail,
        }

    def detail_text(self) -> str:
        """Return ``detail`` as compact JSON."""
        return json.dumps(self.detail, separators=(",", ":"), sort_keys=True)


type AlarmSink = Callable[[AlarmEvent], None]


class AlarmBoard:
    """Raise and clear alarms; each transition is logged and journalled once.

    Parameters
    ----------
    journal
        Receives every transition (the history writer); ``None`` keeps it in memory.

    Attributes
    ----------
    listeners
        Also receive every transition (notifications); a failing listener is logged
        and never stops the others.
    """

    def __init__(self, journal: AlarmSink | None = None) -> None:
        self._active: dict[AlarmCode, Alarm] = {}
        self.history: deque[AlarmEvent] = deque(maxlen=HISTORY_SIZE)
        self.journal = journal
        self.listeners: list[AlarmSink] = []
        self.raised = 0

    def record(self, event: AlarmEvent) -> None:
        """Keep and journal one transition and hand it to the listeners."""
        self.history.append(event)
        if self.journal is not None:
            self.journal(event)
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:
                LOGGER.exception("alarm listener failed")

    def journal_only(self, event: AlarmEvent) -> None:
        """Keep and journal one informational event without telling the listeners.

        For notices that must be reviewable but never notify (closing an orphaned
        wood-stove episode); the alarm board's active alarms and its bounded in-memory
        history are not touched, so a chatty notice cannot push real alarms out of it.
        """
        if self.journal is not None:
            self.journal(event)

    def raise_alarm(
        self,
        code: AlarmCode,
        message: str,
        now: Instant,
        detail: dict[str, Any] | None = None,
    ) -> bool:
        """Raise ``code`` (with optional structured ``detail``); ``True`` when it was not active.

        Parameters
        ----------
        code
            Alarm to raise.
        message
            Alarm text.
        now
            Time of the event.
        detail
            Structured detail stored with the alarm.
        """
        if code in self._active:
            return False
        extras = dict(detail or {})
        self._active[code] = Alarm(code, message, now, extras)
        self.raised += 1
        severity = SEVERITY[code]
        level = logging.CRITICAL if severity is Severity.CRITICAL else logging.ERROR
        if severity is Severity.INFO:
            level = logging.WARNING
        LOGGER.log(level, "ALARM %s (%s): %s", code.value, severity.value, message)
        self.record(AlarmEvent(now, code.value, severity, AlarmEventKind.RAISED, message, extras))
        return True

    def clear(self, code: AlarmCode, now: Instant, why: str = "condition gone") -> bool:
        """Clear ``code``; returns ``True`` when it was active."""
        alarm = self._active.pop(code, None)
        if alarm is None:
            return False
        LOGGER.warning("alarm %s cleared: %s", code.value, why)
        self.record(AlarmEvent(now, code.value, SEVERITY[code], AlarmEventKind.CLEARED, why))
        return True

    def is_active(self, code: AlarmCode) -> bool:
        """Whether ``code`` is active."""
        return code in self._active

    def get(self, code: AlarmCode) -> Alarm | None:
        """Return the active alarm ``code``, if active."""
        return self._active.get(code)

    def active(self) -> tuple[Alarm, ...]:
        """Active alarms in the order they were raised."""
        return tuple(self._active.values())

    def level(self) -> Severity | None:
        """Highest severity of the active alarms; ``None`` when none is active."""
        if not self._active:
            return None
        return max(
            (alarm.severity for alarm in self._active.values()),
            key=lambda severity: SEVERITY_RANK[severity],
        )
