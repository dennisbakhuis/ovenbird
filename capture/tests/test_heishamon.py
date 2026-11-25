from __future__ import annotations

import json

import pytest

from climate_manager_capture.heishamon import (
    COMMAND_QUEUE_MAX,
    Cadence,
    CommandSemantics,
    command_name,
    to_int,
)
from climate_manager_capture.testing import FakeClock


@pytest.mark.parametrize(
    ("payload", "expected"),
    [("21", 21), ("21.9", 21), ("-3", -3), ("  7abc", 7), ("abc", 0), ("", 0), ("+4", 4)],
)
def test_to_int_reads_the_leading_integer(payload: str, expected: int) -> None:
    assert to_int(payload) == expected


def test_command_name() -> None:
    assert command_name("panasonic_heat_pump/commands/SetHeatpump") == "SetHeatpump"
    assert command_name("panasonic_heat_pump/main/Outside_Temp") is None
    assert command_name("SetHeatpump") is None


def test_side_effect_lands_on_next_query_tick(clock: FakeClock) -> None:
    semantics = CommandSemantics(clock)
    clock.advance(1.0)
    assert semantics.receive("SetHeatpump", "0") is True
    assert semantics.due() == []
    clock.advance(3.9)
    assert semantics.due() == []
    clock.advance(0.2)
    effects = semantics.due()
    assert [(e.suffix, e.payload) for e in effects] == [("main/Heatpump_State", "0")]
    assert semantics.owned == {"main/Heatpump_State"}


def test_truncation_and_secondary_effects(clock: FakeClock) -> None:
    semantics = CommandSemantics(clock, secondary=True)
    semantics.receive("SetZ1HeatRequestTemperature", "36.7")
    clock.advance(5.0)
    effects = {e.suffix: e.payload for e in semantics.due()}
    assert effects == {"main/Z1_Heat_Request_Temp": "36", "main/Z1_Water_Target_Temp": "36"}


def test_queue_cap_and_unknown_commands(clock: FakeClock) -> None:
    semantics = CommandSemantics(clock)
    assert semantics.receive("SetQuietMode", "1") is False
    assert semantics.ignored == 1
    for _ in range(COMMAND_QUEUE_MAX):
        assert semantics.receive("SetHeatpump", "1") is True
    assert semantics.receive("SetHeatpump", "1") is False
    assert semantics.dropped == 1
    clock.advance(5.0)
    assert len(semantics.due()) == COMMAND_QUEUE_MAX


def test_release_stale_ownership(clock: FakeClock) -> None:
    semantics = CommandSemantics(clock)
    semantics.receive("SetHeatpump", "1")
    clock.advance(5.0)
    semantics.due()
    assert semantics.release_stale(clock.now + 10, max_age=60) == set()
    assert semantics.release_stale(clock.now + 61, max_age=60) == {"main/Heatpump_State"}
    assert semantics.owned == set()


def test_cadence_first_tick_dumps_everything(clock: FakeClock) -> None:
    cadence = Cadence(clock)
    cadence.set("main/A", "1")
    cadence.set("main/B", "2")
    emissions = cadence.tick()
    suffixes = [e.suffix for e in emissions]
    assert suffixes == ["main/A", "main/B", "stats", "LWT"]
    assert all(e.retain for e in emissions if e.suffix != "LWT")
    lwt = emissions[-1]
    assert (lwt.payload, lwt.retain) == ("Online", False)
    assert json.loads(emissions[-2].payload)["total reads"] == 1
    assert cadence.will().payload == "Offline"
    assert cadence.will().retain is True


def test_cadence_publishes_only_changes_between_dumps(clock: FakeClock) -> None:
    cadence = Cadence(clock)
    cadence.set("main/A", "1")
    cadence.set("main/B", "2")
    cadence.tick()
    clock.advance(2.0)
    assert cadence.tick() == []
    clock.advance(3.0)
    cadence.set("main/A", "5")
    suffixes = [e.suffix for e in cadence.tick()]
    assert suffixes == ["main/A", "stats", "LWT"]
    clock.advance(5.0)
    assert [e.suffix for e in cadence.tick()] == ["stats", "LWT"]


def test_cadence_full_dump_every_300s(clock: FakeClock) -> None:
    cadence = Cadence(clock)
    cadence.set("main/A", "1")
    cadence.tick()
    clock.advance(295.0)
    assert [e.suffix for e in cadence.tick()] == ["stats", "LWT"]
    clock.advance(5.0)
    assert [e.suffix for e in cadence.tick()] == ["main/A", "stats", "LWT"]
