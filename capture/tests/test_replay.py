from __future__ import annotations

from pathlib import Path

import pytest

from climate_manager_capture.capture import CaptureReader, CaptureWriter, Record
from climate_manager_capture.replay import (
    CommandMode,
    ReplayConfig,
    Replayer,
    ReplayScheduler,
    UnsafeBrokerError,
    _build_argparser,
    check_broker,
    config_from_args,
)
from climate_manager_capture.testing import FakeClock

BASE = "panasonic_heat_pump"


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    def __call__(self, topic: str, payload: str, retain: bool) -> None:
        self.published.append((topic, payload, retain))

    def payloads(self, topic: str) -> list[str]:
        return [p for t, p, _ in self.published if t == topic]


def _records(t0: float) -> list[Record]:
    return [
        Record(t0, f"{BASE}/main/Outside_Temp", "3", retained=True),
        Record(t0, f"{BASE}/main/Z1_Heat_Request_Temp", "35", retained=True),
        Record(t0, f"{BASE}/LWT", "Offline", retained=True),
        Record(t0 + 1, f"{BASE}/LWT", "Online"),
        Record(t0 + 5, f"{BASE}/stats", "{}"),
        Record(t0 + 10, f"{BASE}/commands/SetZ1HeatRequestTemperature", "36"),
        Record(t0 + 13, f"{BASE}/main/Z1_Heat_Request_Temp", "36"),
        Record(t0 + 20, f"{BASE}/main/Outside_Temp", "2"),
        Record(t0 + 20, "climate_manager_capture/room_temp", "20.4"),
        Record(t0 + 300, f"{BASE}/main/Z1_Heat_Request_Temp", "36"),
        Record(t0 + 300, f"{BASE}/main/Outside_Temp", "2"),
    ]


@pytest.fixture
def capture(tmp_path: Path) -> CaptureReader:
    writer = CaptureWriter(tmp_path, "c", clock=FakeClock(1_700_000_000))
    for record in _records(1_700_000_000):
        writer.write(record)
    writer.close()
    return CaptureReader(tmp_path / "c")


def _run(
    reader: CaptureReader,
    clock: FakeClock,
    broker: FakeBroker,
    **overrides: object,
) -> Replayer:
    config = ReplayConfig(capture=reader.path, speed=None, **overrides)  # type: ignore[arg-type]
    replayer = Replayer(reader, config, broker, clock=clock, sleep=clock.advance)
    replayer.run()
    return replayer


def test_scheduler_due_times(clock: FakeClock) -> None:
    records = [Record(100, "a", "1"), Record(110, "a", "2"), Record(130, "a", "3")]
    due = [d for d, _ in ReplayScheduler(10.0, clock).schedule(records)]
    assert due == [1000.0, 1001.0, 1003.0]
    due = [d for d, _ in ReplayScheduler(1.0, clock).schedule(records)]
    assert due == [1000.0, 1010.0, 1030.0]
    due = [d for d, _ in ReplayScheduler(None, clock).schedule(records)]
    assert due == [1000.0, 1000.0, 1000.0]
    with pytest.raises(ValueError, match="positive"):
        ReplayScheduler(0, clock)


def test_replay_waits_for_due_time(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    config = ReplayConfig(capture=capture.path, speed=10.0, prime=False)
    replayer = Replayer(capture, config, broker, clock=clock, sleep=clock.advance)
    replayer.run()
    assert clock.now == pytest.approx(1000.0 + 30.0, abs=0.2)


def test_prime_publishes_snapshot_then_offline(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    replayer = _run(capture, clock, broker, start="+15", drop=frozenset({"stats"}))
    primed = broker.published[: len(broker.published) - replayer.stats.published]
    assert (f"{BASE}/main/Z1_Heat_Request_Temp", "36", True) in primed
    assert (f"{BASE}/main/Outside_Temp", "3", True) in primed
    assert primed[-1] == (f"{BASE}/LWT", "Offline", True)
    assert not any("commands" in t for t, _, _ in primed)


def test_ignore_mode_drops_commands_and_stats(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    replayer = _run(capture, clock, broker, commands=CommandMode.IGNORE, prime=False)
    topics = [t for t, _, _ in broker.published]
    assert not any("commands" in t for t in topics)
    assert not any(t.endswith("/stats") for t in topics)
    assert ("climate_manager_capture/room_temp", "20.4", True) in broker.published
    assert (f"{BASE}/LWT", "Online", False) in broker.published
    assert replayer.stats.dropped == 2
    assert replayer.stats.published == 9


def test_passthrough_replays_recorded_commands(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    _run(capture, clock, broker, commands=CommandMode.PASSTHROUGH, prime=False)
    assert (f"{BASE}/commands/SetZ1HeatRequestTemperature", "36", False) in broker.published


def test_overlay_takes_ownership_and_suppresses_capture(
    capture: CaptureReader, clock: FakeClock
) -> None:
    broker = FakeBroker()
    config = ReplayConfig(capture=capture.path, speed=None, prime=False)
    replayer = Replayer(capture, config, broker, clock=clock, sleep=clock.advance)
    replayer.on_command(f"{BASE}/commands/SetZ1HeatRequestTemperature", "40.5")
    clock.advance(5.0)
    replayer.run()

    setpoints = broker.payloads(f"{BASE}/main/Z1_Heat_Request_Temp")
    assert setpoints == ["40"]
    assert broker.payloads(f"{BASE}/main/Z1_Water_Target_Temp") == ["40"]
    assert replayer.stats.suppressed == 3
    assert replayer.stats.owned == {"main/Z1_Heat_Request_Temp", "main/Z1_Water_Target_Temp"}
    assert broker.payloads(f"{BASE}/main/Outside_Temp") == ["3", "2", "2"]
    assert not any("commands" in t for t, _, _ in broker.published)


def test_overlay_release_hands_topic_back(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    config = ReplayConfig(capture=capture.path, speed=None, prime=False, overlay_release=1.0)
    replayer = Replayer(capture, config, broker, clock=clock, sleep=clock.advance)
    replayer.on_command(f"{BASE}/commands/SetHeatpump", "0")
    clock.advance(5.0)
    replayer.pump_overlay()
    assert replayer.semantics.owned == {"main/Heatpump_State"}
    clock.advance(2.0)
    replayer.pump_overlay()
    assert replayer.semantics.owned == set()


def test_overlay_grid_never_exceeds_confirmation_window(clock: FakeClock, tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path, "c", clock=clock)
    writer.write(Record(1.0, f"{BASE}/main/A", "1"))
    writer.close()
    reader = CaptureReader(tmp_path / "c")
    fast = Replayer(
        reader, ReplayConfig(capture=reader.path, speed=10.0), FakeBroker(), clock=clock
    )
    slow = Replayer(reader, ReplayConfig(capture=reader.path, speed=0.5), FakeBroker(), clock=clock)
    assert fast.semantics._query_interval == pytest.approx(0.5)
    assert slow.semantics._query_interval == pytest.approx(4.5)


def test_loop_replays_twice_then_stop(capture: CaptureReader, clock: FakeClock) -> None:
    broker = FakeBroker()
    config = ReplayConfig(capture=capture.path, speed=None, prime=False, loop=True)
    replayer = Replayer(capture, config, broker, clock=clock, sleep=clock.advance)
    original = replayer.run_once

    def _run_once(start: float, end: float) -> None:
        original(start, end)
        if replayer.stats.passes == 1:
            replayer.stop_requested = True

    replayer.run_once = _run_once  # type: ignore[method-assign]
    replayer.run()
    assert replayer.stats.passes == 2


def test_broker_guard() -> None:
    check_broker("localhost", False)
    check_broker("mosquitto", False)
    check_broker("mqtt.example", True)
    with pytest.raises(UnsafeBrokerError):
        check_broker("mqtt.example", False)


def test_cli_config_parsing() -> None:
    args = _build_argparser().parse_args(
        [
            "--capture",
            "x",
            "--speed",
            "max",
            "--from",
            "+1h",
            "--commands",
            "ignore",
            "--drop",
            "a, b",
        ]
    )
    config = config_from_args(args)
    assert config.speed is None
    assert config.start == "+1h"
    assert config.commands is CommandMode.IGNORE
    assert config.drop == frozenset({"a", "b"})
    assert config.prime is True
