from __future__ import annotations

from ovenbird_core.capture import CaptureRecord
from ovenbird_core.control import OvenbirdConfig, OvenbirdController, StoveConfig
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Reading, SourceKind
from ovenbird_sim.evaluate.openloop import (
    OpenLoopOptions,
    Summary,
    Tick,
    drive,
    render_stove,
    stove_option,
    stove_reference,
    with_stove,
)
from ovenbird_sim.evaluate.recorded import DATALAKE_SIGNAL, RoomSource

HALL = "ha/sensor.hall_temperature"
PUMP = {
    "Outside_Temp": "5",
    "Main_Outlet_Temp": "31",
    "Main_Inlet_Temp": "27",
    "Compressor_Freq": "30",
    "Defrosting_State": "0",
    "ThreeWay_Valve_State": "0",
    "Heating_Mode": "1",
    "Operating_Mode_State": "0",
    "Z1_Water_Target_Temp": "31",
}


def test_stove_option() -> None:
    assert stove_option(False, "sensor.hall_temperature") is None
    stove = stove_option(True, "sensor.hall_temperature", 19.5)
    assert stove is not None
    assert stove.reference == HALL
    assert stove.reference_floor_c == 19.5
    plain = stove_option(True)
    assert plain is not None
    assert plain.reference is None
    assert plain.reference_floor_c == 19.0


def test_with_stove_only_changes_ovenbird() -> None:
    controller = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=21.0))
    stoved = with_stove(controller, StoveConfig())
    assert isinstance(stoved, OvenbirdController)
    assert stoved.config.stove == StoveConfig()
    assert with_stove(controller, None) is controller


def test_reference_age() -> None:
    options = OpenLoopOptions(room_max_age_s=900.0, stove=StoveConfig(reference=HALL))
    assert stove_reference(options) == (HALL, 900.0)
    longer = OpenLoopOptions(stove=StoveConfig(reference=HALL), stove_reference_max_age_s=7200.0)
    assert stove_reference(longer) == (HALL, 7200.0)
    assert stove_reference(OpenLoopOptions(stove=StoveConfig())) is None


def test_episodes_are_summarised() -> None:
    stream: list[CaptureRecord | Reading] = []
    for k in range(0, 4 * 3600, 20):
        t = 1_800_000_000.0 + k
        for name, value in PUMP.items():
            stream.append(CaptureRecord(t, f"panasonic_heat_pump/main/{name}", value))
        stream.append(CaptureRecord(t, "panasonic_heat_pump/stats", '{"uptime":1}'))
        if k % 600 == 0:
            room = 21.0 if k < 1800 or k >= 3 * 3600 else min(23.7, 21.0 + 0.9 * (k - 1200) / 600)
            if k >= 3 * 3600 + 1800:
                room = 20.2
            observed = Instant.from_unix(t)
            stream.append(Reading(DATALAKE_SIGNAL, room, "°C", observed, SourceKind.HA))
            stream.append(Reading(HALL, 19.6, "°C", observed, SourceKind.HA))
    controller = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=21.0))
    options = OpenLoopOptions(
        room=RoomSource.DATALAKE,
        room_max_age_s=86400.0,
        stove=StoveConfig(reference=HALL, min_active_s=0.0),
    )
    summary = Summary()
    ticks: list[Tick] = []

    def sink(tick: Tick) -> None:
        ticks.append(tick)
        summary.add(tick)

    drive(with_stove(controller, options.stove), stream, options, sink)
    result = summary.to_json(60.0)
    stove = result["stove"]
    assert isinstance(stove, dict)
    episodes = stove["episodes"]
    assert isinstance(episodes, list)
    assert len(episodes) == 1
    (episode,) = episodes
    assert isinstance(episode, dict)
    assert episode["trigger"] in ("level", "rise")
    assert episode["exit"] == "cooled"
    assert episode["backoff_k_min"] == episode["backoff_k_max"] == 3.0
    assert episode["reference_c_at_entry"] == 19.6
    assert "stove" not in Summary().to_json(60.0)
    text = render_stove(result)
    assert text is not None
    assert text.startswith("wood-stove mode: 1 episodes")
    assert "exit cooled" in text
    assert render_stove(Summary().to_json(60.0)) is None
