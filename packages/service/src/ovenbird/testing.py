"""Test fakes: clock, MQTT client, pump messages, forecast and a recorded decision journal."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, Self

import aiomqtt

from ovenbird.config import Settings
from ovenbird.history.journal import DecisionRow, write_journal
from ovenbird.history.schema import open_history
from ovenbird.mqtt import InboundMessage
from ovenbird_core import Instant
from ovenbird_core.control import (
    DecisionRecord,
    OvenbirdController,
    control_inputs,
    shift_state,
)
from ovenbird_core.control.synthetic import PlantView, synthetic_snapshot


class FakeClock:
    """A manually advanced clock; both axes follow the unix time ``t``.

    Parameters
    ----------
    t
        Start time in unix seconds.
    """

    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> Instant:
        """Return the current instant."""
        return Instant(self.t, datetime.fromtimestamp(self.t, UTC))

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self.t += seconds


def inbound(topic: str, payload: str, *, retained: bool = False) -> InboundMessage:
    """Build an inbound message with a UTF-8 payload."""
    return InboundMessage(topic, payload.encode("utf-8"), retained)


DIRECT_PUMP: Final = {
    "Outside_Temp": "3",
    "Main_Inlet_Temp": "27.00",
    "Main_Outlet_Temp": "30.50",
    "Compressor_Freq": "30",
    "Defrosting_State": "0",
    "ThreeWay_Valve_State": "0",
    "Heating_Mode": "1",
    "Operating_Mode_State": "0",
    "Z1_Water_Target_Temp": "30",
    "Max_Pump_Duty": "159",
    "Quiet_Mode_Level": "0",
}


def stats_message(base: str = "panasonic_heat_pump", uptime_s: float = 60.0) -> InboundMessage:
    """Build a live HeishaMon ``stats`` message."""
    body = {"uptime": int(uptime_s * 1000), "version": "3.9-test", "total reads": 1}
    return inbound(f"{base}/stats", json.dumps(body))


def pump_messages(base: str = "panasonic_heat_pump", **overrides: str) -> list[InboundMessage]:
    """Live ``main/*`` messages of a heating pump in Direct mode, plus ``stats``.

    Parameters
    ----------
    base
        HeishaMon topic base.
    **overrides
        Payloads replacing :data:`DIRECT_PUMP` entries (by ``main/*`` name).

    Returns
    -------
    list of InboundMessage
        One message per topic, then ``stats``.
    """
    values = {**DIRECT_PUMP, **overrides}
    messages = [inbound(f"{base}/main/{name}", payload) for name, payload in values.items()]
    messages.append(stats_message(base))
    return messages


class FakeMqttClient:
    """Subscribe-only client that replays a list of messages.

    Parameters
    ----------
    messages
        Deliveries to yield after connecting.
    fail_connect
        Raise :class:`aiomqtt.MqttError` on connect.
    then
        After the messages: ``block`` forever, ``drop`` the connection or ``end``.
    """

    def __init__(
        self,
        messages: Iterable[InboundMessage] = (),
        *,
        fail_connect: bool = False,
        then: Literal["block", "drop", "end"] = "block",
    ) -> None:
        self._messages = list(messages)
        self.fail_connect = fail_connect
        self.then = then
        self.subscribed: list[str] = []
        self.connected = False
        self.delivered = asyncio.Event()

    async def __aenter__(self) -> Self:
        """Connect, or fail when configured to."""
        if self.fail_connect:
            raise aiomqtt.MqttError("connection refused")
        self.connected = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect."""
        self.connected = False

    async def subscribe(self, topic: str) -> None:
        """Record the subscription."""
        self.subscribed.append(topic)

    async def messages(self) -> AsyncIterator[InboundMessage]:
        """Yield the messages, then block, drop or end."""
        for message in self._messages:
            yield message
        self.delivered.set()
        if self.then == "drop":
            raise aiomqtt.MqttError("connection lost")
        if self.then == "block":
            await asyncio.Event().wait()


SYNTHETIC_FORECAST_START: Final = datetime(2026, 11, 9, tzinfo=UTC)
SYNTHETIC_FORECAST_HOURS: Final = 96


def synthetic_open_meteo(
    start: datetime = SYNTHETIC_FORECAST_START, hours: int = SYNTHETIC_FORECAST_HOURS
) -> dict[str, object]:
    """Return a deterministic Open-Meteo hourly response (no recorded weather).

    A mild November spell: the daily mean falls from 5 to 2 °C with a 3 K diurnal
    swing peaking at 14:00 UTC, a winter sun between 08:00 and 16:00 UTC behind
    clouds that thicken and clear on a 30-hour cycle, and a light wind. The location
    is the neutral manual location of the dev seed.

    Parameters
    ----------
    start
        First hour (UTC, on the hour).
    hours
        Number of hours.

    Returns
    -------
    dict
        The response body, as ``json.loads`` of an Open-Meteo reply would give it.
    """
    first = int(start.timestamp())
    times = [first + 3600 * k for k in range(hours)]
    temperature: list[float] = []
    radiation: list[float] = []
    cloud: list[int] = []
    wind: list[float] = []
    for k in range(hours):
        hour = (start.hour + k) % 24
        mean = 5.0 - 3.0 * k / max(hours - 1, 1)
        temperature.append(round(mean + 1.5 * math.cos(2 * math.pi * (hour - 14) / 24), 1))
        cover = round(50 + 45 * math.sin(2 * math.pi * k / 30))
        cloud.append(cover)
        sun = max(0.0, math.sin(math.pi * (hour - 8) / 8)) if 8 <= hour <= 16 else 0.0
        radiation.append(round(300.0 * sun * (1 - 0.75 * cover / 100)))
        wind.append(round(3.0 + 2.0 * math.sin(2 * math.pi * k / 19 + 1.0), 2))
    return {
        "latitude": 52.09,
        "longitude": 5.12,
        "generationtime_ms": 0.09,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "timezone_abbreviation": "GMT",
        "elevation": 5.0,
        "hourly_units": {
            "time": "unixtime",
            "temperature_2m": "°C",
            "shortwave_radiation": "W/m²",
            "cloud_cover": "%",
            "wind_speed_10m": "m/s",
        },
        "hourly": {
            "time": times,
            "temperature_2m": temperature,
            "shortwave_radiation": radiation,
            "cloud_cover": cloud,
            "wind_speed_10m": wind,
        },
    }


def synthetic_open_meteo_text() -> str:
    """Return :func:`synthetic_open_meteo` as the committed fixture file's text."""
    return json.dumps(synthetic_open_meteo(), indent=1, ensure_ascii=False) + "\n"


RECORD_START: Final = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
RECORD_ROOM: Final = "room_temperature"


def recorded_plant(index: int) -> PlantView:
    """Return a synthetic plant of minute ``index``: cycling compressor, defrosts, a slow room."""
    hour = index / 60.0
    running = (index // 70) % 3 != 2
    return PlantView(
        outside=float(round(2.0 + 5.0 * math.sin(hour / 5.0))),
        outlet=31.0 + 2.0 * math.sin(index / 9.0) if running else 27.0,
        inlet=27.0,
        compressor_hz=38 if running else 0,
        defrost=1 if index % 131 in (3, 4, 5) else 0,
        water_target=32,
        max_pump_duty=159,
        room=round(21.5 + 0.5 * math.sin(hour / 3.0), 1),
    )


def record_decisions(
    path: Path,
    settings: Settings,
    ticks: int,
    *,
    start: datetime = RECORD_START,
    tick_s: float = 60.0,
    version_at: int | None = None,
    restart_at: int | None = None,
) -> list[DecisionRecord]:
    """Run the controller over :func:`recorded_plant` and store its decisions in ``path``.

    Parameters
    ----------
    path
        History database (created when missing).
    settings
        Settings the controller runs with.
    ticks
        Number of ticks, one per ``tick_s`` from ``start``.
    start
        Wall-clock time of the first tick.
    tick_s
        Tick period.
    version_at
        Tick from which the decisions carry configuration version 2 (1 before).
    restart_at
        Tick at which the service "restarts" (a new monotonic origin).

    Returns
    -------
    list of DecisionRecord
        The recorded decisions, oldest first.
    """
    config = settings.controller_config()
    controller = OvenbirdController(config)
    state = controller.initial_state()
    origin = 5000.0
    rows: list[DecisionRow] = []
    records: list[DecisionRecord] = []
    for index in range(ticks):
        if restart_at is not None and index == restart_at:
            state = shift_state(state, 9000.0)
            origin += 9000.0
        moment = start + timedelta(seconds=index * tick_s)
        now = Instant(origin + index * tick_s, moment)
        snapshot = synthetic_snapshot(now, recorded_plant(index), room_signal=RECORD_ROOM)
        inputs = control_inputs(
            snapshot, room_signal=settings.control_room_signal, room_profile=config.room
        )
        result = controller.step(state, inputs)
        state = result.state
        record = result.decision
        records.append(record)
        version = 1 if version_at is None or index < version_at else 2
        rows.append(
            DecisionRow(
                ts=moment.timestamp(),
                controller=record.controller,
                mode=record.mode.value,
                ladder=record.ladder.value,
                reason=record.reason.value,
                setpoint=record.setpoint,
                record=json.dumps(record.to_json_dict()),
                arbiter="[]",
                commands="[]",
                config_version=version,
            )
        )
    conn = open_history(path)
    try:
        write_journal(conn, rows, [])
    finally:
        conn.close()
    return records
