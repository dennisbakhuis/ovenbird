from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest

from ovenbird_sim.heishamon import (
    BoardConfig,
    ColdWeek,
    Publication,
    Registers,
    SimulatedHeishaMon,
    preroll,
)
from ovenbird_sim.heishamon.__main__ import build_board, build_parser
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.heishamon.registers import registers_from_json, registers_to_json
from ovenbird_sim.heishamon.runner import RegisterSaver, RunnerConfig, run, save_registers

START = datetime(2026, 11, 7, tzinfo=UTC)
BASE = "panasonic_heat_pump"
PREFIX = "heishamon_sim/inject"


def make_board(prefix: str | None = PREFIX) -> SimulatedHeishaMon:
    weather = ColdWeek(START)
    state = preroll(REFERENCE_PARAMS, weather, START, 33, hours=2.0)
    return SimulatedHeishaMon(
        REFERENCE_PARAMS,
        weather,
        START,
        registers=Registers(direct_setpoint=33, curve_target_high=33),
        config=BoardConfig(inject_prefix=prefix),
        state=state,
    )


def main_topics(pubs: list[Publication]) -> dict[str, str]:
    prefix = f"{BASE}/main/"
    return {p.topic.removeprefix(prefix): p.payload for p in pubs if p.topic.startswith(prefix)}


def test_main_overrides_replace_reported_values_until_cleared() -> None:
    board = make_board()
    first = main_topics(board.cycle())
    assert first["Error"] == "No error"
    assert float(first["Pump_Flow"]) > 10.0
    assert board.receive(f"{PREFIX}/main/Pump_Flow", b"3.00")
    assert board.receive(f"{PREFIX}/main/Error", "H62")
    changed = main_topics(board.cycle())
    assert changed["Pump_Flow"] == "3.00"
    assert changed["Error"] == "H62"
    assert board.receive(f"{PREFIX}/main/Error", b"")
    assert main_topics(board.cycle())["Error"] == "No error"
    assert board.receive(f"{PREFIX}/clear", b"")
    assert board.overrides == {}
    assert board.stats.injections == 4


def test_register_injection_switches_to_compensation_mode() -> None:
    board = make_board()
    board.cycle()
    assert board.receive(f"{PREFIX}/register/heating_mode", b"0")
    topics = main_topics(board.cycle())
    assert topics["Heating_Mode"] == "0"
    assert board.registers.heating_mode == 0


@pytest.mark.parametrize(
    ("name", "payload"),
    [("register/heating_mode", "x"), ("register/nonsense", "1"), ("main/a/b", "1"), ("other", "")],
)
def test_bad_injections_are_rejected(name: str, payload: str) -> None:
    board = make_board()
    assert not board.receive(f"{PREFIX}/{name}", payload)
    assert board.stats.injections_rejected == 1
    assert board.registers == Registers(direct_setpoint=33, curve_target_high=33)


def test_injection_is_off_without_a_prefix() -> None:
    board = make_board(prefix=None)
    assert board.inject_filter is None
    assert not board.receive(f"{PREFIX}/main/Error", "H62")
    assert board.overrides == {}


def test_wrapped_setpoint_reaches_the_reported_target() -> None:
    board = make_board()
    board.cycle()
    board.receive(f"{BASE}/commands/SetCurves", '{"zone1":{"heat":{"target":{"high":300}}}}')
    board.cycle()
    board.cycle()
    assert board.registers.direct_setpoint == 44
    assert board.water_target == 44


def test_registers_json_round_trip_and_validation() -> None:
    registers = Registers(heating_mode=0, direct_setpoint=27, max_pump_duty=102)
    assert registers_from_json(registers_to_json(registers)) == registers
    with pytest.raises(ValueError, match="state file"):
        registers_from_json(json.dumps({"schema": 9, "registers": {}}))
    with pytest.raises(ValueError, match="integer"):
        registers_from_json(json.dumps({"schema": 1, "registers": {"direct_setpoint": "30"}}))


def test_saver_writes_only_on_change(tmp_path: Path) -> None:
    path = tmp_path / "registers.json"
    save = RegisterSaver(path)
    save(Registers(direct_setpoint=31))
    first = path.stat().st_mtime_ns
    save(Registers(direct_setpoint=31))
    assert path.stat().st_mtime_ns == first
    save(Registers(direct_setpoint=32))
    assert registers_from_json(path.read_text()).direct_setpoint == 32
    assert not (tmp_path / ".registers.json.tmp").exists()
    RegisterSaver(None)(Registers())


def test_cli_restores_registers_from_the_state_file(tmp_path: Path) -> None:
    path = tmp_path / "registers.json"
    save_registers(path, Registers(direct_setpoint=29, curve_target_high=29, max_pump_duty=102))
    argv = ["--scenario", "cold-week", "--preroll-hours", "1", "--state-file", str(path)]
    board = build_board(build_parser().parse_args(argv))
    assert board.registers.direct_setpoint == 29
    assert board.registers.max_pump_duty == 102
    assert board.water_target == 29
    assert board.config.inject_prefix == PREFIX
    path.write_text("not json", encoding="utf-8")
    fallback = build_board(build_parser().parse_args(argv))
    assert fallback.registers.max_pump_duty == Registers().max_pump_duty
    off = build_board(
        build_parser().parse_args(
            ["--scenario", "cold-week", "--preroll-hours", "0", "--inject-prefix", ""]
        )
    )
    assert off.config.inject_prefix is None


class Client:
    instances: list[Client] = []  # noqa: RUF012

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.subscribed: list[str] = []
        Client.instances.append(self)

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
        return None

    @property
    def messages(self) -> Any:
        async def stream() -> Any:
            await asyncio.Event().wait()
            yield None

        return stream()


async def test_runner_subscribes_to_injections_and_saves_registers(tmp_path: Path) -> None:
    Client.instances.clear()
    board = make_board()
    path = tmp_path / "registers.json"
    config = RunnerConfig(speed=1000.0, duration_s=30.0, state_file=path)
    await asyncio.wait_for(run(board, config, client_factory=Client), 10)
    (client,) = Client.instances
    assert client.subscribed == [f"{BASE}/commands/#", f"{PREFIX}/#"]
    assert registers_from_json(path.read_text()) == board.registers
