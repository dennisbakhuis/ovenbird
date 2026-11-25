from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import Settings, load_settings


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in list(os.environ):
        if name.startswith("OVENBIRD_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OVENBIRD_OPTIONS_FILE", str(tmp_path / "no-options.json"))


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "data_dir": tmp_path / "data",
            "ui_dir": tmp_path / "ui",
            "http_port": 0,
        }
        values.update(overrides)
        return load_settings(**values)

    return factory


BROKER_ENV = "OVENBIRD_TEST_MQTT"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"broker at {host}:{port} did not come up")


@pytest.fixture(scope="module")
def broker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, int]]:
    configured = os.environ.get(BROKER_ENV)
    if configured:
        configured_host, _, configured_port = configured.rpartition(":")
        yield configured_host or "localhost", int(configured_port)
        return
    binary = shutil.which("mosquitto")
    if binary is None:
        pytest.skip(f"no mosquitto binary on PATH and {BROKER_ENV} unset")
    port = free_port()
    config = tmp_path_factory.mktemp("mosquitto") / "mosquitto.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n", encoding="utf-8"
    )
    process = subprocess.Popen(  # noqa: S603
        [binary, "-c", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_for_port("127.0.0.1", port)
        yield "127.0.0.1", port
    finally:
        process.terminate()
        process.wait(10)
