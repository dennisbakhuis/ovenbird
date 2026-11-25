from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Self

import aiomqtt
import pytest

from ovenbird_sim.heishamon import ColdWeek, RecordedWeather, SimulatedHeishaMon
from ovenbird_sim.heishamon.__main__ import build_board, build_parser, idle, main, parse_start
from ovenbird_sim.heishamon.board import BoardConfig
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.heishamon.runner import (
    END_OF_WEATHER,
    FINISHED,
    RemoteBrokerError,
    RunnerConfig,
    check_broker,
    run,
    status_line,
)
from ovenbird_sim.heishamon.weather import LoopedWeather, weather_end

START = datetime(2026, 1, 7, tzinfo=UTC)


class Delivered:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload
        self.retain = False


class FakeClient:
    instances: ClassVar[list[FakeClient]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.subscribed: list[str] = []
        self.published: list[tuple[str, str, bool]] = []
        self.inbox: asyncio.Queue[Delivered] = asyncio.Queue()
        FakeClient.instances.append(self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload, retain))
        if topic.endswith("/stats") and json.loads(payload)["total reads"] == 2:
            await self.inbox.put(Delivered("panasonic_heat_pump/commands/SetMaxPumpDuty", b"102"))

    @property
    def messages(self) -> Any:
        async def stream() -> Any:
            while True:
                yield await self.inbox.get()

        return stream()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "mosquitto", "LocalHost"])
def test_local_brokers_are_allowed(host: str) -> None:
    check_broker(host)


@pytest.mark.parametrize("host", ["192.0.2.10", "homeassistant.local", "nas", "core-mosquitto"])
def test_remote_brokers_are_refused(host: str) -> None:
    with pytest.raises(RemoteBrokerError):
        check_broker(host)
    check_broker(host, allow_remote=True)


async def test_runner_registers_will_subscribes_and_applies_commands() -> None:
    FakeClient.instances.clear()
    board = SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), START)
    config = RunnerConfig(speed=1000.0, duration_s=60.0)
    await asyncio.wait_for(run(board, config, client_factory=FakeClient), 10)
    (client,) = FakeClient.instances
    will = client.kwargs["will"]
    assert (will.topic, will.payload, will.retain) == (
        "panasonic_heat_pump/LWT",
        "Offline",
        True,
    )
    assert client.subscribed == ["panasonic_heat_pump/commands/#"]
    lwt = [p for p in client.published if p[0].endswith("/LWT")]
    assert len(lwt) == 12
    assert all(p[1:] == ("Online", False) for p in lwt)
    assert not any("/commands/" in p[0] for p in client.published)
    assert board.registers.max_pump_duty == 102
    assert board.elapsed_s == 60.0
    assert "room" in status_line(board)


async def test_runner_refuses_a_remote_broker_before_connecting() -> None:
    FakeClient.instances.clear()
    board = SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), START)
    with pytest.raises(RemoteBrokerError):
        await run(board, RunnerConfig(host="192.168.1.5"), client_factory=FakeClient)
    assert FakeClient.instances == []


def test_parse_start() -> None:
    assert parse_start("2026-01-07") == START
    assert parse_start("2026-01-07T06:00:00Z") == datetime(2026, 1, 7, 6, tzinfo=UTC)


def test_cold_week_needs_no_local_data(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["--scenario", "cold-week", "--weather-dir", str(tmp_path), "--preroll-hours", "2"]
    )
    board = build_board(args)
    assert board.params == REFERENCE_PARAMS
    assert board.registers.heating_mode == 1
    assert 30 <= board.registers.direct_setpoint <= 40
    assert board.registers.curve_target_high == board.registers.direct_setpoint


def test_recorded_scenario_without_cache_fails_cleanly(tmp_path: Path) -> None:
    assert main(["--weather-dir", str(tmp_path), "--preroll-hours", "0"]) == 2


def test_cli_refuses_remote_broker(tmp_path: Path) -> None:
    argv = ["--scenario", "cold-week", "--host", "10.0.0.2", "--preroll-hours", "0"]
    assert main(argv) == 2


def test_recorded_weather_interpolates(tmp_path: Path) -> None:
    t0 = START.timestamp()
    cache = {
        "meta": {},
        "hourly": {
            "time": [t0, t0 + 3600.0],
            "temperature_2m": [2.0, 4.0],
            "shortwave_radiation": [0.0, 100.0],
        },
    }
    (tmp_path / "open_meteo_hourly.json").write_text(json.dumps(cache), encoding="utf-8")
    weather = RecordedWeather.load(tmp_path)
    assert weather.covers(t0 + 1800.0)
    assert not weather.covers(t0 - 1.0)
    assert weather.at(t0 + 1800.0, 1.5).outside_c == pytest.approx(3.0)
    assert weather.at(t0 + 7200.0, 3.0).outside_c == pytest.approx(4.0)
    assert weather.at(t0 + 1800.0, 1.5).solar_w_m2 == pytest.approx(100.0)


def test_cold_week_is_cold_and_deterministic() -> None:
    week = ColdWeek(START)
    temps = [week.at(START.timestamp() + h * 3600.0, (h + 1) % 24).outside_c for h in range(168)]
    assert min(temps) < -8.0
    assert max(temps) < 3.0
    assert temps == [
        ColdWeek(START).at(START.timestamp() + h * 3600.0, (h + 1) % 24).outside_c
        for h in range(168)
    ]
    assert week.at(START.timestamp(), 3.0).solar_w_m2 == 0.0
    assert week.at(START.timestamp() + 11 * 3600.0, 12.5).solar_w_m2 > 0.0


def test_mqtt_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    class Flaky(FakeClient):
        async def __aenter__(self) -> Self:
            attempts.append(1)
            if len(attempts) == 1:
                raise aiomqtt.MqttError("refused")
            return self

    monkeypatch.setattr("ovenbird_sim.heishamon.runner.RECONNECT_DELAY_S", 0.0)
    board = SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), START)
    asyncio.run(run(board, RunnerConfig(speed=1000.0, duration_s=10.0), client_factory=Flaky))
    assert len(attempts) == 2


def two_hour_cache(directory: Path) -> RecordedWeather:
    t0 = START.timestamp()
    cache = {
        "meta": {},
        "hourly": {
            "time": [t0, t0 + 3600.0, t0 + 7200.0],
            "temperature_2m": [2.0, 4.0, 6.0],
            "shortwave_radiation": [0.0, 0.0, 0.0],
        },
    }
    (directory / "open_meteo_hourly.json").write_text(json.dumps(cache), encoding="utf-8")
    return RecordedWeather.load(directory)


async def test_runner_stops_at_the_end_of_the_recorded_weather(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    FakeClient.instances.clear()
    weather = two_hour_cache(tmp_path)
    board = SimulatedHeishaMon(REFERENCE_PARAMS, weather, START)
    outcome = await asyncio.wait_for(
        run(board, RunnerConfig(speed=1e6), client_factory=FakeClient), 30
    )
    assert outcome == END_OF_WEATHER
    assert board.now.timestamp() > START.timestamp() + 7200.0
    assert board.elapsed_s <= 7200.0 + board.config.query_interval_s
    (client,) = FakeClient.instances
    assert client.published[-1] == ("panasonic_heat_pump/LWT", "Offline", True)
    assert "recorded weather ends at 2026-01-07T02:00:00+00:00" in caplog.text


async def test_runner_finishes_a_duration() -> None:
    FakeClient.instances.clear()
    board = SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), START)
    outcome = await run(board, RunnerConfig(speed=1e6, duration_s=60.0), client_factory=FakeClient)
    assert outcome == FINISHED


def test_looped_weather_wraps(tmp_path: Path) -> None:
    weather = two_hour_cache(tmp_path)
    looped = LoopedWeather(weather)
    t0 = START.timestamp()
    assert looped.at(t0 + 3600.0, 1.0).outside_c == pytest.approx(4.0)
    assert looped.at(t0 + 7200.0 + 3600.0, 1.0).outside_c == pytest.approx(4.0)
    assert looped.at(t0 + 7200.0 + 1800.0, 1.0).outside_c == pytest.approx(3.0)
    assert weather_end(looped) is None
    assert weather_end(weather) == pytest.approx(t0 + 7200.0)
    assert weather_end(ColdWeek(START)) is None


def test_at_end_option(tmp_path: Path) -> None:
    two_hour_cache(tmp_path)
    base = ["--weather-dir", str(tmp_path), "--preroll-hours", "0", "--start", "2026-01-07"]
    assert build_parser().parse_args(base).at_end == "stop"
    looped = build_board(build_parser().parse_args([*base, "--at-end", "loop"]))
    assert isinstance(looped.weather, LoopedWeather)
    stopped = build_board(build_parser().parse_args(base))
    assert isinstance(stopped.weather, RecordedWeather)


def test_idle_never_returns() -> None:
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) == 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        idle(sleep)
    assert calls == [3600.0] * 3


def test_extra_heat_injection_warms_the_house() -> None:
    plain = SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), START)
    stove = SimulatedHeishaMon(
        REFERENCE_PARAMS, ColdWeek(START), START, config=BoardConfig(inject_prefix="sim")
    )
    assert stove.receive("sim/house/extra_heat_w", b"6000")
    assert stove.extra_heat_w == 6000.0
    assert not stove.receive("sim/house/extra_heat_w", b"-5")
    assert not stove.receive("sim/house/extra_heat_w", b"warm")
    for _ in range(5 * 720):
        plain.cycle()
        stove.cycle()
    assert stove.state.t_air > plain.state.t_air + 1.0
    assert stove.stove_zone_k == pytest.approx(3.6, abs=0.05)
    assert stove.observation is not None
    assert stove.observation.room_temp == pytest.approx(stove.room_c, abs=0.05)
    assert stove._room_thermostat() == pytest.approx(stove.state.t_air, abs=1.0)
    stove.receive("sim/house/extra_heat_w", b"0")
    for _ in range(4 * 720):
        stove.cycle()
    assert stove.stove_zone_k < 0.1
    assert stove.receive("sim/clear", b"")
    assert stove.extra_heat_w == 0.0
