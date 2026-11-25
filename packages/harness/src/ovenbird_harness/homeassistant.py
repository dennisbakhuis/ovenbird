"""A fake Home Assistant feeding the service's real HA input, and the room device behind it.

:class:`FakeHomeAssistant` keeps HA's view of the configured entities (state,
``last_changed``, ``last_reported``) and drives the service's
:class:`~ovenbird.ha.HaInput` with the messages a real Home Assistant sends over the
WebSocket API: a ``subscribe_entities`` snapshot on connect, compressed change diffs
when a state changes (a report of an unchanged value changes nothing but
``last_reported``, which ``subscribe_entities`` does not forward) and ``get_states``
results every :data:`~ovenbird.ha.REFRESH_INTERVAL_S`. Nothing touches the network.

The room device is a :class:`RoomFeed`: it turns the plant's true room temperature
into the reports a sensor would make. :class:`DeviceFeed` runs the shared sensor
model of the simulator and the evaluation
(:class:`~ovenbird_sim.evaluate.sensors.RoomSensorDevice` on a
:class:`~ovenbird_sim.evaluate.sensors.RoomSensorModel`, by default the example install's
calibrated send-on-delta device) and adds the companion humidity entity (recorded
report times and values when available, the model's humidity otherwise), the
recorded ``unavailable`` periods, and the fault hooks (silence, a dead sensor).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np

from ovenbird.config import Settings
from ovenbird.ha import REFRESH_INTERVAL_S, SUBSCRIBE_ID, HaInput
from ovenbird.runtime import Runtime
from ovenbird_core import SourceKind
from ovenbird_sim.data.datalake import load_state
from ovenbird_sim.evaluate.sensors import (
    RoomSensorDevice,
    RoomSensorModel,
    example_room_sensor,
    install_room_sensor,
)

UNAVAILABLE: Final = "unavailable"
COVER_TOLERANCE_S: Final = 12 * 3600.0
EPSILON: Final = 1e-9


@dataclass(frozen=True, slots=True)
class SensorReport:
    """One report of a device as Home Assistant receives it.

    Parameters
    ----------
    entity_id
        Entity id.
    state
        State text (a number or ``unavailable``).
    """

    entity_id: str
    state: str


class RoomFeed(Protocol):
    """The room device: true room temperature in, Home Assistant reports out."""

    @property
    def units(self) -> Mapping[str, str]:
        """``unit_of_measurement`` per entity."""
        ...

    def reports(self, t: float, room_c: float) -> list[SensorReport]:
        """Return the reports the device makes at ``t`` (unix s) for room ``room_c``."""
        ...

    def mute(self, start: float, end: float) -> None:
        """Make the device silent in ``[start, end)``."""
        ...

    def stick(self, value: float, start: float, end: float) -> None:
        """Report ``value`` once at ``start``, then stay silent until ``end``."""
        ...

    def bias(self, offset_k: float, start: float, end: float) -> None:
        """Read ``offset_k`` above the room in ``[start, end)`` (a sensor failing high)."""
        ...


@dataclass(frozen=True, slots=True)
class ReportTrack:
    """Times and values of a device's reports, replayed as they were recorded.

    Parameters
    ----------
    t
        Report times in unix seconds, ascending.
    v
        Values; ``NaN`` reports ``unavailable``.
    """

    t: np.ndarray
    v: np.ndarray

    def covers(self, start: float, end: float, tolerance_s: float = COVER_TOLERANCE_S) -> bool:
        """Whether the recorded reports span ``[start, end]`` up to ``tolerance_s`` at each end."""
        if self.t.size < 2:
            return False
        return float(self.t[0]) <= start + tolerance_s and float(self.t[-1]) >= end - tolerance_s


def load_track(datalake: Path, entity_id: str) -> ReportTrack | None:
    """Load an entity's recorded reports from the Datalake (``None`` when absent)."""
    if not (datalake / "states").is_dir():
        return None
    series = load_state(datalake, entity_id)
    if series.t.size == 0:
        return None
    return ReportTrack(np.asarray(series.t, dtype=np.float64), np.asarray(series.v))


def dropouts(track: ReportTrack) -> tuple[tuple[float, float], ...]:
    """Return the ``unavailable`` periods of a recorded track (``NaN`` until the next value)."""
    periods: list[tuple[float, float]] = []
    for index in np.flatnonzero(np.isnan(track.v)):
        following = track.t[index + 1 :][np.isfinite(track.v[index + 1 :])]
        end = float(following[0]) if following.size else math.inf
        periods.append((float(track.t[index]), end))
    return tuple(periods)


@dataclass
class DeviceFeed:
    """The room sensor device behind Home Assistant (see the module docstring).

    Parameters
    ----------
    model
        Device model (grid, noise, hysteresis, heartbeat, dropouts, humidity model).
    room_entity, humidity_entity
        Entity ids.
    humidity_track
        Recorded humidity reports; ``None`` uses the model's humidity.
    seed
        Seed of the measurement noise and the modelled humidity.
    """

    model: RoomSensorModel
    room_entity: str
    humidity_entity: str
    humidity_track: ReportTrack | None = None
    seed: int = 0
    muted: list[tuple[float, float]] = field(default_factory=list)
    stuck: list[tuple[float, float]] = field(default_factory=list)
    biased: list[tuple[float, float, float]] = field(default_factory=list)
    device: RoomSensorDevice | None = None
    _rng: np.random.Generator | None = None
    _humidity_index: int = 0
    _unavailable: bool = False
    _offset_k: float = 0.0

    def __post_init__(self) -> None:
        """Start the device."""
        self.device = RoomSensorDevice(self.model, self.seed)
        self._rng = np.random.default_rng(self.seed)

    @property
    def units(self) -> Mapping[str, str]:
        """``unit_of_measurement`` per entity."""
        return {self.room_entity: "°C", self.humidity_entity: "%"}

    def mute(self, start: float, end: float) -> None:
        """Make the device silent (no reports at all) in ``[start, end)``."""
        self.muted.append((start, end))

    def stick(self, value: float, start: float, end: float) -> None:
        """Report ``value`` once at ``start``, then stay silent until ``end`` (a dead sensor)."""
        self.stuck.append((value, start))
        self.mute(start, end)

    def bias(self, offset_k: float, start: float, end: float) -> None:
        """Read ``offset_k`` above the room in ``[start, end)``; the step is reported at once."""
        self.biased.append((offset_k, start, end))

    def _offset(self, t: float) -> float:
        return sum(offset for offset, a, b in self.biased if a <= t < b)

    def _silent(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.muted)

    def _room(self, t: float, room_c: float) -> list[SensorReport]:
        device = self.device
        assert device is not None
        assert self._rng is not None
        if self.stuck and self.stuck[0][1] <= t:
            value, _ = self.stuck.pop(0)
            device.value, device.reported_at = value, t
            return [SensorReport(self.room_entity, f"{value:.1f}")]
        if self._silent(t):
            return []
        if self.model.unavailable(t):
            if self._unavailable:
                return []
            self._unavailable = True
            return [SensorReport(self.room_entity, UNAVAILABLE)]
        resumed, self._unavailable = self._unavailable, False
        offset = self._offset(t)
        stepped, self._offset_k = offset != self._offset_k, offset
        due = device.sampled_at is None or t - device.sampled_at >= self.model.sample_s - EPSILON
        if not due and not resumed and not stepped:
            return []
        draw = float(self._rng.standard_normal())
        sent = device.temperature(t, room_c + offset, draw, force=resumed or stepped)
        return [] if sent is None else [SensorReport(self.room_entity, f"{sent:.1f}")]

    def _humidity(self, t: float) -> list[SensorReport]:
        track = self.humidity_track
        if track is None:
            assert self.device is not None
            value = self.device.humidity(t)
            if value is None or self._silent(t):
                return []
            return [SensorReport(self.humidity_entity, f"{value:.0f}")]
        out: list[SensorReport] = []
        while self._humidity_index < track.t.size and track.t[self._humidity_index] <= t:
            recorded = float(track.v[self._humidity_index])
            self._humidity_index += 1
            if not self._silent(t):
                state = UNAVAILABLE if math.isnan(recorded) else f"{recorded:.1f}"
                out.append(SensorReport(self.humidity_entity, state))
        return out[-1:]

    def reports(self, t: float, room_c: float) -> list[SensorReport]:
        """Return the reports of the device at ``t``."""
        return self._room(t, room_c) + self._humidity(t)


def room_feed(
    start: float,
    end: float,
    room_entity: str,
    humidity_entity: str,
    datalake: Path | None = None,
    model: RoomSensorModel | None = None,
    seed: int = 0,
) -> tuple[DeviceFeed, str]:
    """Return the room device and a note on its sources.

    The temperature is a calibrated send-on-delta device: the recorded install's
    (:func:`~ovenbird_sim.evaluate.sensors.install_room_sensor`) when the Datalake
    covers the span, otherwise the example install's
    (:func:`~ovenbird_sim.evaluate.sensors.example_room_sensor`). The recorded
    ``unavailable`` periods and the recorded humidity reports are replayed when the
    Datalake covers the span, otherwise the model's humidity reports.

    Parameters
    ----------
    start, end
        Span of the run (unix s).
    room_entity, humidity_entity
        Entity ids.
    datalake
        Datalake root with the recorded HA states, if available locally.
    model
        Device model; chosen as above when omitted.
    seed
        Noise seed.
    """
    temperature = load_track(datalake, room_entity) if datalake is not None else None
    humidity = load_track(datalake, humidity_entity) if datalake is not None else None
    recorded = temperature is not None and temperature.covers(start, end)
    base = model or (install_room_sensor() if recorded else example_room_sensor())
    notes = [
        f"room device step {base.step_k} K, offset {base.grid_offset_k} K, "
        f"noise {base.noise_k:.3f} K, hysteresis {base.hysteresis_k:.3f} K"
    ]
    if temperature is not None and temperature.covers(start, end) and not base.dropouts:
        base = replace(base, dropouts=dropouts(temperature))
        notes.append(f"recorded unavailable periods ({len(base.dropouts)})")
    track: ReportTrack | None = None
    if humidity is not None and humidity.covers(start, end):
        track = humidity
        notes.append(f"recorded humidity reports ({humidity.t.size})")
    else:
        notes.append("modelled humidity reports")
    feed = DeviceFeed(base, room_entity, humidity_entity, track, seed)
    return feed, "; ".join(notes)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


@dataclass
class _EntityState:
    state: str
    unit: str | None
    last_changed: float
    last_reported: float

    def compressed(self) -> dict[str, Any]:
        attributes = {} if self.unit is None else {"unit_of_measurement": self.unit}
        return {"s": self.state, "a": attributes, "lc": self.last_changed}

    def full(self, entity_id: str) -> dict[str, Any]:
        attributes = {} if self.unit is None else {"unit_of_measurement": self.unit}
        return {
            "entity_id": entity_id,
            "state": self.state,
            "attributes": attributes,
            "last_changed": _iso(self.last_changed),
            "last_updated": _iso(self.last_changed),
            "last_reported": _iso(self.last_reported),
        }


class FakeHomeAssistant:
    """Home Assistant as the service's WebSocket client sees it, driven synchronously.

    Parameters
    ----------
    settings
        Service settings (HA URL, token and entities).
    runtime
        Runtime of the service the HA input feeds.
    units
        ``unit_of_measurement`` per entity.
    refresh_interval_s
        Seconds between ``get_states`` re-reads.

    Set :attr:`reads_fail` to answer every re-read with an error (the input's link
    then stays unconfirmed); :attr:`failed_reads` counts those answers.
    """

    def __init__(
        self,
        settings: Settings,
        runtime: Runtime,
        units: Mapping[str, str],
        *,
        refresh_interval_s: float = REFRESH_INTERVAL_S,
    ) -> None:
        if settings.ha_url is None or settings.ha_token is None:
            raise ValueError("the fake Home Assistant needs ha_url and ha_token in the settings")
        self.settings = settings
        self.runtime = runtime
        self.units = dict(units)
        self.refresh_interval_s = refresh_interval_s
        self.states: dict[str, _EntityState] = {}
        self.input: HaInput | None = None
        self._last_refresh: float | None = None
        self.events = 0
        self.refreshes = 0
        self.sessions = 0
        self.reads_fail = False
        self.failed_reads = 0

    @property
    def connected(self) -> bool:
        """Whether the service's HA input has a session."""
        return self.input is not None

    def attach(self, runtime: Runtime) -> None:
        """Feed a new service runtime (after an ovenbird restart); the session is dropped."""
        self.disconnect()
        self.runtime = runtime

    def connect(self, t: float) -> None:
        """Open a session: the subscription snapshot, then a ``get_states`` re-read."""
        settings = self.settings
        assert settings.ha_url is not None
        assert settings.ha_token is not None
        self.input = HaInput(
            settings.ha_url, settings.ha_token, settings.ha_subscriptions, self.runtime
        )
        self.input.open_session()
        self.sessions += 1
        self.input.handle({"id": SUBSCRIBE_ID, "type": "result", "success": True, "result": None})
        added = {entity: state.compressed() for entity, state in self.states.items()}
        self._send_event({"a": added})
        self.refresh(t)

    def disconnect(self) -> None:
        """End the session (link down, HA restart)."""
        if self.input is not None:
            self.input.close_session()
        else:
            self.runtime.ha_connected = False
            self.runtime.set_link(SourceKind.HA, up=False)
        self.input = None

    def _send_event(self, event: dict[str, Any]) -> None:
        if self.input is None:
            return
        self.input.handle({"id": SUBSCRIBE_ID, "type": "event", "event": event})
        self.events += 1

    def report(self, report: SensorReport, t: float) -> None:
        """Apply a device report; forward a state change to the subscription."""
        current = self.states.get(report.entity_id)
        unit = self.units.get(report.entity_id)
        if current is None:
            self.states[report.entity_id] = _EntityState(report.state, unit, t, t)
            self._send_event({"a": {report.entity_id: self.states[report.entity_id].compressed()}})
            return
        current.last_reported = t
        if current.state == report.state:
            return
        current.state = report.state
        current.last_changed = t
        self._send_event({"c": {report.entity_id: {"+": {"s": report.state, "lc": t}}}})

    def refresh(self, t: float) -> None:
        """Answer one ``get_states`` re-read with the full states."""
        self._last_refresh = t
        ha = self.input
        if ha is None:
            return
        message_id = ha.expect_states()
        if self.reads_fail:
            error = {"code": "unknown_error", "message": "harness: get_states fails"}
            ha.handle({"id": message_id, "type": "result", "success": False, "error": error})
            self.failed_reads += 1
            return
        result = [state.full(entity) for entity, state in self.states.items()]
        ha.handle({"id": message_id, "type": "result", "success": True, "result": result})
        self.refreshes += 1

    def tick(self, t: float, reports: Sequence[SensorReport] = ()) -> None:
        """Apply the reports at ``t`` and re-read when the refresh interval is over."""
        for item in reports:
            self.report(item, t)
        if self.input is None:
            return
        last = self._last_refresh
        if last is None or t - last >= self.refresh_interval_s - EPSILON:
            self.refresh(t)
