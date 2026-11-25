"""The shared room sensor model: device reports, calibration, store semantics, variants."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace

import numpy as np
import pytest

from ovenbird_core.control import OvenbirdConfig, OvenbirdController, RoomProfile
from ovenbird_core.control.config import RoomSensorProfile
from ovenbird_sim.data.series import Series
from ovenbird_sim.evaluate.closedloop import HaRoomSensor, LoopOptions, Weather, simulate
from ovenbird_sim.evaluate.counterfactual import room_variant_models
from ovenbird_sim.evaluate.sensors import (
    HUMIDITY_SIGNAL,
    HumidityModel,
    RoomSensorDevice,
    RoomSensorModel,
    SensorModel,
    calibrate_room,
    changes_per_day,
    example_profile,
    example_room_sensor,
    report_stats,
    reversal_share,
)
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams, initial_state

T0 = 1_793_232_000.0
DAY = 86400.0
HOUR = 3600.0
GRID = RoomSensorModel(step_k=0.2, grid_offset_k=0.0, confirm_s=math.inf)


def wandering_room(days: float, seed: int = 3) -> tuple[np.ndarray, np.ndarray]:
    n = int(days * 1440)
    t = T0 + 60.0 * np.arange(n, dtype=np.float64)
    rng = np.random.default_rng(seed)
    walk = np.cumsum(rng.standard_normal(n)) * 0.004
    walk -= np.convolve(walk, np.ones(720) / 720, mode="same")
    daily = 0.3 * np.sin(2 * np.pi * (t - T0) / DAY)
    return t, (21.0 + daily + walk).astype(np.float64)


def recorded_by(model: RoomSensorModel, t: np.ndarray, air: np.ndarray, seed: int) -> Series:
    device = RoomSensorDevice(model)
    draws = np.random.default_rng(seed).standard_normal(t.size)
    times: list[float] = []
    values: list[float] = []
    for k in range(t.size):
        value = device.temperature(float(t[k]), float(air[k]), float(draws[k]))
        if value is not None and (not values or value != values[-1]):
            times.append(float(t[k]))
            values.append(value)
    return Series(np.asarray(times), np.asarray(values))


class TestDevice:
    def test_send_on_delta_with_hysteresis(self) -> None:
        device = RoomSensorDevice(replace(GRID, hysteresis_k=0.05))
        assert device.temperature(0.0, 21.32, 0.0) == pytest.approx(21.4)
        assert device.temperature(60.0, 21.48, 0.0) is None
        assert device.temperature(120.0, 21.54, 0.0) is None
        assert device.temperature(180.0, 21.56, 0.0) == pytest.approx(21.6)
        assert device.temperature(240.0, 21.46, 0.0) is None
        assert device.temperature(300.0, 21.34, 0.0) == pytest.approx(21.4)

    def test_samples_once_per_interval(self) -> None:
        device = RoomSensorDevice(GRID)
        assert device.temperature(0.0, 21.4, 0.0) is not None
        assert device.temperature(5.0, 22.2, 0.0) is None
        assert device.temperature(60.0, 22.2, 0.0) == pytest.approx(22.2)

    def test_heartbeat_and_force(self) -> None:
        device = RoomSensorDevice(replace(GRID, confirm_s=600.0))
        device.temperature(0.0, 21.4, 0.0)
        assert device.temperature(540.0, 21.4, 0.0) is None
        assert device.temperature(600.0, 21.4, 0.0) == pytest.approx(21.4)
        assert device.temperature(605.0, 21.4, 0.0, force=True) == pytest.approx(21.4)

    def test_recorded_liveness_times(self) -> None:
        device = RoomSensorDevice(replace(GRID, liveness_times=(10.0, 70.0, 80.0, 500.0)))
        assert device.liveness(5.0) is None
        assert device.liveness(60.0) == 10.0
        assert device.liveness(100.0) == 80.0
        assert device.liveness(100.0) is None
        assert device.liveness(1000.0) == 500.0

    def test_humidity_reports_about_six_times_a_day(self) -> None:
        rates = []
        for seed in range(4):
            device = RoomSensorDevice(replace(GRID, humidity=HumidityModel()), seed=seed)
            reports = [device.humidity(60.0 * k) for k in range(30 * 1440)]
            values = [r for r in reports if r is not None]
            assert all(abs(b - a) >= 1.0 for a, b in itertools.pairwise(values))
            rates.append(len(values) / 30.0)
        assert 4.0 < float(np.mean(rates)) < 9.0


class TestCalibration:
    def test_recovers_change_rate_and_reversals(self) -> None:
        t, air = wandering_room(20.0)
        truth = replace(GRID, noise_k=0.04, hysteresis_k=0.12)
        recorded = recorded_by(truth, t, air, seed=11)
        target_rate = changes_per_day(recorded)
        target_reversals = reversal_share(recorded)
        model = calibrate_room(recorded, air, t)
        assert model.step_k == pytest.approx(0.2)
        assert model.grid_offset_k == pytest.approx(0.0)
        assert model.confirm_s == math.inf
        changes, reversals = report_stats(
            air, np.random.default_rng(99).standard_normal(t.size), model
        )
        assert changes / 20.0 == pytest.approx(target_rate, rel=0.15)
        assert reversals / (changes - 1) == pytest.approx(target_reversals, abs=0.08)
        assert model.changes_per_day == target_rate
        assert model.reversal_share == target_reversals

    def test_liveness_times_from_recorded_states(self) -> None:
        t, air = wandering_room(2.0)
        recorded = recorded_by(GRID, t, air, seed=1)
        humidity = Series(np.array([T0 + 50.0, T0 + 100.0, T0 + 900.0]), np.array([55, 56, np.nan]))
        model = calibrate_room(recorded, air, t, profile=example_profile(), liveness=humidity)
        assert model.liveness_times == (T0 + 50.0, T0 + 100.0)
        assert model.profile.kind is RoomProfile.ON_CHANGE

    def test_example_device(self) -> None:
        example = example_room_sensor()
        assert (example.step_k, example.grid_offset_k) == (0.1, 0.0)
        assert example.confirm_s == math.inf
        assert example.humidity is not None
        assert example.profile.kind is RoomProfile.ON_CHANGE
        assert example.profile.liveness == (HUMIDITY_SIGNAL,)
        assert example.changes_per_day == pytest.approx(30.0)
        assert example.reversal_share == pytest.approx(0.35)


class TestStoreSemantics:
    def model(
        self, profile: RoomSensorProfile, liveness: tuple[float, ...] = ()
    ) -> RoomSensorModel:
        return replace(GRID, profile=profile, liveness_times=liveness)

    def test_held_value_alive_by_liveness(self) -> None:
        liveness = tuple(T0 + h * HOUR for h in range(1, 30))
        sensor = HaRoomSensor(self.model(example_profile(), liveness))
        first = sensor.view(T0, 21.72, 0.0)
        assert first is not None
        assert first.fresh
        later = sensor.view(T0 + 20 * HOUR, 21.75, 0.0)
        assert later is not None
        assert later.fresh
        assert later.held == pytest.approx(20 * HOUR)
        assert later.age == pytest.approx(0.0)
        assert later.alive_by == HUMIDITY_SIGNAL

    def test_silent_after_the_silence_limit(self) -> None:
        sensor = HaRoomSensor(self.model(example_profile()))
        sensor.view(T0, 21.72, 0.0)
        assert sensor.view(T0 + 23 * HOUR, 21.75, 0.0).fresh  # type: ignore[union-attr]
        assert not sensor.view(T0 + 25 * HOUR, 21.75, 0.0).fresh  # type: ignore[union-attr]

    def test_todays_1800_s(self) -> None:
        sensor = HaRoomSensor(self.model(RoomSensorProfile(step_k=0.2)))
        sensor.view(T0, 21.72, 0.0)
        assert sensor.view(T0 + 1800.0, 21.75, 0.0).fresh  # type: ignore[union-attr]
        assert not sensor.view(T0 + 1860.0, 21.75, 0.0).fresh  # type: ignore[union-attr]

    def test_modelled_humidity_keeps_the_value_alive(self) -> None:
        model = replace(example_room_sensor(), noise_k=0.0)
        sensor = HaRoomSensor(model, seed=2)
        fresh = []
        for k in range(3 * 1440):
            view = sensor.view(T0 + 60.0 * k, 21.75, 0.0)
            fresh.append(view is not None and view.fresh)
        assert all(fresh)


class TestVariants:
    PARAMS = PlantParams(HeatPumpParams(), BuildingParams(c_air=3.0e7, h_air_out=250.0))

    def test_variant_models(self) -> None:
        sensors = SensorModel(room=replace(example_room_sensor(), liveness_times=(T0,)))
        models = room_variant_models(sensors)
        ideal, today = models["ideal"].room, models["1800s"].room
        assert ideal.confirm_s == 0.0
        assert ideal.noise_k == 0.0
        assert ideal.profile.kind is RoomProfile.PERIODIC
        assert ideal.profile.quantum_k == 0.1
        assert today.profile.max_age_s == 1800.0
        assert today.liveness_times == ()
        assert today.noise_k == sensors.room.noise_k

    def test_profile_keeps_feedback_where_1800_s_loses_it(self) -> None:
        n = 2 * 1440
        hours = (np.arange(n) / 60.0) % 24.0
        weather = Weather(T0, 60.0, np.full(n, 3.0), np.zeros(n), hours.astype(np.float64))
        start = initial_state(self.PARAMS, 21.0, t_mass=23.0, t_water=26.0)
        liveness = tuple(T0 + 3600.0 * k for k in range(49))
        recorded = replace(example_room_sensor(), humidity=None, liveness_times=liveness)
        today = room_variant_models(SensorModel(room=recorded))["1800s"]
        traces = {}
        for name, sensors in (("profile", SensorModel(room=recorded)), ("1800s", today)):
            config = OvenbirdConfig.preset("mixed", comfort_room_c=21.0, room=sensors.room.profile)
            traces[name] = simulate(
                OvenbirdController(config),
                self.PARAMS,
                weather,
                start,
                LoopOptions(initial_setpoint=30, sensors=sensors),
            )
        assert traces["profile"].room_feedback.mean() > 0.95
        assert traces["1800s"].room_feedback.mean() < traces["profile"].room_feedback.mean()
        assert traces["1800s"].room_fresh.mean() < 0.9
