"""Bodies of the read-only core routes (:func:`ovenbird.api.app.build_router`).

``health``, ``snapshot``, ``history``, ``decisions``, ``decisions/latest``,
``alarms``, ``commands`` and ``live/ticket``. The CSV forms and the WebSocket are
not modelled here (see :mod:`ovenbird.api.models.ws` for the live messages).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, Number, Scalar, absent
from ovenbird.api.models.control import Alarm, AlarmEvent, ControlStatus, Decision

type SourceName = Literal["heishamon", "ha", "mqtt", "provider"]


class HealthChecks(ApiModel):
    """The component checks of ``health``."""

    mqtt: Literal["connected", "disconnected"]
    heishamon: Literal["alive", "dead"]
    ha: Literal["connected", "disconnected", "disabled"]
    history: Literal["ok", "starting", "error"]
    alarms: str
    weather: str


class Health(ApiModel):
    """``GET health``: liveness, readiness, version and the component checks."""

    live: bool
    ready: bool
    version: str
    api_version: int
    checks: HealthChecks


class HeishamonLink(ApiModel):
    """HeishaMon's heartbeat and last will."""

    alive: bool
    last_heartbeat_age: Number | None
    lwt: Literal["Online", "Offline"] | None


class Signal(ApiModel):
    """One signal of the snapshot: value, provenance and freshness."""

    value: Scalar
    unit: str | None
    label: str | None
    age: Number | None
    held: Number | None
    max_age: Number
    alive_by: str | None
    fresh: bool
    source: SourceName
    retained: bool
    reason: str | None
    source_unit: str | None = absent()


class Derived(ApiModel):
    """A derived signal with the reason it has no value."""

    value: Scalar
    reason: str | None


class DefrostState(ApiModel):
    """The live defrost as the safety monitor latched it at its start.

    ``mode`` is the deice mode the unit picks (1: reverse cycle, water pump running;
    2: hot gas, water pump off by design); ``None`` for an unknown model. Everything
    but ``active`` is ``None`` outside a defrost; ``max_s`` is the ``defrost_stuck``
    limit in effect.
    """

    active: bool
    mode: Literal[1, 2] | None
    since: str | None
    inlet_at_start_c: Number | None
    outside_at_start_c: Number | None
    max_s: Number | None


class Snapshot(ApiModel):
    """``GET snapshot``: every signal, the derived values and the defrost at one instant."""

    at: str
    heishamon: HeishamonLink
    links: dict[str, bool]
    signals: dict[str, Signal]
    derived: dict[str, Derived]
    defrost: DefrostState


class HistorySeries(ApiModel):
    """One signal's points (``[time, value]``)."""

    unit: str | None
    points: list[tuple[str, Scalar]]


class History(ApiModel):
    """``GET history``: the requested signals over a window."""

    from_: str = Field(alias="from")
    to: str
    step: int
    series: dict[str, HistorySeries]


class DecisionsPage(ApiModel):
    """``GET decisions``: decisions in a window."""

    from_: str = Field(alias="from")
    to: str
    limit: int
    decisions: list[Decision]


class DecisionsLatest(ApiModel):
    """``GET decisions/latest``: the newest decision and the control state."""

    decision: Decision | None
    control: ControlStatus | None


class AlarmsPage(ApiModel):
    """``GET alarms``: the active alarms and the events in a window."""

    from_: str = Field(alias="from")
    to: str
    limit: int
    active: list[Alarm]
    events: list[AlarmEvent]


class CommandLogEntry(ApiModel):
    """One journalled command event (journal column order: ``detail`` last)."""

    at: str
    kind: str
    value: int
    status: str
    attempt: int
    topic: str | None
    payload: str | None
    detail: str


class CommandsPage(ApiModel):
    """``GET commands``: command events in a window."""

    from_: str = Field(alias="from")
    to: str
    limit: int
    commands: list[CommandLogEntry]


class LiveTicket(ApiModel):
    """``POST live/ticket``: a single-use pass for the WebSocket."""

    ticket: str
    expires_in: Number
