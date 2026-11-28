"""Release control: the go-live pump-state snapshot and its restore (the hand-back).

**Snapshot.** On every control tick that runs in ``auto`` with publishing permitted,
the manager makes sure a snapshot of the pump state *before ovenbird wrote anything*
exists: when there is none, the last one was used by a complete release, or the one
there was captured by hand in shadow, it records the settings ovenbird may write
(water setpoint ``Z1_Water_Target_Temp``, maximum pump duty, quiet level) plus facts
it never writes (``Heating_Mode``, ``Operating_Mode_State``, the setpoint register's
read-back and the stored curve) and the outside temperature. It runs before the
arbiter of that tick, so nothing ovenbird sent can be in it; a value that is not
fresh at go-live is filled in at the first tick where it is (the arbiter never sends
a value it cannot read, so it is still the pump's own). A pause followed by a resume
keeps the snapshot, and so does an incomplete release. It is kept in ``config.db``
(:mod:`ovenbird.system.facts`). While ovenbird does not control (shadow, paused) an admin
may capture a snapshot from the pump's current values (:meth:`ReleaseManager.capture`,
origin ``manual``) to rehearse against; the go-live replaces it.

**Release** (``POST api/v1/control/release``): the pause is stored first (a restart
comes back paused; when it cannot be stored nothing changes), the controller stops
(the loop runs as ``shadow``) and every snapshot value that differs from what the
pump reports now is restored through the command adapter
(:meth:`~ovenbird.control.adapter.CommandAdapter.request_restore`: the same
allowlist, clamps, spacing, budget and verification as any controller command, the
water setpoint also kept inside the envelope band at the current outside
temperature, refused during a hold). A setting with one of ovenbird's own commands
still in flight is always restored: the restore waits until that command has
settled. Settings ovenbird does not control are left alone. When every item has
settled and nothing is in flight, the pump's values are read once more (an item the
pump no longer reports ends ``changed``), or the timeout passes, and the pause takes
effect: the adapter drops what is left and forgets its verified values, so the
previous controller can take over. Only a release that restored everything
uses up the snapshot; after an incomplete one a resume keeps it. The run is stored
when it starts and on every step, so a restart in the middle finds it, marks it
``interrupted`` and raises ``release_interrupted`` (warning). Each item is reported,
the time taken recorded and the release audited (``control_release``); a rehearsal
is the same release flagged for the trial checklist, and a *dry* rehearsal plans the
release against the snapshot without sending or pausing anything (possible in
shadow).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_z
from ovenbird.control.adapter import (
    RESTORE_PREFIX,
    VERIFY_SIGNALS,
    AdapterConfig,
    CommandEvent,
    CommandStatus,
    Reader,
    SettingRefusedError,
    reported_int,
    restore_target,
)
from ovenbird.control.alarms import AlarmCode
from ovenbird.system.privacy import public_name
from ovenbird_core import HeishaSignal, Instant, SignalId
from ovenbird_core.control import IntentKind, Mode
from ovenbird_core.control.observe import as_number

if TYPE_CHECKING:
    from ovenbird.configstore import Actor, ConfigManager
    from ovenbird.control.loop import ControlLoop
    from ovenbird.system.facts import Facts

LOGGER = logging.getLogger("ovenbird.control.release")
SNAPSHOT_KEY: Final = "pump_snapshot"
LAST_KEY: Final = "release_last"
REHEARSAL_KEY: Final = "release_last_rehearsal"
DRY_KEY: Final = "release_last_dry_rehearsal"
AUDIT_ACTION: Final = "control_release"
CAPTURE_ACTION: Final = "snapshot_capture"
PAUSE_REASON: Final = "release control"
REHEARSAL_LIMIT_S: Final = 300.0
TIMEOUT_MARGIN_S: Final = 60.0
MAX_REASON: Final = 200
DAY_S: Final = 86_400.0
STALE_AFTER_S: Final = {"go_live": 30.0 * DAY_S, "manual": 7.0 * DAY_S}
ORIGINS: Final = ("go_live", "manual")
FACT_SIGNALS: Final[tuple[SignalId, ...]] = (
    HeishaSignal.HEATING_MODE,
    HeishaSignal.OPERATING_MODE_STATE,
    HeishaSignal.Z1_HEAT_REQUEST_TEMP,
    HeishaSignal.Z1_CURVE_TARGET_HIGH_TEMP,
    HeishaSignal.Z1_CURVE_TARGET_LOW_TEMP,
    HeishaSignal.Z1_CURVE_OUTSIDE_HIGH_TEMP,
    HeishaSignal.Z1_CURVE_OUTSIDE_LOW_TEMP,
)
OK_STATUSES: Final = frozenset({"verified", "unchanged", "not_managed", "planned"})
TERMINAL: Final = OK_STATUSES | {
    "missing",
    "refused",
    "failed",
    "dropped",
    "timeout",
    "changed",
}
ITEM_STATUSES: Final = (
    "queued",
    "sent",
    "retry",
    "verified",
    "unchanged",
    "not_managed",
    "planned",
    "missing",
    "refused",
    "failed",
    "dropped",
    "timeout",
    "changed",
)
OUTCOMES: Final = ("running", "ok", "incomplete", "interrupted")
REFUSAL_CODES: Final = (
    "in_progress",
    "not_publishing",
    "reset_pending",
    "no_snapshot",
    "storage_failed",
)
CAPTURE_REFUSALS: Final = ("controlling", "in_use", "in_progress")
EVENT_STATUS: Final = {
    CommandStatus.QUEUED: "queued",
    CommandStatus.SENT: "sent",
    CommandStatus.RETRY: "retry",
    CommandStatus.VERIFIED: "verified",
    CommandStatus.FAILED: "failed",
    CommandStatus.DROPPED: "dropped",
    CommandStatus.REFUSED: "refused",
}


class ReleaseRefusedError(Exception):
    """A release or snapshot request is refused.

    Parameters
    ----------
    status
        HTTP status.
    code
        Stable refusal code.
    message
        Human explanation.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def to_json(self) -> dict[str, Any]:
        """Return the ``detail`` of the error response."""
        return {"code": self.code, "message": self.message}


def _wall(ts: float | None) -> datetime | None:
    """Return the UTC datetime of a Unix timestamp (s), or ``None``."""
    return None if ts is None else datetime.fromtimestamp(ts, UTC)


def _iso(moment: datetime | None) -> str | None:
    """Return the ISO 8601 text of a datetime, or ``None``."""
    return None if moment is None else iso_z(moment)


@dataclass(slots=True)
class PumpSnapshot:
    """The pump state recorded at go-live (or captured by hand in shadow).

    Parameters
    ----------
    taken_at
        When it was recorded (service clock).
    previous_mode
        The loop's mode on the tick before (``shadow``, ``off`` or ``None`` after a
        start; ``auto`` means ovenbird already controlled, so the values may be
        its own).
    register
        Setpoint register in use (``OVENBIRD_COMMAND_SETPOINT_REGISTER``).
    items
        Restorable settings by kind (``water_setpoint``, ...): the integer the pump
        reported, ``None`` while not freshly known.
    facts
        Values ovenbird never writes, by signal id (``None`` when not fresh).
    released_at
        When a complete release used it; a new go-live then records a new snapshot.
    origin
        ``go_live`` (recorded by the first publishing tick) or ``manual`` (captured
        by an admin while ovenbird did not control).
    outside_c
        The outside temperature when it was recorded, if fresh.
    by
        Who captured a ``manual`` snapshot.
    """

    taken_at: datetime
    previous_mode: str | None
    register: str
    items: dict[str, int | None]
    facts: dict[str, float | None]
    released_at: datetime | None = None
    origin: str = "go_live"
    outside_c: float | None = None
    by: str | None = None

    @property
    def complete(self) -> bool:
        """Whether every restorable value is known."""
        return all(value is not None for value in self.items.values())

    @property
    def armed(self) -> bool:
        """Whether a release would use it (not used up by a complete release)."""
        return self.released_at is None

    def age_s(self, now: datetime) -> float:
        """Return its age at ``now``."""
        return max(0.0, (now - self.taken_at).total_seconds())

    def stale(self, now: datetime) -> bool:
        """Whether it is older than :data:`STALE_AFTER_S` for its origin."""
        return self.age_s(now) > STALE_AFTER_S.get(self.origin, STALE_AFTER_S["go_live"])

    def to_store(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "taken_ts": self.taken_at.timestamp(),
            "previous_mode": self.previous_mode,
            "register": self.register,
            "items": self.items,
            "facts": self.facts,
            "released_ts": None if self.released_at is None else self.released_at.timestamp(),
            "origin": self.origin,
            "outside_c": self.outside_c,
            "by": self.by,
        }

    @classmethod
    def from_store(cls, raw: Any) -> PumpSnapshot | None:
        """Rebuild a stored snapshot; ``None`` when it is missing or malformed."""
        if not isinstance(raw, dict):
            return None
        try:
            taken = _wall(float(raw["taken_ts"]))
            released = raw.get("released_ts")
            items = {str(k): (None if v is None else int(v)) for k, v in raw["items"].items()}
            facts = {str(k): (None if v is None else float(v)) for k, v in raw["facts"].items()}
            outside = raw.get("outside_c")
            outside_c = None if outside is None else float(outside)
        except KeyError, TypeError, ValueError, AttributeError:
            LOGGER.warning("stored pump-state snapshot is malformed; ignored")
            return None
        assert taken is not None
        origin = raw.get("origin")
        by = raw.get("by")
        return cls(
            taken_at=taken,
            previous_mode=raw.get("previous_mode"),
            register=str(raw.get("register", "")),
            items=items,
            facts=facts,
            released_at=_wall(None if released is None else float(released)),
            origin=origin if origin in ORIGINS else "go_live",
            outside_c=outside_c,
            by=by if isinstance(by, str) else None,
        )

    def to_json(self, now: datetime | None = None) -> dict[str, Any]:
        """Return the API form (``age_s`` and ``stale`` at ``now`` when given)."""
        return {
            "taken_at": iso_z(self.taken_at),
            "origin": self.origin,
            "by": public_name(self.by),
            "previous_mode": self.previous_mode,
            "own_values_possible": self.previous_mode == Mode.AUTO.value,
            "register": self.register,
            "complete": self.complete,
            "released_at": _iso(self.released_at),
            "outside_c": self.outside_c,
            "age_s": None if now is None else round(self.age_s(now), 1),
            "stale": None if now is None else self.stale(now),
            "stale_after_s": STALE_AFTER_S.get(self.origin),
            "items": [
                {
                    "kind": kind.value,
                    "signal": VERIFY_SIGNALS[kind],
                    "value": self.items.get(kind.value),
                }
                for kind in VERIFY_SIGNALS
            ],
            "facts": dict(self.facts),
        }


@dataclass(slots=True)
class ReleaseItem:
    """One setting of a release.

    Parameters
    ----------
    kind
        The setting.
    snapshot
        The value recorded at go-live.
    before
        What the pump reported when the release started.
    status
        ``queued``, ``sent``, ``retry``, then ``verified``, ``unchanged``,
        ``not_managed`` (``planned`` in a dry rehearsal), ``missing``, ``refused``,
        ``failed``, ``dropped``, ``timeout`` or ``changed``.
    detail
        Human explanation of the latest status.
    target
        The value sent (after the clamps), when one is sent or planned.
    at
        When the latest status was reached.
    clamped
        Why the target differs from the snapshot value, if it does.
    waited_for
        The value of ovenbird's own command that was in flight at the start.
    """

    kind: IntentKind
    snapshot: int | None
    before: int | None
    status: str = "pending"
    detail: str = ""
    target: int | None = None
    at: datetime | None = None
    clamped: str | None = None
    waited_for: int | None = None

    @property
    def done(self) -> bool:
        """Whether the item reached a final status."""
        return self.status in TERMINAL

    def update(self, status: str, detail: str, at: datetime) -> None:
        """Move to ``status``."""
        self.status = status
        self.detail = detail
        self.at = at

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "kind": self.kind.value,
            "signal": VERIFY_SIGNALS[self.kind],
            "snapshot": self.snapshot,
            "before": self.before,
            "target": self.target,
            "clamped": self.clamped,
            "waited_for": self.waited_for,
            "status": self.status,
            "ok": self.status in OK_STATUSES,
            "detail": self.detail,
            "at": _iso(self.at),
        }


@dataclass(slots=True)
class ReleaseRun:
    """One release of control.

    Parameters
    ----------
    started
        When it started (service clock).
    actor
        Who released control (audit identity).
    by
        Who released control, with the reason.
    rehearsal
        A rehearsal for the trial checklist.
    reason
        Optional operator note.
    snapshot_taken_at
        The snapshot restored.
    paused_before
        Control was already paused when the release started.
    items
        One entry per restorable setting.
    finished
        When the pause took effect.
    dry
        Planned only: nothing sent, nothing paused.
    snapshot_origin
        ``go_live`` or ``manual``.
    snapshot_age_s
        The snapshot's age when the release started.
    outside_c
        The outside temperature the water setpoint was clamped for.
    """

    started: Instant
    actor: Actor
    by: str
    rehearsal: bool
    reason: str | None
    snapshot_taken_at: datetime
    paused_before: bool
    items: list[ReleaseItem] = field(default_factory=list)
    finished: Instant | None = None
    dry: bool = False
    snapshot_origin: str = "go_live"
    snapshot_age_s: float | None = None
    outside_c: float | None = None

    @property
    def done(self) -> bool:
        """Whether the pause took effect (or the plan is made)."""
        return self.finished is not None

    @property
    def ok(self) -> bool:
        """Whether every item ended well."""
        return all(item.status in OK_STATUSES for item in self.items)

    def to_json(self, now: Instant | None = None) -> dict[str, Any]:
        """Return the API form (``duration_s`` so far while running)."""
        end = self.finished or now
        duration = None if end is None else round(end.since(self.started), 1)
        outcome = "running" if not self.done else ("ok" if self.ok else "incomplete")
        return {
            "started_at": iso_z(self.started.wall),
            "finished_at": None if self.finished is None else iso_z(self.finished.wall),
            "done": self.done,
            "outcome": outcome,
            "rehearsal": self.rehearsal,
            "dry": self.dry,
            "by": public_name(self.by),
            "reason": self.reason,
            "paused_before": self.paused_before,
            "duration_s": duration,
            "within_limit": None if duration is None else duration <= REHEARSAL_LIMIT_S,
            "snapshot_taken_at": iso_z(self.snapshot_taken_at),
            "snapshot_origin": self.snapshot_origin,
            "snapshot_age_s": self.snapshot_age_s,
            "outside_c": self.outside_c,
            "interrupted": False,
            "items": [item.to_json() for item in self.items],
        }


def _number(view: Any) -> float | None:
    """Return the numeric value of a fresh reading, else ``None``."""
    if view is None or not view.fresh:
        return None
    number = as_number(view.value)
    return None if number is None else float(number)


class ReleaseManager:
    """Keep the go-live snapshot and run releases of control.

    Parameters
    ----------
    loop
        The control loop (its runtime, guard, adapter and controller).
    facts
        Where the snapshot and the last releases are kept.
    previous_mode
        Mode of the newest stored decision (the mode before a restart).
    limits
        The adapter's limits (clamps of a dry rehearsal without an adapter); the
        adapter's own when omitted.
    register
        Setpoint register in use (for a snapshot captured without an adapter).
    """

    def __init__(
        self,
        loop: ControlLoop,
        facts: Facts,
        previous_mode: str | None = None,
        *,
        limits: AdapterConfig | None = None,
        register: str = "setcurves_target_high",
    ) -> None:
        self.loop = loop
        self.facts = facts
        self.config: ConfigManager | None = None
        self.run: ReleaseRun | None = None
        self.snapshot = PumpSnapshot.from_store(facts.get(SNAPSHOT_KEY))
        self._last_mode = previous_mode
        self.limits = (
            limits
            if limits is not None
            else (loop.adapter.config if loop.adapter is not None else None)
        )
        self.register = register
        if loop.adapter is not None:
            loop.adapter.listeners.append(self._on_event)
        loop.tick_hooks.append(self.on_tick)
        self._recover()

    def _recover(self) -> None:
        """After a restart, mark an unfinished release as interrupted and raise its alarm."""
        stored = self.facts.get(LAST_KEY)
        if not isinstance(stored, dict) or stored.get("done") is not False:
            return
        now = self.loop.runtime.clock()
        body = {**stored, "done": True, "outcome": "interrupted", "interrupted": True}
        body["noticed_at"] = iso_z(now.wall)
        self._store(LAST_KEY, body)
        if body.get("rehearsal"):
            self._store(REHEARSAL_KEY, body)
        unfinished = [
            item.get("kind")
            for item in body.get("items", [])
            if isinstance(item, dict) and not item.get("ok")
        ]
        LOGGER.error(
            "a release of control started at %s was interrupted by a restart; not finished: %s",
            stored.get("started_at"),
            ", ".join(str(kind) for kind in unfinished) or "nothing",
        )
        self.loop.alarms.raise_alarm(
            AlarmCode.RELEASE_INTERRUPTED,
            f"the release of control started at {stored.get('started_at')} was interrupted by a "
            "restart; control stays paused and the pump may be only partly restored "
            f"(not finished: {', '.join(str(k) for k in unfinished) or 'none'}); release "
            "again to finish the hand-back",
            now,
            {"started_at": stored.get("started_at"), "unfinished": unfinished},
        )

    @property
    def timeout_s(self) -> float:
        """Longest a release waits for its commands before the pause takes effect."""
        adapter = self.loop.adapter
        if adapter is None:
            return TIMEOUT_MARGIN_S
        config = adapter.config
        per_item = config.verify_timeout_s * (config.max_retries + 1) + config.min_spacing_s
        return per_item * (len(VERIFY_SIGNALS) + 1) + TIMEOUT_MARGIN_S

    def _reader(self, now: Instant) -> Reader:
        """Return a signal reader over the store as of ``now``."""
        store = self.loop.runtime.store
        return lambda signal: store.view(signal, now)

    def _store(self, key: str, value: Any) -> bool:
        """Store a fact; return ``False`` (after logging) when the database refuses it."""
        try:
            self.facts.set(key, value)
        except sqlite3.Error:
            LOGGER.exception("could not store %s", key)
            return False
        return True

    def _store_snapshot(self) -> None:
        """Store the go-live snapshot, or clear it when there is none."""
        snapshot = self.snapshot
        self._store(SNAPSHOT_KEY, None if snapshot is None else snapshot.to_store())

    def _outside(self, now: Instant) -> float | None:
        """Return the fresh outside temperature in °C, or ``None``."""
        return _number(self._reader(now)(HeishaSignal.OUTSIDE_TEMP))

    def on_tick(self, now: Instant, mode: Mode) -> None:
        """Check the release, keep the go-live snapshot (a control-loop hook)."""
        self.poll(now)
        self._finish_if_done(now)
        adapter = self.loop.adapter
        if mode is Mode.AUTO and adapter is not None and self.loop.guard.permits:
            snapshot = self.snapshot
            if snapshot is None or not snapshot.armed or snapshot.origin != "go_live":
                self._take(now, adapter.config.setpoint_register)
            elif not snapshot.complete:
                self._fill(now)
            self.loop.alarms.clear(AlarmCode.RELEASE_INTERRUPTED, now, "control resumed")
        self._last_mode = mode.value

    def _read_snapshot(
        self, now: Instant, register: str, origin: str, by: str | None
    ) -> PumpSnapshot:
        """Return the pump settings and facts as they are reported now.

        Parameters
        ----------
        now
            Time of the reading.
        register
            Register the water setpoint is written to.
        origin
            What triggered the snapshot (``go_live`` or a manual capture).
        by
            Who captured it, ``None`` for go-live.
        """
        read = self._reader(now)
        items = {kind.value: reported_int(read(signal)) for kind, signal in VERIFY_SIGNALS.items()}
        facts = {signal: _number(read(signal)) for signal in FACT_SIGNALS}
        return PumpSnapshot(
            now.wall,
            self._last_mode,
            register,
            items,
            facts,
            origin=origin,
            outside_c=self._outside(now),
            by=by,
        )

    def _take(self, now: Instant, register: str) -> None:
        """Record the go-live snapshot of the pump state."""
        self.snapshot = self._read_snapshot(now, register, "go_live", None)
        self._store_snapshot()
        LOGGER.warning(
            "go-live: pump-state snapshot recorded (%s; previous mode %s)",
            ", ".join(f"{kind}={value}" for kind, value in self.snapshot.items.items()),
            self._last_mode,
        )

    def _fill(self, now: Instant) -> None:
        """Add settings the snapshot lacked from what the pump reports now."""
        snapshot = self.snapshot
        if snapshot is None:
            return
        read = self._reader(now)
        changed = False
        for kind, signal in VERIFY_SIGNALS.items():
            if snapshot.items.get(kind.value) is None:
                value = reported_int(read(signal))
                if value is not None:
                    snapshot.items[kind.value] = value
                    changed = True
        if changed:
            self._store_snapshot()

    def capture(self, actor: Actor, now: Instant | None = None) -> PumpSnapshot:
        """Capture a snapshot from the pump's current values while ovenbird does not control.

        Parameters
        ----------
        actor
            Who asked.
        now
            Capture time; the runtime clock when omitted.

        Raises
        ------
        ReleaseRefusedError
            ``409`` while ovenbird controls the pump (``controlling``), while a
            go-live snapshot is armed (``in_use``) or a release runs
            (``in_progress``).
        """
        moment = now or self.loop.runtime.clock()
        hold = self.loop.guard.hold
        if hold.releasing or (self.run is not None and not self.run.done):
            raise ReleaseRefusedError(409, "in_progress", "a release is in progress")
        if self.loop.effective_mode is Mode.AUTO and self.loop.adapter is not None:
            raise ReleaseRefusedError(
                409,
                "controlling",
                "ovenbird controls the pump, so its values may be ovenbird's own; the go-live "
                "snapshot is recorded automatically",
            )
        snapshot = self.snapshot
        if snapshot is not None and snapshot.armed and snapshot.origin == "go_live":
            raise ReleaseRefusedError(
                409,
                "in_use",
                "the go-live snapshot has not been restored yet; release control first",
            )
        adapter = self.loop.adapter
        register = adapter.config.setpoint_register if adapter is not None else self.register
        captured = self._read_snapshot(moment, register, "manual", actor.name)
        self.snapshot = captured
        self._store_snapshot()
        if self.config is not None:
            self.config.audit(
                actor, CAPTURE_ACTION, {"items": captured.items, "outside_c": captured.outside_c}
            )
        LOGGER.warning(
            "pump-state snapshot captured by %s in %s (%s)",
            actor.name,
            self.loop.effective_mode.value,
            ", ".join(f"{kind}={value}" for kind, value in self.snapshot.items.items()),
        )
        return self.snapshot

    def _managed(self, kind: IntentKind) -> bool:
        """Return whether the controller manages the setting, so a release must restore it."""
        config = self.loop.controller.config
        match kind:
            case IntentKind.MAX_PUMP_DUTY:
                return config.pump_duty is not None
            case IntentKind.QUIET_MODE:
                return config.quiet is not None
            case _:
                return True

    def _band(self, now: Instant) -> tuple[tuple[int, int, str] | None, float | None]:
        """Return the safety band and the outside temperature now (``None`` when unknown)."""
        outside = self._outside(now)
        if outside is None:
            return None, None
        bounds = self.loop.controller.config.safety.bounds(outside)
        return (bounds.low_int, bounds.high_int, f"at {outside:g} °C outside"), outside

    def start(
        self,
        actor: Actor,
        *,
        rehearsal: bool,
        reason: str | None,
        now: Instant | None = None,
        dry: bool = False,
    ) -> ReleaseRun:
        """Release control: store the pause, restore the snapshot, then pause.

        Parameters
        ----------
        actor
            Who releases control (audited, journalled with every command).
        rehearsal
            Record the release as a rehearsal for the trial checklist.
        reason
            Optional note.
        now
            Current instant; the runtime clock when omitted.
        dry
            Plan the release against the snapshot without sending or pausing
            anything (a dry rehearsal; possible in shadow).

        Returns
        -------
        ReleaseRun
            The run (already done when nothing had to be sent, and always when dry).

        Raises
        ------
        ReleaseRefusedError
            ``409`` while a release runs, without publishing (unless dry), while a
            configuration reset is pending (unless dry) or without a snapshot;
            ``503`` when the pause cannot be stored.
        """
        moment = now or self.loop.runtime.clock()
        self.poll(moment)
        if self.run is not None and not self.run.done:
            raise ReleaseRefusedError(409, "in_progress", "a release is already in progress")
        snapshot = self.snapshot
        adapter = self.loop.adapter
        if not dry and adapter is None:
            raise ReleaseRefusedError(
                409,
                "not_publishing",
                "publishing is not enabled, so ovenbird has written nothing to restore: "
                + "; ".join(self.loop.guard.refusals()),
            )
        hold = self.loop.guard.hold
        if not dry and hold.reset_pending:
            raise ReleaseRefusedError(
                409, "reset_pending", "a configuration reset waits for an admin's acknowledgement"
            )
        if snapshot is None:
            raise ReleaseRefusedError(
                409,
                "no_snapshot",
                "no pump-state snapshot was recorded (it is taken when ovenbird goes live, or "
                "captured by an admin in shadow)",
            )
        by = actor.name if reason is None else f"{actor.name}: {reason}"
        band, outside = self._band(moment)
        run = ReleaseRun(
            moment,
            actor,
            by,
            rehearsal or dry,
            reason,
            snapshot.taken_at,
            hold.paused,
            dry=dry,
            snapshot_origin=snapshot.origin,
            snapshot_age_s=round(snapshot.age_s(moment.wall), 1),
            outside_c=outside,
        )
        if dry:
            return self._plan(run, snapshot, band, moment)
        assert adapter is not None
        if self.config is not None:
            try:
                self.config.store_pause(actor, PAUSE_REASON)
            except sqlite3.Error as exc:
                raise ReleaseRefusedError(
                    503,
                    "storage_failed",
                    f"the pause could not be stored ({exc}); nothing was changed",
                ) from None
        hold.releasing = True
        hold.paused = False
        self.run = run
        try:
            self.facts.set(LAST_KEY, run.to_json(moment))
            self._begin(run, snapshot, band, moment)
        except Exception as exc:
            LOGGER.exception("release of control could not start")
            hold.releasing = False
            hold.paused = True
            for item in run.items:
                if not item.done:
                    item.update("failed", f"the release could not start: {exc}", moment.wall)
            run.finished = moment
            self._store(LAST_KEY, run.to_json())
            raise ReleaseRefusedError(
                503,
                "storage_failed",
                f"the release could not start ({exc}); control is paused, nothing was restored",
            ) from None
        self._finish_if_done(moment)
        return run

    def _begin(
        self,
        run: ReleaseRun,
        snapshot: PumpSnapshot,
        band: tuple[int, int, str] | None,
        moment: Instant,
    ) -> None:
        """Start the release: clear the queue and request a restoring command per setting.

        Parameters
        ----------
        run
            Release run being started.
        snapshot
            Pump state recorded at go-live or by a capture.
        band
            Safety band ``(low, high, description)`` for the setpoint, ``None`` if unknown.
        moment
            Time of the release.
        """
        adapter = self.loop.adapter
        assert adapter is not None
        if self.config is not None:
            self.config.audit(
                run.actor,
                AUDIT_ACTION,
                {"phase": "started", "rehearsal": run.rehearsal, "reason": run.reason},
            )
        adapter.clear_queue(moment, "release of control")
        flying = adapter.in_flight
        read = self._reader(moment)
        for kind, signal in VERIFY_SIGNALS.items():
            value = snapshot.items.get(kind.value)
            reported = reported_int(read(signal))
            item = ReleaseItem(kind, value, reported)
            run.items.append(item)
            if flying is not None and flying.kind == kind and not flying.restore:
                item.waited_for = flying.value
            if value is None:
                item.update("missing", "no value was recorded at go-live", moment.wall)
                continue
            if not self._managed(kind):
                item.update(
                    "not_managed",
                    "ovenbird does not control this setting; left as the pump reports it",
                    moment.wall,
                )
                continue
            target, note = adapter.restore_target(kind, value, band)
            item.clamped = note or None
            if reported == target and item.waited_for is None:
                item.target = target
                item.update("unchanged", f"the pump already reports {target}", moment.wall)
                continue
            try:
                event = adapter.request_restore(kind, value, run.actor.name, moment, read, band)
            except SettingRefusedError as exc:
                item.update("refused", exc.message, moment.wall)
                continue
            item.target = event.value
            detail = event.detail
            if item.waited_for is not None:
                detail += f"; waits for ovenbird's {item.waited_for} still in flight"
            item.update("queued", detail, moment.wall)
        LOGGER.warning("release of control by %s started (rehearsal: %s)", run.by, run.rehearsal)
        self._store(LAST_KEY, run.to_json(moment))

    def _plan(
        self,
        run: ReleaseRun,
        snapshot: PumpSnapshot,
        band: tuple[int, int, str] | None,
        moment: Instant,
    ) -> ReleaseRun:
        """Plan a rehearsal: record per setting what a release would do, without sending.

        Parameters
        ----------
        run
            Release run to fill with one item per setting.
        snapshot
            Pump state recorded at go-live or by a capture.
        band
            Safety band ``(low, high, description)`` for the setpoint, ``None`` if unknown.
        moment
            Time of the release.
        """
        read = self._reader(moment)
        adapter = self.loop.adapter
        limits = adapter.config if adapter is not None else self.limits
        for kind, signal in VERIFY_SIGNALS.items():
            value = snapshot.items.get(kind.value)
            reported = reported_int(read(signal))
            item = ReleaseItem(kind, value, reported)
            run.items.append(item)
            if value is None:
                item.update("missing", "no value was recorded", moment.wall)
                continue
            if not self._managed(kind):
                item.update("not_managed", "ovenbird does not control this setting", moment.wall)
                continue
            if limits is None:
                target, note = value, ""
            else:
                target, note = restore_target(limits, kind, value, band)
            item.target = target
            item.clamped = note or None
            if reported == target:
                item.update("unchanged", f"the pump already reports {target}", moment.wall)
                continue
            if adapter is not None and adapter.hold_reason is not None:
                item.update("refused", f"hold: {adapter.hold_reason}", moment.wall)
                continue
            seen = "nothing" if reported is None else str(reported)
            suffix = f" ({note})" if note else ""
            item.update("planned", f"would restore {seen} → {target}{suffix}", moment.wall)
        run.finished = moment
        body = run.to_json()
        self._store(DRY_KEY, body)
        if self.config is not None:
            self.config.audit(run.actor, AUDIT_ACTION, {"phase": "planned", **body})
        LOGGER.warning("dry rehearsal of a release by %s: %s", run.by, body["outcome"])
        return run

    def _on_event(self, event: CommandEvent) -> None:
        """Update the matching item of the running release from a command event."""
        run = self.run
        if run is None or run.done:
            return
        status = EVENT_STATUS.get(event.status)
        if status is not None and event.detail.startswith(RESTORE_PREFIX):
            for item in run.items:
                if item.kind == event.kind and item.target == event.value and not item.done:
                    item.update(status, event.detail, event.at.wall)
                    self._store(LAST_KEY, run.to_json(event.at))
                    break
        self._finish_if_done(event.at)

    def poll(self, now: Instant) -> None:
        """End a release whose commands did not settle within :attr:`timeout_s`."""
        run = self.run
        if run is None or run.done or now.since(run.started) < self.timeout_s:
            return
        for item in run.items:
            if not item.done:
                item.update(
                    "timeout",
                    f"not settled within {self.timeout_s:.0f} s ({item.status})",
                    now.wall,
                )
        self._finish(run, now)

    def _finish_if_done(self, now: Instant) -> None:
        """Finish the release once every item is done and no command is in flight."""
        run = self.run
        if run is None or run.done or len(run.items) < len(VERIFY_SIGNALS):
            return
        if not all(item.done for item in run.items):
            return
        adapter = self.loop.adapter
        if adapter is not None and adapter.in_flight is not None:
            return
        self._check_values(run, now)
        self._finish(run, now)

    def _check_values(self, run: ReleaseRun, now: Instant) -> None:
        """Downgrade items whose setting the pump no longer reports at the target at the end."""
        read = self._reader(now)
        for item in run.items:
            if item.status not in {"verified", "unchanged"} or item.target is None:
                continue
            reported = reported_int(read(VERIFY_SIGNALS[item.kind]))
            if reported is not None and reported != item.target:
                item.update(
                    "changed",
                    f"the pump reports {reported} at the end, not {item.target}",
                    now.wall,
                )

    def _finish(self, run: ReleaseRun, now: Instant) -> None:
        """Close the run: pause control, store the outcome and clear the interrupted alarm.

        Parameters
        ----------
        run
            Run that has finished.
        now
            Current time.
        """
        hold = self.loop.guard.hold
        hold.paused = True
        hold.releasing = False
        run.finished = now
        snapshot = self.snapshot
        if snapshot is not None and run.ok:
            snapshot.released_at = now.wall
            self._store_snapshot()
        body = run.to_json()
        self._store(LAST_KEY, body)
        if run.rehearsal:
            self._store(REHEARSAL_KEY, body)
        if run.ok:
            self.loop.alarms.clear(AlarmCode.RELEASE_INTERRUPTED, now, "a release finished")
        LOGGER.warning(
            "release of control finished in %.0f s (%s); control is paused%s",
            now.since(run.started),
            body["outcome"],
            "" if run.ok else "; the snapshot stays armed for the values not restored",
        )
        if self.config is not None:
            try:
                self.config.audit(run.actor, AUDIT_ACTION, {"phase": "finished", **body})
            except sqlite3.Error:
                LOGGER.exception("could not audit the end of the release")

    def last(self) -> dict[str, Any] | None:
        """Return the running release, or the last finished one (kept across restarts)."""
        run = self.run
        if run is not None:
            return run.to_json(self.loop.runtime.clock())
        stored = self.facts.get(LAST_KEY)
        return _public(stored) if isinstance(stored, dict) else None

    def last_rehearsal(self) -> dict[str, Any] | None:
        """Return the last finished rehearsal, if any."""
        stored = self.facts.get(REHEARSAL_KEY)
        return _public(stored) if isinstance(stored, dict) else None

    def last_dry_rehearsal(self) -> dict[str, Any] | None:
        """Return the last dry rehearsal (the plan against the snapshot), if any."""
        stored = self.facts.get(DRY_KEY)
        return _public(stored) if isinstance(stored, dict) else None

    def snapshot_payload(self) -> dict[str, Any]:
        """Return the body of ``GET api/v1/control/snapshot``."""
        snapshot = self.snapshot
        now = self.loop.runtime.clock().wall
        return {
            "snapshot": None if snapshot is None else snapshot.to_json(now),
            "armed": snapshot is not None and snapshot.armed,
            "publishing": self.loop.adapter is not None,
            "can_capture": self._capture_refusal() is None,
            "capture_refusal": self._capture_refusal(),
        }

    def _capture_refusal(self) -> str | None:
        """Return the code that refuses a capture now, or ``None`` when it may proceed."""
        if self.loop.guard.hold.releasing or (self.run is not None and not self.run.done):
            return "in_progress"
        if self.loop.effective_mode is Mode.AUTO and self.loop.adapter is not None:
            return "controlling"
        snapshot = self.snapshot
        if snapshot is not None and snapshot.armed and snapshot.origin == "go_live":
            return "in_use"
        return None


def _public(body: dict[str, Any]) -> dict[str, Any]:
    """Return the body with the actor reduced to its public name."""
    return {**body, "by": public_name(body.get("by"))}
