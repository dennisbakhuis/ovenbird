"""Contract test: the MQTT ingest against a real Mosquitto broker.

Uses the ``broker`` fixture of ``conftest.py`` (a private Mosquitto on a free port, or
``OVENBIRD_TEST_MQTT=host:port``); skipped without one. Every run uses its own topic base, so a
shared broker is safe.
"""

from __future__ import annotations

import asyncio
import gzip
import secrets
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import aiomqtt
import pytest

from ovenbird.config import Settings
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird_core.capture import CaptureRecord, parse_capture_line

FIXTURE_BASE = "panasonic_heat_pump"
RECORDS = 3000


def fixture_records(path: Path, limit: int) -> list[CaptureRecord]:
    records: list[CaptureRecord] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = parse_capture_line(line)
            if record is None or not record.topic.startswith(FIXTURE_BASE + "/"):
                continue
            records.append(record)
            if len(records) >= limit:
                break
    return records


@pytest.fixture
async def publisher(broker: tuple[str, int]) -> AsyncIterator[aiomqtt.Client]:
    host, port = broker
    async with aiomqtt.Client(host, port, identifier=f"ovenbird-test-{secrets.token_hex(4)}") as c:
        yield c


async def wait_until(condition: Callable[[], bool], limit: float = 15.0) -> None:
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


async def test_ingest_against_a_real_broker(
    broker: tuple[str, int],
    publisher: aiomqtt.Client,
    make_settings: Callable[..., Settings],
    capture_slice: Path,
) -> None:
    host, port = broker
    base = f"ovenbird_contract_{secrets.token_hex(4)}"
    records = fixture_records(capture_slice, RECORDS)
    retained_topic = f"{base}/main/Outside_Temp"
    await publisher.publish(retained_topic, "4", qos=1, retain=True)
    await publisher.publish(f"{base}/LWT", "Online", qos=1, retain=True)
    settings = make_settings(mqtt_host=host, mqtt_port=port, heishamon_base=base)
    runtime = Runtime()
    ingest = MqttIngest(settings, runtime)
    task = asyncio.create_task(ingest.session())
    try:
        await wait_until(lambda: runtime.mqtt_connected and ingest.received >= 2)
        outside = runtime.snapshot()["signals"]["main/Outside_Temp"]
        assert outside["retained"] is True
        assert outside["fresh"] is False
        assert runtime.snapshot()["heishamon"]["lwt"] == "Online"
        for record in records:
            topic = base + record.topic[len(FIXTURE_BASE) :]
            await publisher.publish(topic, record.payload, qos=1)
        await wait_until(lambda: ingest.received >= len(records) + 2)
        snapshot = runtime.snapshot()
        assert ingest.received == len(records) + 2
        assert snapshot["heishamon"]["alive"] is True
        assert snapshot["signals"]["main/Main_Outlet_Temp"]["fresh"] is True
        assert snapshot["signals"]["main/Main_Outlet_Temp"]["retained"] is False
        assert snapshot["signals"]["main/Outside_Temp"]["retained"] is False
        assert all(view["source"] == "heishamon" for view in snapshot["signals"].values())
        assert runtime.health()["checks"]["mqtt"] == "connected"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await publisher.publish(retained_topic, b"", qos=1, retain=True)
        await publisher.publish(f"{base}/LWT", b"", qos=1, retain=True)
    assert runtime.mqtt_connected is False
