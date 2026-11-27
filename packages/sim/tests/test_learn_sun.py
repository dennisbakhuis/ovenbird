"""The sun gate's numbers on a simulated house: sunny days, ablation skill, response slope."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ovenbird_sim.data.dataset import FLAGS, Dataset, OffsetCalibration
from ovenbird_sim.data.grid import TimeGrid
from ovenbird_sim.heishamon.reference import REFERENCE_BUILDING
from ovenbird_sim.identify.building import CHAIN_FIXED, internal_gains
from ovenbird_sim.learn import checks
from ovenbird_sim.learn.sun import SunEvaluator, sunny_days
from ovenbird_sim.model.building import BuildingParams, simulate_batch

START = 1_789_948_800.0
STEP = 300.0
PER_DAY = round(86400.0 / STEP)
TRUTH = REFERENCE_BUILDING.replace(**dict(CHAIN_FIXED), solar_aperture_m2=6.0)


def simulated(clear: list[float], p: BuildingParams = TRUTH, seed: int = 2) -> Dataset:
    """A building-only dataset: the room and loop of ``p`` under a sun with a daily clearness."""
    rng = np.random.default_rng(seed)
    days = len(clear)
    n = days * PER_DAY
    grid = TimeGrid(START, STEP, n)
    t = grid.edges
    hour = (t % 86400.0) / 3600.0
    day = np.repeat(np.arange(days), PER_DAY)
    sky = np.asarray(clear)[day]
    ghi = sky * np.clip(500.0 * np.sin(np.pi * (hour - 8.0) / 8.0), 0.0, None)
    outside = 4.0 + 3.0 * np.sin(2.0 * np.pi * (hour - 9.0) / 24.0)
    period = rng.integers(18, 48, size=n // 18 + 1).repeat(18)[:n]
    heat = np.where((np.arange(n) % period) < period // 2, 2500.0, 0.0)
    u = np.column_stack([heat, outside, ghi, internal_gains(p, hour)])
    x = simulate_batch(p, STEP, np.array([[28.0, 23.0, 21.0]]), u[None, :-1])[0]
    room = x[:, 2] + rng.normal(0.0, 0.02, n)
    water = x[:, 0]
    columns = {
        "room": room,
        "outside": outside,
        "ghi": ghi,
        "heat_w": heat,
        "compressor_frac": (heat > 0).astype(np.float64),
        "local_hour": hour,
        "inlet": water - 2.0,
        "outlet": water + 2.0,
    }
    flags = {name: np.zeros(n, dtype=np.bool_) for name in FLAGS}
    return Dataset(grid, columns, flags, OffsetCalibration(0.0, 0.0, 0.0, 0, 0.0), {}, ())


SKIES = [1.0, 0.1, 0.9, 0.2, 1.0, 0.8, 0.1, 1.0, 0.3, 0.95, 0.15, 0.85, 1.0, 0.2]


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return simulated(SKIES)


def test_sunny_days_count_whole_local_days_with_three_hours_of_sun(ds: Dataset) -> None:
    days, sunny = sunny_days(ds, 0, ds.grid.n)
    assert days == len(SKIES)
    assert sunny == sum(1 for c in SKIES if c * 500.0 > 150.0 / math.sin(math.pi * 1.5 / 8.0))
    assert sunny_days(ds, 0, PER_DAY // 2) == (0, 0)


def test_the_true_model_passes_the_sun_gate(ds: Dataset) -> None:
    sun = SunEvaluator(ds, TRUTH).check(START, START + len(SKIES) * 86400.0)
    assert sun.sunny_days >= checks.SUNNY_DAYS
    assert sun.ablation_skill > 0.3
    assert sun.beta == pytest.approx(1.0, abs=0.1)
    assert sun.beta_interval is not None
    assert sun.beta_interval[0] < 1.0 < sun.beta_interval[1]
    assert checks.sun_gate(sun)["ok"] is True


def test_a_doubled_aperture_fails_the_sun_gate(ds: Dataset) -> None:
    wrong = TRUTH.replace(solar_aperture_m2=2.0 * TRUTH.solar_aperture_m2)
    sun = SunEvaluator(ds, wrong).check(START, START + len(SKIES) * 86400.0)
    assert sun.beta == pytest.approx(0.5, abs=0.06)
    assert sun.beta_interval is not None
    assert sun.beta_interval[1] < checks.BETA_RANGE[0]
    gate = checks.sun_gate(sun)
    assert gate["ok"] is False
    assert "sun_response_off" in gate["needed"]


def test_a_model_without_sun_has_no_sun_skill(ds: Dataset) -> None:
    dark = TRUTH.replace(solar_aperture_m2=0.0)
    sun = SunEvaluator(ds, dark).check(START, START + len(SKIES) * 86400.0)
    assert math.isnan(sun.ablation_skill)
    assert math.isnan(sun.beta)
    gate = checks.sun_gate(sun)
    assert gate["needed"] == ["no_sun_skill", "sun_response_off"]


def test_a_grey_block_asks_for_more_sunny_days() -> None:
    grey = simulated([0.1, 0.2, 1.0, 0.1, 0.15, 1.0, 0.2, 0.1])
    sun = SunEvaluator(grey, TRUTH).check(START, START + 8 * 86400.0)
    assert sun.sunny_days == 2
    gate = checks.sun_gate(sun)
    assert gate["ok"] is False
    assert gate["needed"][0] == "more_sunny_days"
    assert gate["message"].startswith("3 more sunny days")
