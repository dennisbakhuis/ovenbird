"""The MQTT ingest: subscriptions, session routing, reconnect backoff and capture replay."""

from __future__ import annotations

import asyncio
import gzip
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from ovenbird.backoff import Backoff
from ovenbird.config import MqttInput, Settings
from ovenbird.history.database import Sample
from ovenbird.mqtt import InboundMessage, MqttIngest, subscriptions
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, FakeMqttClient, inbound
from ovenbird_core.capture import CaptureRecord, parse_capture_line

BASE = "panasonic_heat_pump"


class RecordingHistory:
    """History stand-in that records every offered sample."""

    def __init__(self) -> None:
        """Start with no recorded samples."""
        self.samples: list[Sample] = []

    def offer(self, sample: Sample) -> None:
        """Record a sample."""
        self.samples.append(sample)

    def healthy(self) -> bool:
        """Report the history as healthy."""
        return True

    def starting(self) -> bool:
        """Report that the history is not starting."""
        return False


def fixture_records(path: Path) -> Iterator[CaptureRecord]:
    """Yield the parsed capture records of a gzipped capture file, skipping unparsable lines."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = parse_capture_line(line)
            if record is not None:
                yield record


def test_subscriptions_cover_base_and_outside_inputs(
    make_settings: Callable[..., Settings],
) -> None:
    """Subscriptions cover the HeishaMon base topic and the extra inputs outside it."""
    settings = make_settings(
        mqtt_inputs=[
            MqttInput(topic="home/room/temp"),
            MqttInput(topic=f"{BASE}/1wire/abc", signal="floor_temp"),
        ]
    )
    assert subscriptions(settings) == (f"{BASE}/#", "home/room/temp")


async def test_session_routes_messages_and_keeps_retained_flag(
    make_settings: Callable[..., Settings],
) -> None:
    """A session routes pump and extra inputs, keeps retained flags and counts parse errors."""
    clock = FakeClock()
    history = RecordingHistory()
    runtime = Runtime(clock=clock, history=history)
    client = FakeMqttClient(
        [
            inbound(f"{BASE}/main/Outside_Temp", "4", retained=True),
            inbound(f"{BASE}/main/Main_Outlet_Temp", "31.5"),
            inbound(f"{BASE}/main/Operating_Mode_State", "0"),
            inbound(f"{BASE}/commands/SetHeatpump", "1"),
            inbound("home/room/temp", "21.4"),
            inbound(f"{BASE}/main/Outside_Temp", "nonsense"),
        ],
        then="drop",
    )
    settings = make_settings(mqtt_inputs=[MqttInput(topic="home/room/temp", unit="°C")])
    ingest = MqttIngest(settings, runtime, connect=lambda: client)

    reason = await ingest.session()

    assert "connection lost" in reason
    assert client.subscribed == [f"{BASE}/#", "home/room/temp"]
    assert runtime.mqtt_connected is False
    signals = runtime.snapshot()["signals"]
    outside = signals["main/Outside_Temp"]
    assert outside["value"] == 4
    assert outside["retained"] is True
    assert outside["age"] is None
    assert outside["fresh"] is False
    outlet = signals["main/Main_Outlet_Temp"]
    assert outlet["retained"] is False
    assert outlet["fresh"] is True
    assert signals["main/Operating_Mode_State"]["label"] == "heat"
    assert signals["mqtt/home/room/temp"]["value"] == 21.4
    assert signals["mqtt/home/room/temp"]["source"] == "mqtt"
    assert runtime.store.snapshot(clock()).error_counts["main/Outside_Temp"] == 1
    assert outside["reason"] == "malformed: not an integer"
    assert {sample.signal for sample in history.samples if sample.value is not None} == {
        "main/Main_Outlet_Temp",
        "main/Operating_Mode_State",
        "mqtt/home/room/temp",
    }
    assert [sample.signal for sample in history.samples if sample.value is None] == [
        "derived/heat_delivered_w",
        "main/Outside_Temp",
    ]


async def test_connected_flag_during_session(make_settings: Callable[..., Settings]) -> None:
    """The runtime reports MQTT connected during a session and disconnected after cancellation."""
    runtime = Runtime(clock=FakeClock())
    client = FakeMqttClient([inbound(f"{BASE}/main/Outside_Temp", "4")])
    ingest = MqttIngest(make_settings(), runtime, connect=lambda: client)
    task = asyncio.create_task(ingest.session())
    await asyncio.wait_for(client.delivered.wait(), 2)
    assert runtime.mqtt_connected is True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.mqtt_connected is False


async def test_reconnects_with_backoff(make_settings: Callable[..., Settings]) -> None:
    """The ingest reconnects after failed and dropped connections and keeps delivering."""
    runtime = Runtime(clock=FakeClock())
    attempts: list[FakeMqttClient] = []
    connected = asyncio.Event()

    def connect() -> FakeMqttClient:
        """Return a client that fails to connect twice, drops once more and then blocks."""
        client = FakeMqttClient(
            [inbound(f"{BASE}/main/Outside_Temp", str(len(attempts)))],
            fail_connect=len(attempts) < 2,
            then="drop" if len(attempts) < 3 else "block",
        )
        attempts.append(client)
        if len(attempts) >= 4:
            connected.set()
        return client

    backoff = Backoff(initial=0.01, cap=0.02)
    ingest = MqttIngest(make_settings(), runtime, connect=connect, backoff=backoff)
    task = asyncio.create_task(ingest.run())
    await asyncio.wait_for(connected.wait(), 2)
    await asyncio.wait_for(attempts[-1].delivered.wait(), 2)
    assert runtime.mqtt_connected is True
    assert runtime.snapshot()["signals"]["main/Outside_Temp"]["value"] == 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_backoff_doubles_caps_and_resets() -> None:
    """The backoff doubles up to its cap and resets after a stable session."""
    backoff = Backoff(initial=1, cap=8, stable_after=60)
    assert [backoff.next_delay() for _ in range(5)] == [1, 2, 4, 8, 8]
    assert backoff.next_delay(session_s=120) == 1


def test_fixture_replay_through_ingest(
    make_settings: Callable[..., Settings], capture_slice: Path
) -> None:
    """Replaying a recorded capture through the ingest yields live signals and history samples."""
    clock = FakeClock()
    history = RecordingHistory()
    runtime = Runtime(clock=clock, history=history)
    settings = make_settings(
        mqtt_inputs=[MqttInput(topic="climate_manager_capture/room_temp", unit="°C")]
    )
    ingest = MqttIngest(settings, runtime)
    mqtt_records = 0
    for record in fixture_records(capture_slice):
        if record.topic.startswith(("ha/", "snapshot/")):
            continue
        clock.t = record.t
        ingest.ingest(InboundMessage(record.topic, record.payload.encode(), record.retained))
        mqtt_records += 1
    assert ingest.received == mqtt_records > 9_000
    snapshot = runtime.snapshot()
    signals = snapshot["signals"]
    assert snapshot["heishamon"]["alive"] is True
    assert snapshot["heishamon"]["lwt"] == "Online"
    for signal in ("main/Outside_Temp", "main/Main_Outlet_Temp", "main/Compressor_Freq"):
        assert signals[signal]["fresh"] is True
    assert all(view["source"] in {"heishamon", "mqtt"} for view in signals.values())
    assert snapshot["derived"]["heat_delivered_w"]["value"] is not None
    assert snapshot["derived"]["compressor_running"]["reason"] is None
    assert runtime.health()["checks"]["heishamon"] == "alive"
    assert len(history.samples) > 1000
    assert not any(sample.signal.startswith("stats") for sample in history.samples)
