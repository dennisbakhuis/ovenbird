from __future__ import annotations

import asyncio
import functools
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

import ovenbird.__main__ as entry
from ovenbird import __version__
from ovenbird.__main__ import main, run_check, run_until_terminated
from ovenbird.config import Settings
from ovenbird.instance import AlreadyRunningError, InstanceLock, running_endpoint
from ovenbird.service import build_service
from ovenbird.testing import FakeMqttClient, inbound


def test_version_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"ovenbird {__version__}"


def test_check_without_running_service_is_a_self_check(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OVENBIRD_DATA_DIR", str(tmp_path / "data"))
    with caplog.at_level(logging.INFO, logger="ovenbird"):
        assert main(["--check"]) == 0
    assert f"ovenbird {__version__} self-check ok (no service running)" in caplog.messages


def test_check_with_invalid_settings_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVENBIRD_HTTP_HOST", "0.0.0.0")
    assert main(["--check"]) == 2


def test_check_while_starting_fails(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    lock = InstanceLock(settings.data_dir)
    lock.acquire()
    try:
        assert running_endpoint(settings.data_dir) == (True, None)
        assert run_check(settings) == 1
        with pytest.raises(AlreadyRunningError):
            InstanceLock(settings.data_dir).acquire()
    finally:
        lock.release()
    assert running_endpoint(settings.data_dir) == (False, None)


async def test_service_serves_probes_and_stops_cleanly(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings()
    client = FakeMqttClient(
        [
            inbound("panasonic_heat_pump/main/Outside_Temp", "3"),
            inbound("panasonic_heat_pump/stats", '{"uptime": 1000}'),
        ]
    )
    service = build_service(settings, mqtt_connect=lambda: client)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    await asyncio.wait_for(service.server.ready.wait(), 5)
    await asyncio.wait_for(client.delivered.wait(), 5)
    port = service.server.bound_port()
    assert port is not None
    async with httpx2.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
        health = (await http.get("/api/v1/health")).json()
        snapshot = (await http.get("/api/v1/snapshot")).json()
    assert health["live"] is True
    assert health["ready"] is True
    assert health["checks"]["mqtt"] == "connected"
    assert snapshot["signals"]["main/Outside_Temp"]["value"] == 3
    running, endpoint = running_endpoint(settings.data_dir)
    assert running
    assert endpoint is not None
    assert endpoint.port == port
    assert await asyncio.to_thread(run_check, settings) == 0
    stop.set()
    await asyncio.wait_for(task, 10)
    assert running_endpoint(settings.data_dir) == (False, None)
    assert settings.history_path.exists()
    assert not service.writer.is_alive()


async def test_sigterm_stops_the_service(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings()
    monkeypatch.setattr(
        entry, "build_service", functools.partial(build_service, mqtt_connect=FakeMqttClient)
    )
    task = asyncio.create_task(run_until_terminated(settings))
    for _ in range(100):
        if running_endpoint(settings.data_dir)[1] is not None:
            break
        await asyncio.sleep(0.05)
    assert running_endpoint(settings.data_dir)[1] is not None
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, 10)
    assert running_endpoint(settings.data_dir) == (False, None)


async def test_bind_failure_is_reported(make_settings: Callable[..., Settings]) -> None:
    first = build_service(make_settings(), mqtt_connect=FakeMqttClient)
    stop = asyncio.Event()
    task = asyncio.create_task(first.run(stop))
    await asyncio.wait_for(first.server.ready.wait(), 5)
    port = first.server.bound_port()
    other_dir = make_settings().data_dir.parent / "other"
    second = build_service(
        make_settings(http_port=port, data_dir=other_dir), mqtt_connect=FakeMqttClient
    )
    with pytest.raises(ExceptionGroup) as excinfo:
        await asyncio.wait_for(second.run(asyncio.Event()), 10)
    assert excinfo.group_contains(RuntimeError, match="HTTP server failed to start")
    stop.set()
    await asyncio.wait_for(task, 10)
