"""The room series of a model: measured against the 24 h-ahead prediction."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from ovenbird_sim.data import events as ev
from ovenbird_sim.data.dataset import Dataset
from ovenbird_sim.data.synthetic import simulated_dataset
from ovenbird_sim.learn.run import iso
from ovenbird_sim.learn.series import COLUMNS, SERIES_DAYS, SERIES_STEP_S, room_series
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams, PlantState

START = 1_789_999_200.0
DAYS = 20


@pytest.fixture(scope="module")
def recording() -> tuple[PlantParams, Dataset]:
    n = DAYS * 1440
    minutes = np.arange(n)
    outside = 5.0 + 5.0 * np.sin(2 * np.pi * minutes / 1440.0)
    ghi = np.clip(250.0 * np.sin(np.pi * ((minutes / 60.0) % 24 - 7.0) / 10.0), 0.0, None)
    setpoint = np.where((minutes // 360) % 2 == 0, 33.0, 29.0).astype(float)
    params = PlantParams(HeatPumpParams(), BuildingParams())
    state = PlantState(t_water=27.0, t_mass=25.0, t_air=21.0, off_s=3600.0)
    return params, simulated_dataset(params, state, setpoint, outside, ghi, start=START)


def test_series_has_the_last_fourteen_days_at_quarter_hours(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    held_out = START + 3 * 86400.0
    body = room_series(coarse, coarse, params.building, held_out, iso)
    rows = body["rows"]
    assert len(rows) == SERIES_DAYS * 96
    assert body["out_of_sample_from"] == iso(held_out)
    assert body["events"] == []
    assert body["columns"] == list(COLUMNS)
    assert body["step_s"] == SERIES_STEP_S
    assert body["from"] == rows[0][0]
    assert body["to"] == rows[-1][0]
    assert all(len(row) == 3 for row in rows)


def test_rows_start_at_the_first_prediction(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    held_out = START + 10 * 86400.0
    body = room_series(coarse, coarse, params.building, held_out, iso)
    first = body["predicted_from"]
    assert first is not None
    assert first >= iso(held_out + 86400.0)
    assert body["from"] == first
    assert body["rows"][0][2] is not None
    assert len(body["rows"]) < SERIES_DAYS * 96
    assert all(row[2] is not None for row in body["rows"])
    assert body["points"] == len(body["rows"])


def test_the_true_model_predicts_its_own_simulation(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    body = room_series(coarse, coarse, params.building, START + 6 * 86400.0, iso)
    pairs = [(row[1], row[2]) for row in body["rows"] if row[1] is not None and row[2] is not None]
    assert len(pairs) > 800
    error = math.sqrt(sum((m - p) ** 2 for m, p in pairs) / len(pairs))
    assert error < 0.5


def test_no_prediction_before_the_held_out_block_exists(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    body = room_series(coarse, coarse, params.building, START + 40 * 86400.0, iso)
    assert body["predicted_from"] is None
    assert all(row[2] is None for row in body["rows"])
    assert any(row[1] is not None for row in body["rows"])


def test_an_event_nulls_every_prediction_whose_path_it_touches(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    fire_start, fire_end = START + 12 * 86400.0, START + 12 * 86400.0 + 4 * 3600.0
    fire = ev.Event(ev.STOVE_MODE, fire_start, fire_end, fire_end + ev.TAIL_S, math.nan, math.nan)
    scored = replace(coarse, events=(fire,))
    body = room_series(scored, coarse, params.building, START + 6 * 86400.0, iso)
    assert body["events"] == [
        {
            "kind": ev.STOVE_MODE,
            "from": iso(fire_start),
            "to": iso(fire_end),
            "tail_to": iso(fire_end + ev.TAIL_S),
        }
    ]
    touched = [
        row
        for row in body["rows"]
        if iso(fire_start) <= row[0] < iso(fire_end + ev.TAIL_S + 86400.0)
    ]
    assert touched
    assert all(row[2] is None for row in touched)
    assert all(row[1] is not None for row in touched)
    clear = [row for row in body["rows"] if row[0] >= iso(fire_end + ev.TAIL_S + 86400.0)]
    assert clear
    assert all(row[2] is not None for row in clear)
    assert body["points"] == sum(1 for row in body["rows"] if row[2] is not None)


def test_the_champion_series_scores_only_its_unseen_days(
    recording: tuple[PlantParams, Dataset],
) -> None:
    params, ds = recording
    coarse = ds.coarsen(5)
    seen = START + 15 * 86400.0
    body = room_series(coarse, coarse, params.building, -math.inf, iso, out_of_sample_from=seen)
    assert body["out_of_sample_from"] == iso(seen)
    assert body["predicted_from"] == body["from"]
    predicted = [row for row in body["rows"] if row[2] is not None]
    unseen = [row for row in predicted if row[0] >= iso(seen + 86400.0)]
    assert len(predicted) > len(unseen) > 0
    assert body["points"] == len(unseen)
    assert body["rmse_k"] is not None
    assert body["rmse_k"] < 0.5
    assert abs(body["bias_k"]) <= body["rmse_k"]
    nothing = room_series(coarse, coarse, params.building, START + 40 * 86400.0, iso)
    assert (nothing["rmse_k"], nothing["bias_k"], nothing["points"]) == (None, None, 0)
