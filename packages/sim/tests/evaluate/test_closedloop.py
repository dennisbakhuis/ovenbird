"""Closed loop on a known plant: sanity of outcomes, KPIs and determinism."""

import math
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

import numpy as np
import pytest

from ovenbird_core.control import (
    CommandIntent,
    Controller,
    DecisionRecord,
    IntentKind,
    LadderLevel,
    OvenbirdConfig,
    OvenbirdController,
    ReasonCode,
    StepResult,
)
from ovenbird_core.control.types import ControlInputs
from ovenbird_core.store import Snapshot
from ovenbird_sim.evaluate import kpi
from ovenbird_sim.evaluate.closedloop import (
    LoopOptions,
    RecordedSetpoints,
    SyntheticHeishaMon,
    Weather,
    plant_readings,
    simulate,
)
from ovenbird_sim.evaluate.sensors import SensorModel
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams, PlantState, initial_state

PARAMS = PlantParams(
    HeatPumpParams(),
    BuildingParams(c_air=3.0e7, h_air_out=250.0, q_int_w=200.0),
)
T0 = 1_793_232_000.0


def _weather(days: float, outside: float = 0.0) -> Weather:
    """Return ``days`` of sunless weather at a constant outside temperature (degC), per minute."""
    n = int(days * 1440)
    hours = (np.arange(n) / 60.0) % 24.0
    return Weather(T0, 60.0, np.full(n, outside), np.zeros(n), hours.astype(np.float64))


def _start() -> PlantState:
    """Return the plant state the closed-loop tests start from."""
    return initial_state(PARAMS, 21.0, t_mass=23.0, t_water=26.0)


@dataclass(frozen=True)
class Constant:
    """Controller that always requests the same water setpoint."""

    setpoint: int
    name: str = "constant"

    def initial_state(self) -> None:
        """Return no state; the controller is stateless."""
        return

    def step(self, state: None, inputs: ControlInputs) -> StepResult[None]:
        """Return the constant setpoint as the only intent, with a minimal decision record."""
        intent = CommandIntent(IntentKind.WATER_SETPOINT, self.setpoint, ReasonCode.CURVE)
        record = DecisionRecord(
            at=inputs.now,
            controller=self.name,
            mode=inputs.mode,
            ladder=LadderLevel.CURVE_ONLY,
            terms=(),
            pre_round=float(self.setpoint),
            setpoint=self.setpoint,
            binding=None,
            flip_distance=None,
            inputs_used=(),
            controller_state={},
            reason=ReasonCode.CURVE,
            note="constant",
            intents=(intent,),
        )
        return StepResult(state, (intent,), record)


def _kpis(setpoint: int) -> kpi.KpiTable:
    """Return the KPIs of two days under a constant setpoint."""
    weather = _weather(2.0)
    trace = simulate(
        Constant(setpoint), PARAMS, weather, _start(), LoopOptions(initial_setpoint=28)
    )
    return kpi.compute(kpi.from_trace(trace, weather.dt), 22.0)


def test_more_aggressive_heating_delivers_more_heat_and_comfort() -> None:
    """A higher constant setpoint gives more heat, more electricity and a warmer room."""
    low, high = _kpis(28), _kpis(36)
    assert high.totals["heat_kwh_per_day"] > low.totals["heat_kwh_per_day"] > 0.0
    assert high.totals["elec_kwh_per_day"] > low.totals["elec_kwh_per_day"]
    assert high.totals["room_mean_c"] > low.totals["room_mean_c"]
    assert high.totals["degree_hours_below_per_day"] <= low.totals["degree_hours_below_per_day"]
    assert low.totals["writes_per_day"] == 0.0
    assert high.totals["writes_per_day"] == 0.5
    assert len(high.days) == 2


def test_runs_are_deterministic_with_seeded_sensor_noise() -> None:
    """Two runs with the same seeded sensor noise are identical."""
    weather = _weather(0.5)
    options = LoopOptions(
        initial_setpoint=30,
        sensors=SensorModel(outside_noise_k=0.3, thermostat_noise_k=0.3, seed=3),
    )
    controller = OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=22.0))
    a = simulate(controller, PARAMS, weather, _start(), options)
    b = simulate(controller, PARAMS, weather, _start(), options)
    for name in ("setpoint", "room_c", "heat_w", "elec_w", "start", "write"):
        assert np.array_equal(getattr(a, name), getattr(b, name))
    assert a.reasons == b.reasons


def test_recorded_setpoints_drive_the_plant_as_recorded() -> None:
    """Recorded setpoints are replayed unchanged, as overrides, and are unknown before the start."""
    weather = _weather(0.5)
    recorded = tuple(30 + (k // 120) % 3 for k in range(weather.n))
    baseline = RecordedSetpoints(weather.t0, weather.dt, recorded)
    trace = simulate(baseline, PARAMS, weather, _start(), LoopOptions(initial_setpoint=30))
    assert trace.setpoint.tolist() == [float(v) for v in recorded]
    assert int(trace.write.sum()) == sum(a != b for a, b in pairwise(recorded))
    assert set(trace.reasons) == {"override"}
    assert baseline.setpoint_at(weather.t0 - 60.0) is None


def test_both_controllers_close_the_loop() -> None:
    """The recorded replay and the ovenbird controller both keep the house plausibly warm."""
    weather = _weather(1.0, outside=2.0)
    options = LoopOptions(initial_setpoint=30)
    controllers: tuple[Controller[Any], ...] = (
        RecordedSetpoints(weather.t0, weather.dt, (33,) * weather.n),
        OvenbirdController(OvenbirdConfig.preset("mixed", comfort_room_c=22.5)),
    )
    for controller in controllers:
        trace = simulate(controller, PARAMS, weather, _start(), options)
        table = kpi.compute(kpi.from_trace(trace, weather.dt), 22.0)
        assert table.totals["heat_kwh_per_day"] > 0.0
        assert 20.0 < table.totals["room_mean_c"] < 25.0
        assert trace.write.sum() >= 1
        assert 20 <= trace.setpoint.min() <= trace.setpoint.max() <= 45


def test_noise_makes_integer_sensors_flip() -> None:
    """Sensor noise makes the integer outside reading flip; without noise it does not."""
    state = _start()
    model = SensorModel(outside_noise_k=0.5, thermostat_noise_k=0.5)
    draws = np.random.default_rng(0).standard_normal((500, 2))
    readings = [
        plant_readings(PARAMS, state, 0.5, 30, 102, (float(d[0]), float(d[1])), model)
        for d in draws
    ]
    outside = np.array([float(r["main/Outside_Temp"]) for r in readings])
    clean = plant_readings(PARAMS, state, 0.5, 30, 102)
    assert int(np.sum(outside[1:] != outside[:-1])) > 100
    assert clean["main/Outside_Temp"] in (0, 1)


def test_heishamon_reobserves_on_change_and_on_dump() -> None:
    """HeishaMon values are re-observed on change and on each periodic dump, not in between."""
    heishamon = SyntheticHeishaMon("ha/sensor.room", dump_s=300.0)
    values = {"main/Outside_Temp": 3}
    first = heishamon.snapshot(T0, values)
    assert first.heishamon.alive
    assert _age(heishamon.snapshot(T0 + 120.0, values)) == pytest.approx(120.0)
    assert _age(heishamon.snapshot(T0 + 180.0, {"main/Outside_Temp": 4})) == 0.0
    assert _age(heishamon.snapshot(T0 + 240.0, {"main/Outside_Temp": 4})) == 60.0
    assert _age(heishamon.snapshot(T0 + 300.0, {"main/Outside_Temp": 4})) == 0.0


def _age(snapshot: Snapshot) -> float | None:
    """Return the age (s) of the outside temperature in the snapshot."""
    view = snapshot.get("main/Outside_Temp")
    assert view is not None
    return view.age


def test_kpis_per_day_and_period() -> None:
    """Daily and period KPIs follow from heat, electricity, room temperature, starts and writes."""
    t = np.arange(2880, dtype=np.float64) * 60.0 + T0
    series = kpi.Series(
        t=t,
        dt=60.0,
        heat_w=np.full(2880, 3600.0),
        elec_w=np.full(2880, 900.0),
        room_c=np.r_[np.full(1440, 21.5), np.full(1440, 22.5)],
        start=np.r_[1.0, np.zeros(2879)],
        write=np.r_[np.zeros(10), 1.0, np.zeros(2869)],
        defrost=np.r_[np.ones(7), np.zeros(2873)],
        run_start=np.array([T0, T0 + 86400.0]),
        run_length_s=np.array([600.0, 3600.0]),
    )
    table = kpi.compute(series, 22.0)
    first, second = table.days.values()
    assert first["heat_kwh"] == pytest.approx(86.4)
    assert first["degree_hours_below"] == pytest.approx(12.0)
    assert second["degree_hours_below"] == 0.0
    assert first["short_runs"] == 1.0
    assert second["short_runs"] == 0.0
    totals = table.totals
    assert totals["cop"] == pytest.approx(4.0)
    assert totals["short_run_share"] == 0.5
    assert totals["room_mean_c"] == pytest.approx(22.0)
    assert totals["starts_per_day"] == 0.5
    assert totals["defrost_min_per_day"] == pytest.approx(3.5)
    sub = table.subset([next(iter(table.days))])
    assert sub.totals["room_mean_c"] == pytest.approx(21.5)
    assert math.isnan(kpi.aggregate({})["cop"])


def test_recorded_runs_bridge_defrost_pauses() -> None:
    """A short defrost pause does not split a compressor run into two."""
    t = 60.0 * np.arange(100, dtype=np.float64)
    running = np.zeros(100)
    running[10:40] = 1.0
    running[44:60] = 1.0
    defrost = np.zeros(100)
    defrost[40:44] = 1.0
    starts, lengths = kpi.recorded_runs(t, running, defrost, 60.0)
    assert starts.tolist() == [600.0]
    assert lengths.tolist() == [3000.0]


def test_room_sensor_reports_changes_confirms_and_drops_out() -> None:
    """The room sensor reports on grid steps, confirms at its interval and drops out as modelled."""
    from ovenbird_sim.evaluate.closedloop import UNAVAILABLE_REASON, HaRoomSensor
    from ovenbird_sim.evaluate.sensors import RoomSensorModel

    model = RoomSensorModel(
        step_k=0.2, grid_offset_k=0.0, confirm_s=math.inf, dropouts=((600.0, 900.0),)
    )
    sensor = HaRoomSensor(model)

    def read(t: float, t_air: float) -> tuple[float, float | None, str | None]:
        """Return the value, the observation time and the reason the sensor shows at ``t``."""
        view = sensor.view(t, t_air, 0.0)
        assert view is not None
        return float(view.value), None if view.age is None else t - view.age, view.reason

    assert read(0.0, 21.22) == (21.2, 0.0, None)
    assert read(300.0, 21.25) == (21.2, 0.0, None)
    assert read(660.0, 21.4) == (21.2, 0.0, UNAVAILABLE_REASON)
    assert read(960.0, 21.22) == (21.2, 960.0, None)
    assert read(1020.0, 21.32) == (21.4, 1020.0, None)
    confirming = HaRoomSensor(replace_room(model, confirm_s=600.0))
    confirming.view(0.0, 21.2, 0.0)
    first = confirming.view(540.0, 21.2, 0.0)
    assert first is not None
    assert first.age == 540.0
    second = confirming.view(1080.0, 21.2, 0.0)
    assert second is not None
    assert second.age == 0.0


def replace_room(model: Any, **changes: Any) -> Any:
    """Return ``model`` with the given fields replaced."""
    return replace(model, **changes)


def test_ovenbird_room_input_goes_stale_like_live() -> None:
    """The controller sees a stale room value when the sensor only confirms rarely."""
    from ovenbird_sim.evaluate.sensors import RoomSensorModel

    weather = _weather(0.5)
    config = OvenbirdConfig.preset("mixed", comfort_room_c=21.0)
    stale_room = SensorModel(room=RoomSensorModel(step_k=0.2, confirm_s=math.inf))
    fresh_room = SensorModel(room=RoomSensorModel(step_k=0.2, confirm_s=0.0))
    stale = simulate(
        OvenbirdController(config),
        PARAMS,
        weather,
        _start(),
        LoopOptions(initial_setpoint=28, sensors=stale_room),
    )
    fresh = simulate(
        OvenbirdController(config),
        PARAMS,
        weather,
        _start(),
        LoopOptions(initial_setpoint=28, sensors=fresh_room),
    )
    assert fresh.room_fresh.mean() == 1.0
    assert "curve_only" not in fresh.ladder
    assert stale.room_fresh.mean() < 1.0
    assert "curve_only" in stale.ladder
    gone = simulate(
        OvenbirdController(config),
        PARAMS,
        weather,
        _start(),
        LoopOptions(
            initial_setpoint=28,
            sensors=SensorModel(room=RoomSensorModel(dropouts=((T0 + 3600.0, T0 + 7200.0),))),
        ),
    )
    assert gone.room_fresh[60:120].sum() == 0.0
    assert gone.room_fresh[:60].all()


def test_thermostat_offset_follows_the_day() -> None:
    """The thermostat offset follows the per-day profile and uses its median without a time."""
    model = SensorModel(thermostat_offset_k=0.8, offset_t0=T0, offset_by_day=(1.0, 0.0))
    state = _start()
    first = plant_readings(PARAMS, state, 0.5, 30, 102, sensors=model, t=T0 + 3600.0)
    second = plant_readings(PARAMS, state, 0.5, 30, 102, sensors=model, t=T0 + 90000.0)
    median = plant_readings(PARAMS, state, 0.5, 30, 102, sensors=model)
    assert first["main/Room_Thermostat_Temp"] == round(21.0 + 1.0)
    assert second["main/Room_Thermostat_Temp"] == 21
    assert median["main/Room_Thermostat_Temp"] == round(21.0 + 0.8)
    assert model.thermostat_offset(T0 - 10 * 86400.0) == 1.0
    assert model.thermostat_offset(T0 + 10 * 86400.0) == 0.0


def test_room_sensor_calibration_finds_grid_noise_and_dropouts() -> None:
    """Calibration recovers the sensor's grid step, noise and dropouts from recorded states."""
    from ovenbird_sim.data.series import Series
    from ovenbird_sim.evaluate.sensors import calibrate_room

    times = (T0 + 60.0 * np.arange(4 * 1440)).astype(np.float64)
    reference = (21.5 + 0.3 * np.sin(2 * np.pi * (times - T0) / 86400.0)).astype(np.float64)
    q = np.round((reference - 0.1) / 0.2) * 0.2 + 0.1
    change = np.r_[True, np.diff(q) != 0]
    t_states = times[change]
    v_states = q[change].copy()
    v_states[5] = np.nan
    states = Series(t_states, v_states)
    model = calibrate_room(states, reference, times)
    assert model.step_k == pytest.approx(0.2)
    assert model.grid_offset_k == pytest.approx(0.1)
    assert model.noise_k == 0.0
    assert model.confirm_s == math.inf
    assert model.dropouts == ((float(t_states[5]), float(t_states[6])),)
    faster = Series(
        np.linspace(times[0], times[-1], 3 * t_states.size),
        np.tile([21.5, 21.7, 21.9], t_states.size),
    )
    assert calibrate_room(faster, reference, times).noise_k > 0.0
