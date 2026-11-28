from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ovenbird_sim.heishamon import (
    BoardConfig,
    ColdWeek,
    Publication,
    Registers,
    SimulatedHeishaMon,
    preroll,
)
from ovenbird_sim.heishamon.board import DEFROST_PUMP_DUTY, THERMOSTAT_OFFSET_K
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS

START = datetime(2026, 11, 7, tzinfo=UTC)
BASE = "panasonic_heat_pump"
CMD = f"{BASE}/commands"
SETCURVES = '{"zone1":{"heat":{"target":{"high":%d}}}}'


def make_board(**config: object) -> SimulatedHeishaMon:
    """Return a board on the cold week with ``config`` overrides, pre-rolled for six hours."""
    weather = ColdWeek(START)
    state = preroll(REFERENCE_PARAMS, weather, START, 33, hours=6.0)
    return SimulatedHeishaMon(
        REFERENCE_PARAMS,
        weather,
        START,
        registers=Registers(direct_setpoint=33, curve_target_high=33),
        config=BoardConfig(**config),  # type: ignore[arg-type]
        state=state,
    )


def by_topic(pubs: list[Publication]) -> dict[str, Publication]:
    """Return the publications by topic."""
    return {p.topic: p for p in pubs}


def main_topics(pubs: list[Publication]) -> dict[str, str]:
    """Return the ``main/*`` publications as a mapping from topic name to payload."""
    prefix = f"{BASE}/main/"
    return {p.topic.removeprefix(prefix): p.payload for p in pubs if p.topic.startswith(prefix)}


def test_first_cycle_dumps_everything_retained_with_stats_and_lwt() -> None:
    """The first cycle dumps every main topic retained, with stats and the online status."""
    board = make_board()
    pubs = board.cycle()
    topics = by_topic(pubs)
    main = [p for p in pubs if "/main/" in p.topic]
    assert len(main) > 30
    assert all(p.retain for p in main)
    assert main_topics(pubs)["Heating_Mode"] == "1"
    assert main_topics(pubs)["Z1_Water_Target_Temp"] == "33"
    assert topics[f"{BASE}/LWT"] == Publication(f"{BASE}/LWT", "Online", False)
    stats = topics[f"{BASE}/stats"]
    assert stats.retain
    assert json.loads(stats.payload)["total reads"] == 1
    assert board.elapsed_s == 5.0


def test_will_is_offline_retained() -> None:
    """The last-will message is a retained ``Offline``."""
    assert make_board().will() == Publication(f"{BASE}/LWT", "Offline", True)


def test_publish_on_change_then_full_dump_every_300_s() -> None:
    """After the first full dump only changes are published, with a full dump every 300 s."""
    board = make_board(room_topic=None)
    first = board.cycle()
    dump_size = len(main_topics(first))
    sizes = [len(main_topics(board.cycle())) for _ in range(59)]
    assert max(sizes) < dump_size
    assert all(n < 15 for n in sizes)
    assert len(main_topics(board.cycle())) == dump_size
    assert board.elapsed_s == 305.0
    for _ in range(60):
        pubs = board.cycle()
        assert f"{BASE}/stats" in by_topic(pubs)
        assert by_topic(pubs)[f"{BASE}/LWT"].payload == "Online"


def test_command_takes_effect_on_next_cycle_without_echo() -> None:
    """A command is applied on the next cycle without being echoed back on a topic."""
    board = make_board(target_lag_cycles=0)
    board.cycle()
    assert board.receive(f"{CMD}/SetCurves", SETCURVES % 30)
    assert board.registers.direct_setpoint == 33
    pubs = board.cycle()
    main = main_topics(pubs)
    assert main["Z1_Heat_Curve_Target_High_Temp"] == "30"
    assert main["Z1_Water_Target_Temp"] == "30"
    assert main["Main_Target_Temp"] == "30"
    assert not any("/commands/" in p.topic for p in pubs)
    assert board.water_target == 30


def test_water_target_follows_one_cycle_after_the_register() -> None:
    """The water target reported follows a changed setpoint one cycle after the register."""
    board = make_board()
    board.cycle()
    board.receive(f"{CMD}/SetZ1HeatRequestTemperature", "29")
    applied = main_topics(board.cycle())
    assert applied["Z1_Heat_Request_Temp"] == "29"
    assert "Z1_Water_Target_Temp" not in applied
    assert board.water_target == 33
    followed = main_topics(board.cycle())
    assert followed["Z1_Water_Target_Temp"] == "29"
    assert followed["Main_Target_Temp"] == "29"
    assert board.water_target == 29


def test_pump_duty_and_quiet_mode_registers() -> None:
    """The max pump duty and quiet mode commands change their registers and are counted."""
    board = make_board()
    board.cycle()
    board.receive(f"{CMD}/SetMaxPumpDuty", "102")
    board.receive(f"{CMD}/SetQuietMode", "2")
    main = main_topics(board.cycle())
    assert main["Max_Pump_Duty"] == "102"
    assert main["Quiet_Mode_Level"] == "2"
    assert board.stats.applied == {"SetMaxPumpDuty": 1, "SetQuietMode": 1}


def test_integer_parsing_reaches_main_topics() -> None:
    """Integer command payloads are parsed like the firmware does, wrapping to a signed byte."""
    board = make_board(target_lag_cycles=0)
    board.cycle()
    board.receive(f"{CMD}/SetZ1HeatRequestTemperature", b"31abc")
    assert main_topics(board.cycle())["Z1_Water_Target_Temp"] == "31"
    board.receive(f"{CMD}/SetZ1HeatRequestTemperature", b"300")
    assert main_topics(board.cycle())["Z1_Water_Target_Temp"] == "44"


def test_unknown_foreign_and_overflowing_commands() -> None:
    """Unknown, foreign-base, state-topic and overflowing commands are ignored or dropped."""
    board = make_board()
    board.cycle()
    assert not board.receive(f"{CMD}/SetHeatpump", "0")
    assert not board.receive("other_base/commands/SetCurves", SETCURVES % 25)
    assert not board.receive(f"{BASE}/main/Heating_Mode", "0")
    accepted = [board.receive(f"{CMD}/SetMaxPumpDuty", str(100 + i)) for i in range(11)]
    assert accepted == [True] * 10 + [False]
    assert board.stats.commands_ignored == 1
    assert board.stats.commands_dropped == 1
    board.cycle()
    assert board.registers.max_pump_duty == 109
    assert board.registers.heating_mode == 1


def test_room_temperature_every_minute_on_its_topic() -> None:
    """The room temperature is published on its own retained topic every minute."""
    board = make_board(room_topic="sim/room", room_interval_s=60.0)
    rooms = []
    for _ in range(36):
        rooms += [p for p in board.cycle() if p.topic == "sim/room"]
    assert len(rooms) == 3
    assert all(p.retain for p in rooms)
    assert 15.0 < float(rooms[0].payload) < 26.0


def test_example_room_sensor_reports_on_change_with_humidity() -> None:
    """The example room sensor publishes on change in 0.1 K steps, with humidity."""
    from ovenbird_sim.evaluate.sensors import example_room_sensor

    board = make_board(
        room_topic="sim/room",
        room_sensor=example_room_sensor(),
        humidity_topic="sim/humidity",
        room_seed=3,
    )
    rooms: list[Publication] = []
    humidity: list[Publication] = []
    for _ in range(12 * 2 * 720):
        pubs = board.cycle()
        rooms += [p for p in pubs if p.topic == "sim/room"]
        humidity += [p for p in pubs if p.topic == "sim/humidity"]
    values = [float(p.payload) for p in rooms]
    assert 1 <= len(rooms) < 12 * 2 * 12
    assert all(round(v / 0.1) * 0.1 == pytest.approx(v) for v in values)
    assert all(a != b for a, b in itertools.pairwise(values))
    assert humidity
    assert all(p.retain for p in rooms + humidity)
    assert board.config.room_model().profile.liveness


def test_default_room_sensor_is_periodic() -> None:
    """By default the room sensor reports periodically and is considered fresh for 30 minutes."""
    model = BoardConfig(room_interval_s=120.0).room_model()
    assert model.confirm_s == 120.0
    assert model.sample_s == 120.0
    assert model.step_k == 0.1
    assert model.profile.max_age_s == 1800.0


def test_compensation_mode_is_reported() -> None:
    """Compensation heating mode is reported in the main topics."""
    weather = ColdWeek(START)
    board = SimulatedHeishaMon(
        REFERENCE_PARAMS, weather, START, registers=Registers(heating_mode=0)
    )
    main = main_topics(board.cycle())
    assert main["Heating_Mode"] == "0"
    assert main["Z1_Heat_Request_Temp"] == "0"


def test_plant_reacts_to_a_setpoint_raise() -> None:
    """The plant heats up after the setpoint is raised."""
    board = make_board(target_lag_cycles=0)
    for _ in range(12):
        board.cycle()
    board.receive(f"{CMD}/SetCurves", SETCURVES % 40)
    outlets = []
    for _ in range(12 * 30):
        board.cycle()
        assert board.observation is not None
        outlets.append(board.observation.outlet_temp)
    assert board.state.running
    assert max(outlets) > outlets[0] + 2.0


def test_start_must_be_aware() -> None:
    """A start time without a time zone is refused."""
    with pytest.raises(ValueError, match="aware"):
        SimulatedHeishaMon(REFERENCE_PARAMS, ColdWeek(START), datetime(2026, 11, 7))


def test_preroll_settles_near_the_requested_room() -> None:
    """The pre-roll brings the room near the requested temperature and keeps the last setpoint."""
    weather = ColdWeek(START)
    state = preroll(REFERENCE_PARAMS, weather, START, 33, room_c=21.0, hours=24.0)
    assert abs(state.t_air - 21.0) < 0.6
    assert state.starts == 0
    assert state.last_setpoint is not None
    held = preroll(
        REFERENCE_PARAMS, weather, START, 33, room_c=21.0, hours=2.0, room_gain_k_per_k=0.0
    )
    assert held.last_setpoint == 33.0


def test_defrost_runs_the_pump_at_its_own_duty() -> None:
    """During a defrost the pump runs at the defrost duty, and at the maximum duty afterwards."""
    board = make_board()
    board.receive(f"{CMD}/SetMaxPumpDuty", "159")
    board.state = replace(board.state, running=True, defrost_left_s=60.0)
    during = main_topics(board.cycle())
    assert during["Defrosting_State"] == "1"
    assert during["Pump_Duty"] == str(DEFROST_PUMP_DUTY)
    assert during["Max_Pump_Duty"] == "159"
    states = [main_topics(board.cycle()) for _ in range(20)]
    after = next(s for s in states if s.get("Defrosting_State") == "0")
    assert after["Pump_Duty"] == ("159" if board.state.running else "0")
    assert "Max_Pump_Duty" not in after or after["Max_Pump_Duty"] == "159"


def test_room_thermostat_is_an_integer_near_the_room_plus_offset() -> None:
    """The room thermostat is reported as an integer near the room temperature plus the offset."""
    board = make_board()
    values = []
    for _ in range(240):
        topics = main_topics(board.cycle())
        if "Room_Thermostat_Temp" in topics:
            values.append(int(topics["Room_Thermostat_Temp"]))
    assert values
    expected = board.state.t_air + THERMOSTAT_OFFSET_K
    assert all(abs(v - expected) <= 1.5 for v in values)
    assert (
        main_topics(make_board(thermostat_offset_k=None).cycle()).get("Room_Thermostat_Temp")
        is None
    )


def test_dhw_flag_silenced_topics_and_reboot() -> None:
    """The hot-water flag, silenced topics and a reboot show up in the published topics."""
    board = make_board()
    board.cycle()
    board.dhw = True
    board.silenced = {"Outside_Temp"}
    topics: dict[str, str] = {}
    for _ in range(61):
        topics |= main_topics(board.cycle())
    assert topics["ThreeWay_Valve_State"] == "1"
    assert "Outside_Temp" not in topics
    board.silenced = set()
    board.reboot()
    dump = main_topics(board.cycle())
    assert "Outside_Temp" in dump
    assert len(dump) > 30
