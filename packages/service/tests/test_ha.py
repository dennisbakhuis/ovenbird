from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import SecretStr
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosedError

from ovenbird.backoff import Backoff
from ovenbird.ha import (
    AREA_REGISTRY_ID,
    CONFIG_ID,
    DEVICE_REGISTRY_ID,
    ENTITY_REGISTRY_ID,
    SUBSCRIBE_ID,
    EntityState,
    HaInput,
    websocket_url,
)
from ovenbird.runtime import Runtime
from ovenbird_core.control.stove import _fresh_temperature

TOKEN = "good-token"
ROOM = "sensor.living_room_temperature"
POWER = "sensor.pv_power"


SESSION_TYPES = [
    "get_config",
    "config/entity_registry/list_for_display",
    "config/device_registry/list",
    "config/area_registry/list",
]


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.sessions = 0
        self.close_after_events = True
        self.subscribed = asyncio.Event()
        self.now = time.time()
        self.full_states: list[Any] | None = None
        self.state_reads = 0
        self.read_answered = asyncio.Event()
        self.temperature_unit = "°C"
        self.registry: dict[str, Any] = {}

    async def handler(self, ws: ServerConnection) -> None:
        self.sessions += 1
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.11.0"}))
        auth = json.loads(await ws.recv())
        self.received.append(auth)
        if auth.get("access_token") != TOKEN:
            await ws.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token"}))
            return
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.11.0"}))
        async for raw in ws:
            request = json.loads(raw)
            self.received.append(request)
            kind = request["type"]
            if kind == "get_config":
                config = {"unit_system": {"temperature": self.temperature_unit}, "version": "x"}
                await ws.send(json.dumps(result(request["id"], config)))
            elif kind in self.registry:
                await ws.send(json.dumps(result(request["id"], self.registry[kind])))
            elif kind in SESSION_TYPES:
                error = {"id": request["id"], "type": "result", "success": False, "error": {}}
                await ws.send(json.dumps(error))
            elif kind == "subscribe_entities":
                await self.subscription(ws, request["id"])
                if self.close_after_events and self.full_states is None:
                    return
            elif kind == "get_states" and self.full_states is not None:
                self.state_reads += 1
                await ws.send(json.dumps(result(request["id"], self.full_states)))
                self.read_answered.set()

    async def subscription(self, ws: ServerConnection, sub_id: int) -> None:
        await ws.send(json.dumps({"id": sub_id, "type": "result", "success": True, "result": None}))
        initial = {
            ROOM: {
                "s": "21.4",
                "a": {"unit_of_measurement": "°C", "device_class": "temperature"},
                "lc": self.now - 600,
                "lu": self.now - 600,
                "lr": self.now - 95,
            },
            POWER: {"s": "unavailable", "a": {"unit_of_measurement": "W"}, "lc": self.now - 10},
            "sensor.not_requested": {"s": "1", "a": {}, "lc": self.now},
        }
        await ws.send(json.dumps({"id": sub_id, "type": "event", "event": {"a": initial}}))
        change = {
            ROOM: {"+": {"s": "22.1", "lc": self.now - 5}},
            POWER: {"+": {"s": "1450", "lu": self.now}},
        }
        await ws.send(json.dumps([{"id": sub_id, "type": "event", "event": {"c": change}}]))
        await ws.send("not json")
        self.subscribed.set()


def result(message_id: int, value: Any) -> dict[str, Any]:
    return {"id": message_id, "type": "result", "success": True, "result": value}


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


@pytest.fixture
async def fake_ha() -> AsyncIterator[tuple[FakeHomeAssistant, str]]:
    fake = FakeHomeAssistant()
    server: Server
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield fake, f"http://127.0.0.1:{port}"


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://ha.local:8123", "ws://ha.local:8123/api/websocket"),
        ("http://ha.local:8123/", "ws://ha.local:8123/api/websocket"),
        ("https://ha.example", "wss://ha.example/api/websocket"),
        ("HTTPS://ha.example:8443", "wss://ha.example:8443/api/websocket"),
        ("https://proxy.example/some/path/", "wss://proxy.example/some/path/api/websocket"),
        ("http://192.168.1.5:8123?x=1#y", "ws://192.168.1.5:8123/api/websocket"),
        ("ws://ha.local:8123/api/websocket", "ws://ha.local:8123/api/websocket"),
        ("wss://ha.example/prefix", "wss://ha.example/prefix/api/websocket"),
        ("http://supervisor/core", "ws://supervisor/core/websocket"),
        ("http://supervisor/core/", "ws://supervisor/core/websocket"),
        ("ws://supervisor/core/websocket", "ws://supervisor/core/websocket"),
        ("http://supervisor", "ws://supervisor/api/websocket"),
    ],
)
def test_websocket_url(base: str, expected: str) -> None:
    assert websocket_url(base) == expected


@pytest.mark.parametrize("bad", ["ftp://ha", "http://", "ha.local:8123"])
def test_websocket_url_rejects_non_http_urls(bad: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        websocket_url(bad)


def test_entity_state_from_full_state() -> None:
    state = EntityState.from_full(
        {
            "entity_id": ROOM,
            "state": "21.5",
            "attributes": {"unit_of_measurement": "°C"},
            "last_changed": "2026-11-14T10:00:00+00:00",
            "last_updated": "2026-11-14T10:00:00+00:00",
            "last_reported": "2026-11-14T11:00:00+00:00",
        }
    )
    assert state.state == "21.5"
    assert state.unit == "°C"
    assert state.last_updated == datetime(2026, 11, 14, 10, tzinfo=UTC).timestamp()
    assert state.last_reported == datetime(2026, 11, 14, 11, tzinfo=UTC).timestamp()
    bare = EntityState.from_full({"state": "on", "last_changed": "2026-11-14T10:00:00+00:00"})
    assert bare.last_reported == bare.last_updated


def test_entity_state_diffs() -> None:
    state = EntityState.from_compressed({"s": "1", "a": {"unit_of_measurement": "W"}, "lc": 10.0})
    assert (state.last_updated, state.last_reported, state.unit) == (10.0, 10.0, "W")
    state.apply_diff({"+": {"lr": 20.0}})
    assert (state.state, state.last_updated, state.last_reported) == ("1", 10.0, 20.0)
    state.apply_diff({"+": {"s": "2", "lu": 30.0}, "-": {"a": ["unit_of_measurement"]}})
    assert (state.state, state.last_updated, state.last_reported, state.unit) == (
        "2",
        30.0,
        30.0,
        None,
    )


async def test_subscribes_and_applies_states(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    fake.close_after_events = False
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr(TOKEN), (ROOM, POWER), runtime)
    assert TOKEN not in repr(client)
    task = asyncio.create_task(client.session())
    await asyncio.wait_for(fake.subscribed.wait(), 5)
    for _ in range(100):
        if client.readings >= 4:
            break
        await asyncio.sleep(0.01)
    assert runtime.ha_connected is True
    assert runtime.health()["checks"]["ha"] == "connected"
    signals = runtime.snapshot()["signals"]
    room = signals[f"ha/{ROOM}"]
    assert room["value"] == 22.1
    assert room["unit"] == "°C"
    assert room["source"] == "ha"
    assert room["fresh"] is True
    assert 4.0 <= room["age"] < 30.0
    assert signals[f"ha/{POWER}"]["value"] == 1450.0
    assert "ha/sensor.not_requested" not in signals
    kinds = [message["type"] for message in fake.received]
    assert kinds[:6] == ["auth", *SESSION_TYPES, "subscribe_entities"]
    assert set(kinds[6:]) <= {"get_states"}
    assert fake.received[5]["entity_ids"] == [ROOM, POWER]
    assert client.temperature_unit == "°C"
    assert client.ha_version == "x"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.ha_connected is False
    assert runtime.health()["checks"]["ha"] == "disconnected"


async def test_replayed_state_keeps_its_age(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    fake.now = time.time() - 3600
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr(TOKEN), (ROOM,), runtime)
    reason = await asyncio.wait_for(client.session(), 5)
    assert reason == "closed by server"
    room = runtime.snapshot()["signals"][f"ha/{ROOM}"]
    assert room["age"] > 3000
    assert room["fresh"] is False


async def test_reconnects_after_server_closes(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    runtime = Runtime(ha_enabled=True)
    client = HaInput(
        url, SecretStr(TOKEN), (ROOM,), runtime, backoff=Backoff(initial=0.01, cap=0.02)
    )
    task = asyncio.create_task(client.run())
    for _ in range(300):
        if fake.sessions >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.sessions >= 3
    assert runtime.snapshot()["signals"][f"ha/{ROOM}"]["value"] == 22.1


async def test_rejected_token_is_reported(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr("wrong"), (ROOM,), runtime)
    reason = await asyncio.wait_for(client.session(), 5)
    assert reason.startswith("authentication rejected")
    assert "wrong" not in reason
    assert [message["type"] for message in fake.received] == ["auth"]
    assert runtime.snapshot()["signals"] == {}


async def test_unreachable_server_is_a_connection_failure() -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput("http://127.0.0.1:9", SecretStr(TOKEN), (ROOM,), runtime)
    reason = await asyncio.wait_for(client.session(), 5)
    assert reason.startswith("connection lost")
    assert runtime.ha_connected is False


async def test_get_states_confirms_a_stable_value(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    fake.close_after_events = False
    fake.now = time.time() - 3600
    fake.full_states = [
        {
            "entity_id": ROOM,
            "state": "22.1",
            "attributes": {"unit_of_measurement": "°C"},
            "last_changed": iso(fake.now),
            "last_updated": iso(fake.now),
            "last_reported": iso(time.time() - 20),
        },
        {"entity_id": "sensor.not_requested", "state": "5", "attributes": {}},
        "garbage",
    ]
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr(TOKEN), (ROOM,), runtime, refresh_interval=0.05)
    task = asyncio.create_task(client.session())
    for _ in range(300):
        if fake.state_reads >= 2 and client.refreshes >= 2:
            break
        await asyncio.sleep(0.01)
    room = runtime.snapshot()["signals"][f"ha/{ROOM}"]
    assert room["value"] == 22.1
    assert room["fresh"] is True
    assert 15.0 <= room["age"] < 60.0
    assert "ha/sensor.not_requested" not in runtime.snapshot()["signals"]
    assert {message["type"] for message in fake.received} == {
        "auth",
        *SESSION_TYPES,
        "subscribe_entities",
        "get_states",
    }
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_get_states_unavailable_invalidates(fake_ha: tuple[FakeHomeAssistant, str]) -> None:
    fake, url = fake_ha
    fake.close_after_events = False
    fake.full_states = [
        {
            "entity_id": ROOM,
            "state": "unavailable",
            "attributes": {},
            "last_changed": iso(time.time()),
            "last_updated": iso(time.time()),
            "last_reported": iso(time.time()),
        }
    ]
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr(TOKEN), (ROOM,), runtime, refresh_interval=0.05)
    task = asyncio.create_task(client.session())
    for _ in range(300):
        if client.refreshes >= 1:
            break
        await asyncio.sleep(0.01)
    room = runtime.snapshot()["signals"][f"ha/{ROOM}"]
    assert room["value"] == 22.1
    assert room["fresh"] is False
    assert room["reason"] == "unavailable: entity has no state"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_failed_get_states_is_ignored() -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput("http://ha.local:8123", SecretStr(TOKEN), (ROOM,), runtime)
    client._pending_reads.add(7)
    assert client.handle({"id": 7, "type": "result", "success": False, "error": {}}) is False
    assert client.refreshes == 0
    assert runtime.snapshot()["signals"] == {}


class FlakyWebSocket:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)


async def test_refresh_loop_survives_unexpected_errors() -> None:
    client = HaInput(
        "http://ha", SecretStr(TOKEN), (ROOM,), Runtime(ha_enabled=True), refresh_interval=0.05
    )
    ws = FlakyWebSocket([RuntimeError("boom"), TypeError("odd")])
    task = asyncio.create_task(client._refresh_loop(cast(Any, ws)))
    for _ in range(300):
        if len(ws.sent) >= 2:
            break
        await asyncio.sleep(0.01)
    assert len(ws.sent) >= 2
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_refresh_loop_ends_when_the_connection_closes() -> None:
    client = HaInput("http://ha", SecretStr(TOKEN), (ROOM,), Runtime(ha_enabled=True))
    ws = FlakyWebSocket([ConnectionClosedError(None, None)])
    await asyncio.wait_for(client._refresh_loop(cast(Any, ws)), 2)
    assert client._pending_reads == set()


def test_full_states_ignore_unrelated_entities(caplog: pytest.LogCaptureFixture) -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput("http://ha", SecretStr(TOKEN), (ROOM,), runtime)
    states = [
        {"entity_id": ROOM, "state": "20", "attributes": {}, "last_changed": iso(time.time())},
        {"entity_id": "sensor.other", "state": "1", "attributes": {}},
    ]
    with caplog.at_level("DEBUG", logger="ovenbird.ha"):
        client._apply_full_states({"type": "result", "success": True, "result": states})
    assert client.readings == 1
    assert set(client._states) == {ROOM}
    assert any("2 states, 1 configured" in record.message for record in caplog.records)


ROOM_SIGNAL = f"ha/{ROOM}"
CLIMATE = "climate.living_room"
CLIMATE_SIGNAL = f"ha/{CLIMATE}#current_temperature"


def unit_client(
    runtime: Runtime, temperature_unit: str | None, *, attributes: tuple[tuple[str, str], ...] = ()
) -> HaInput:
    client = HaInput(
        "http://ha",
        SecretStr(TOKEN),
        (ROOM,),
        runtime,
        attributes=attributes,
        temperature=frozenset({ROOM_SIGNAL, CLIMATE_SIGNAL}),
    )
    client.open_session()
    if temperature_unit is not None:
        client.handle(result(CONFIG_ID, {"unit_system": {"temperature": temperature_unit}}))
    return client


def add(client: HaInput, entity_id: str, state: str, attributes: dict[str, Any]) -> None:
    now = time.time()
    data = {"s": state, "a": attributes, "lc": now, "lu": now, "lr": now}
    client.handle({"id": SUBSCRIBE_ID, "type": "event", "event": {"a": {entity_id: data}}})


@pytest.mark.parametrize(
    ("state", "unit", "celsius"),
    [("71.6", "°F", 22.0), ("295.15", "K", 22.0), ("21.5", "°C", 21.5)],
)
def test_temperatures_reach_the_store_in_celsius(state: str, unit: str, celsius: float) -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, "°F")
    add(client, ROOM, state, {"unit_of_measurement": unit})
    view = runtime.snapshot()["signals"][ROOM_SIGNAL]
    assert view["value"] == pytest.approx(celsius)
    assert view["unit"] == "°C"
    assert view["fresh"] is True
    assert view.get("source_unit") == (None if unit == "°C" else unit)


@pytest.mark.parametrize("unit", [None, "degrees"])
def test_missing_or_unknown_unit_is_accepted_with_a_metric_system(unit: str | None) -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, "°C")
    add(client, ROOM, "21.4", {} if unit is None else {"unit_of_measurement": unit})
    view = runtime.snapshot()["signals"][ROOM_SIGNAL]
    assert (view["value"], view["fresh"], view["reason"]) == (21.4, True, None)


@pytest.mark.parametrize(("system", "word"), [("°F", "not metric"), (None, "unknown")])
def test_missing_unit_is_refused_without_a_metric_system(system: str | None, word: str) -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, system)
    add(client, ROOM, "70.5", {})
    view = runtime.snapshot()["signals"][ROOM_SIGNAL]
    assert view["fresh"] is False
    assert view["reason"].startswith("unit: no temperature unit")
    assert word in view["reason"]
    assert runtime.store.snapshot(runtime.clock()).fresh_value(ROOM_SIGNAL) is None


def test_a_refused_value_names_its_own_signal() -> None:
    garden = "sensor.garden_temperature"
    runtime = Runtime(ha_enabled=True)
    client = HaInput(
        "http://ha",
        SecretStr(TOKEN),
        (garden,),
        runtime,
        temperature=frozenset({f"ha/{garden}"}),
    )
    client.open_session()
    client.handle(result(CONFIG_ID, {"unit_system": {"temperature": "°F"}}))
    add(client, garden, "41.0", {})
    reason = runtime.snapshot()["signals"][f"ha/{garden}"]["reason"]
    assert reason.endswith(f"; ha/{garden} is not used as a temperature")
    assert "room" not in reason


def test_a_late_metric_config_accepts_the_refused_value() -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, None)
    add(client, ROOM, "21.0", {})
    assert runtime.snapshot()["signals"][ROOM_SIGNAL]["fresh"] is False
    client.handle(result(CONFIG_ID, {"unit_system": {"temperature": "°C"}}))
    view = runtime.snapshot()["signals"][ROOM_SIGNAL]
    assert (view["value"], view["fresh"], view["reason"]) == (21.0, True, None)


def test_a_signal_that_is_no_room_input_keeps_its_unit_rule_free() -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput("http://ha", SecretStr(TOKEN), (ROOM,), runtime)
    client.open_session()
    add(client, ROOM, "55", {})
    assert runtime.snapshot()["signals"][ROOM_SIGNAL]["fresh"] is True


@pytest.mark.parametrize("state", ["warm", "nan", "1e999"])
def test_garbage_room_values_are_no_numbers(state: str) -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, "°C")
    add(client, ROOM, state, {"unit_of_measurement": "°F"})
    view = runtime.snapshot()["signals"][ROOM_SIGNAL]
    assert view["value"] == state
    assert runtime.store.snapshot(runtime.clock()).fresh_value(ROOM_SIGNAL) == state


def test_refused_values_never_reach_history() -> None:
    offered: list[Any] = []

    class Sink:
        def offer(self, sample: Any) -> None:
            offered.append(sample)

        def healthy(self) -> bool:
            return True

        def starting(self) -> bool:
            return False

    runtime = Runtime(history=Sink(), ha_enabled=True)
    client = unit_client(runtime, "°F")
    add(client, ROOM, "70.5", {})
    assert [sample.value for sample in offered] == [None]


def test_thermostat_room_temperature_comes_from_its_attribute() -> None:
    runtime = Runtime(ha_enabled=True)
    client = unit_client(runtime, "°F", attributes=((CLIMATE, "current_temperature"),))
    assert client.subscription == (ROOM, CLIMATE)
    add(client, CLIMATE, "heat", {"current_temperature": 68, "temperature": 70})
    signals = runtime.snapshot()["signals"]
    assert f"ha/{CLIMATE}" not in signals
    view = signals[CLIMATE_SIGNAL]
    assert view["value"] == pytest.approx(20.0)
    assert (view["unit"], view["source_unit"], view["fresh"]) == ("°C", "°F", True)
    client.handle(
        {
            "id": SUBSCRIBE_ID,
            "type": "event",
            "event": {"c": {CLIMATE: {"+": {"a": {"current_temperature": 69.8}}}}},
        }
    )
    assert runtime.snapshot()["signals"][CLIMATE_SIGNAL]["value"] == pytest.approx(21.0)
    add(client, CLIMATE, "unavailable", {})
    view = runtime.snapshot()["signals"][CLIMATE_SIGNAL]
    assert view["reason"] == "unavailable: entity has no state"


def test_registry_gives_areas_and_devices() -> None:
    client = HaInput("http://ha", SecretStr(TOKEN), (), Runtime(ha_enabled=True))
    entities = {"entities": [{"ei": ROOM, "di": "dev1"}, {"ei": POWER, "ai": "garage"}, {}]}
    client.handle(result(ENTITY_REGISTRY_ID, entities))
    client.handle(result(DEVICE_REGISTRY_ID, [{"id": "dev1", "area_id": "living"}]))
    client.handle(result(AREA_REGISTRY_ID, [{"area_id": "living", "name": "Living room"}]))
    assert (client.area_of(ROOM), client.device_of(ROOM)) == ("Living room", "dev1")
    assert (client.area_of(POWER), client.device_of(POWER)) == ("garage", None)
    assert client.area_of("sensor.unknown") is None
    client.handle({"id": DEVICE_REGISTRY_ID, "type": "result", "success": False, "error": {}})
    assert client.area_of(ROOM) == "Living room"


async def test_without_entities_nothing_is_subscribed(
    fake_ha: tuple[FakeHomeAssistant, str],
) -> None:
    fake, url = fake_ha
    fake.full_states = [{"entity_id": "climate.x", "state": "heat", "attributes": {}}]
    runtime = Runtime(ha_enabled=True)
    client = HaInput(url, SecretStr(TOKEN), (), runtime, refresh_interval=0.05)
    task = asyncio.create_task(client.session())
    await asyncio.wait_for(fake.read_answered.wait(), 5)
    for _ in range(100):
        if client.refreshes:
            break
        await asyncio.sleep(0.01)
    assert "subscribe_entities" not in [message["type"] for message in fake.received]
    assert set(client.index) == {"climate.x"}
    assert runtime.ha_connected is True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_input_waits_until_configured_and_follows_changes(
    fake_ha: tuple[FakeHomeAssistant, str],
) -> None:
    fake, url = fake_ha
    fake.close_after_events = False
    runtime = Runtime()
    client = HaInput(None, None, (), runtime, backoff=Backoff(initial=0.01, cap=0.02))
    assert not client.configured
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    assert fake.sessions == 0
    assert client.configure(url, SecretStr(TOKEN), (ROOM,)) is True
    await asyncio.wait_for(fake.subscribed.wait(), 5)
    assert fake.sessions == 1
    assert client.configure(url, SecretStr(TOKEN), (ROOM,)) is False
    fake.subscribed.clear()
    assert client.configure(url, SecretStr(TOKEN), (ROOM, POWER)) is True
    await asyncio.wait_for(fake.subscribed.wait(), 5)
    assert fake.sessions == 2
    subscriptions = [m for m in fake.received if m["type"] == "subscribe_entities"]
    assert subscriptions[-1]["entity_ids"] == [ROOM, POWER]
    assert client.configure(None, None, (ROOM,)) is True
    for _ in range(200):
        if not runtime.ha_connected:
            break
        await asyncio.sleep(0.01)
    assert runtime.ha_connected is False
    await asyncio.sleep(0.05)
    assert fake.sessions == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_new_temperature_inputs_reapply_known_states() -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput("http://ha", SecretStr(TOKEN), (ROOM,), runtime)
    client.open_session()
    add(client, ROOM, "70.5", {})
    assert runtime.snapshot()["signals"][ROOM_SIGNAL]["fresh"] is True
    reconnect = client.configure(
        "http://ha", SecretStr(TOKEN), (ROOM,), temperature=frozenset({ROOM_SIGNAL})
    )
    assert reconnect is False
    assert runtime.snapshot()["signals"][ROOM_SIGNAL]["fresh"] is False


def test_a_fahrenheit_stove_reference_counts_as_a_celsius_temperature() -> None:
    runtime = Runtime(ha_enabled=True)
    client = HaInput(
        "http://ha",
        SecretStr(TOKEN),
        ("sensor.hall",),
        runtime,
        temperature=frozenset({"ha/sensor.hall"}),
    )
    client.open_session()
    add(client, "sensor.hall", "64.4", {"unit_of_measurement": "°F"})
    view = runtime.store.view("ha/sensor.hall", runtime.clock())
    assert _fresh_temperature(view) == pytest.approx(18.0)
