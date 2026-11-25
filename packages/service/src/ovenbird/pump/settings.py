"""The pump settings page: what HeishaMon reports, and the operator's three writable settings.

:class:`PumpSettings` answers ``GET api/v1/pump/settings`` from the state store (value,
label, unit, age, freshness, whether this model reports the topic at all) and hands an
admin's ``POST api/v1/pump/settings/{id}`` to the command adapter
(:meth:`~ovenbird.control.adapter.CommandAdapter.request_setting`), which owns every
safety rule: the second closed allowlist, refusal instead of clamping, compare-and-set,
no write during a defrost, a DHW run, a hold or shadow, one write at a time, the
rate limits, the daily budget, verification and the journal. Each accepted request
is audited as ``pump_setting``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.control.adapter import OPERATOR_PREFIX, CommandAdapter, Reader, SettingRefusedError
from ovenbird.control.guard import PublishGuard
from ovenbird.history.journal import command_events_of
from ovenbird.runtime import Runtime
from ovenbird_core import (
    CATALOGUE,
    PUMP_SETTINGS,
    HeishaSignal,
    Instant,
    PumpSetting,
    SignalId,
    SignalView,
    ValueKind,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ovenbird.configstore import Actor, ConfigManager

AUDIT_ACTION: Final = "pump_setting"
MAX_COMMENT: Final = 200
LAST_WRITE_LOOKBACK_S: Final = 90 * 86_400.0
OPERATOR: Final = "operator"
CONTROLLER: Final = "controller"
PUMP: Final = "pump"
OWNERS: Final = (OPERATOR, CONTROLLER, PUMP)
REFUSAL_CODES: Final = (
    "unknown_setting",
    "bad_comment",
    "not_an_integer",
    "out_of_range",
    "expect_required",
    "not_publishing",
    "hold",
    "state_unknown",
    "defrost",
    "dhw",
    "not_fresh",
    "value_changed",
    "unchanged",
    "in_flight",
    "rate_limited",
    "day_limit",
    "write_budget",
)


@dataclass(frozen=True, slots=True)
class ReadSetting:
    """A read-only row of the pump settings page.

    Parameters
    ----------
    id
        Row id.
    signal
        ``main/*`` signal it shows.
    owner
        Who sets it: ``controller`` (ovenbird's own intents), ``operator`` (the
        Panasonic remote or the installer) or ``pump`` (a state the pump reports).
    """

    id: str
    signal: SignalId
    owner: str


READ_SETTINGS: Final = (
    ReadSetting("max_pump_duty", HeishaSignal.MAX_PUMP_DUTY, CONTROLLER),
    ReadSetting("quiet_mode_level", HeishaSignal.QUIET_MODE_LEVEL, CONTROLLER),
    ReadSetting("quiet_mode_priority", HeishaSignal.QUIET_MODE_PRIORITY, OPERATOR),
    ReadSetting("powerful_mode_time", HeishaSignal.POWERFUL_MODE_TIME, OPERATOR),
    ReadSetting("heating_control", HeishaSignal.HEATING_CONTROL, OPERATOR),
    ReadSetting("heater_on_outdoor", HeishaSignal.HEATER_ON_OUTDOOR_TEMP, OPERATOR),
    ReadSetting("heater_delay_time", HeishaSignal.HEATER_DELAY_TIME, OPERATOR),
    ReadSetting("heater_start_delta", HeishaSignal.HEATER_START_DELTA, OPERATOR),
    ReadSetting("heater_stop_delta", HeishaSignal.HEATER_STOP_DELTA, OPERATOR),
    ReadSetting("room_heater_state", HeishaSignal.ROOM_HEATER_STATE, OPERATOR),
    ReadSetting("heating_mode", HeishaSignal.HEATING_MODE, OPERATOR),
    ReadSetting("z1_curve_target_high", HeishaSignal.Z1_CURVE_TARGET_HIGH_TEMP, OPERATOR),
    ReadSetting("z1_curve_target_low", HeishaSignal.Z1_CURVE_TARGET_LOW_TEMP, OPERATOR),
    ReadSetting("z1_curve_outside_high", HeishaSignal.Z1_CURVE_OUTSIDE_HIGH_TEMP, OPERATOR),
    ReadSetting("z1_curve_outside_low", HeishaSignal.Z1_CURVE_OUTSIDE_LOW_TEMP, OPERATOR),
    ReadSetting("operating_mode_state", HeishaSignal.OPERATING_MODE_STATE, PUMP),
    ReadSetting("zones_state", HeishaSignal.ZONES_STATE, PUMP),
    ReadSetting("pump_duty", HeishaSignal.PUMP_DUTY, PUMP),
    ReadSetting("pump_flow", HeishaSignal.PUMP_FLOW, PUMP),
    ReadSetting("internal_heater_state", HeishaSignal.INTERNAL_HEATER_STATE, PUMP),
    ReadSetting("error", HeishaSignal.ERROR, PUMP),
)
SETTING_IDS: Final = (*(setting.value for setting in PumpSetting), *(r.id for r in READ_SETTINGS))


def _row(row_id: str, signal: SignalId, view: SignalView | None, owner: str) -> dict[str, Any]:
    spec = CATALOGUE.get(signal)
    supported = view is not None and view.reason is None
    value = view.value if view is not None and supported else None
    label = None
    if spec is not None and spec.kind is ValueKind.ENUM and type(value) is int:
        label = spec.meaning(value)
    return {
        "id": row_id,
        "signal": signal,
        "value": value,
        "unit": spec.unit if spec is not None else None,
        "label": label,
        "fresh": view is not None and view.fresh,
        "age": None if view is None or view.age is None else round(view.age, 1),
        "supported": supported,
        "access": "read",
        "owner": owner,
    }


class PumpSettings:
    """Read the pump settings and pass an admin's writes to the command adapter.

    Parameters
    ----------
    runtime
        State store and clock.
    guard
        Publish guard (why nothing can be written without an adapter).
    adapter
        Command adapter; ``None`` unless the installation permits publishing.
    config
        Configuration manager (audit trail); ``None`` without a store.
    history_path
        ``history.db`` (the last write's status after a restart).
    """

    def __init__(
        self,
        runtime: Runtime,
        guard: PublishGuard,
        adapter: CommandAdapter | None,
        config: ConfigManager | None = None,
        history_path: Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.guard = guard
        self.adapter = adapter
        self.config = config
        self.history_path = history_path
        self.audit_sink: Callable[[Actor, str, dict[str, Any]], None] | None = (
            config.audit if config is not None else None
        )

    def _reader(self, now: Instant) -> Reader:
        store = self.runtime.store
        return lambda signal: store.view(signal, now)

    def refusals(self, now: Instant | None = None) -> list[str]:
        """Return why no pump setting can be written now (empty when writes are possible)."""
        moment = now or self.runtime.clock()
        adapter = self.adapter
        if adapter is None:
            return list(self.guard.refusals()) or ["publishing is not enabled"]
        blocked = adapter.operator_block(self._reader(moment))
        reasons = [] if blocked is None else [blocked[1]]
        busy = adapter.operator_busy()
        if busy is not None:
            reasons.append(f"a write of {busy.value} is in progress")
        return reasons

    def _last_write(self, setting: PumpSetting) -> dict[str, Any] | None:
        if self.adapter is not None:
            write = self.adapter.operator_writes.get(setting)
            if write is not None:
                return write.to_json()
        if self.config is None:
            return None
        found = next(
            (
                event
                for event in self.config.store.latest_audit(AUDIT_ACTION)
                if event.detail.get("setting") == setting.value
            ),
            None,
        )
        if found is None:
            return None
        status = None
        if self.history_path is not None:
            rows = command_events_of(
                self.history_path, [setting.value], found.ts - 1.0, found.ts + LAST_WRITE_LOOKBACK_S
            )
            operator = [row for row in rows if row.detail.startswith(OPERATOR_PREFIX)]
            status = operator[-1].status if operator else None
        return {
            "at": iso_from_unix(found.ts),
            "by": found.actor,
            "from": found.detail.get("from"),
            "to": found.detail.get("to"),
            "status": status,
        }

    def payload(self, now: Instant | None = None) -> dict[str, Any]:
        """Return the body of ``GET api/v1/pump/settings``."""
        moment = now or self.runtime.clock()
        store = self.runtime.store
        refusals = self.refusals(moment)
        settings: list[dict[str, Any]] = []
        for setting, spec in PUMP_SETTINGS.items():
            row = _row(setting.value, spec.signal, store.view(spec.signal, moment), OPERATOR)
            row["unit"] = spec.unit
            row.update(
                access="write",
                command=spec.command,
                min=spec.low,
                max=spec.high,
                last_write=self._last_write(setting),
            )
            settings.append(row)
        for item in READ_SETTINGS:
            settings.append(_row(item.id, item.signal, store.view(item.signal, moment), item.owner))
        model = store.view(HeishaSignal.HEAT_PUMP_MODEL, moment)
        return {
            "writable": not refusals,
            "refusals": refusals,
            "model": model.value if model is not None and model.reason is None else None,
            "settings": settings,
        }

    def write(self, setting_id: str, body: dict[str, Any], actor: Actor) -> dict[str, Any]:
        """Queue an admin's write (``POST api/v1/pump/settings/{id}``).

        Parameters
        ----------
        setting_id
            One of the three writable settings.
        body
            ``{"value": int, "expect": int, "comment"?: str}``.
        actor
            Who writes (audited and journalled).

        Returns
        -------
        dict
            ``{"command": <the queued command event>}``.

        Raises
        ------
        SettingRefusedError
            ``404`` for another id, ``400`` for a bad comment, otherwise as
            :meth:`~ovenbird.control.adapter.CommandAdapter.request_setting`.
        """
        try:
            setting = PumpSetting(setting_id)
        except ValueError:
            raise SettingRefusedError(
                404, "unknown_setting", f"{setting_id!r} is not a writable pump setting"
            ) from None
        comment = body.get("comment")
        if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_COMMENT):
            raise SettingRefusedError(
                400, "bad_comment", f"comment must be a string of at most {MAX_COMMENT} characters"
            )
        comment = (comment.strip() or None) if isinstance(comment, str) else None
        now = self.runtime.clock()
        adapter = self.adapter
        if adapter is None:
            reasons = list(self.guard.refusals()) or ["publishing is not enabled"]
            raise SettingRefusedError(409, "not_publishing", "; ".join(reasons))
        event = adapter.request_setting(
            setting,
            body.get("value"),
            body.get("expect"),
            actor.name,
            now,
            self._reader(now),
            comment=comment,
        )
        write = adapter.operator_writes[setting]
        if self.audit_sink is not None:
            detail: dict[str, Any] = {
                "setting": setting.value,
                "from": write.from_value,
                "to": write.to,
            }
            if comment is not None:
                detail["comment"] = comment
            self.audit_sink(actor, AUDIT_ACTION, detail)
        return {"command": event.to_json()}
