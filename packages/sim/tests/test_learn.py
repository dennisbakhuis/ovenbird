from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ovenbird_sim.data import events as ev
from ovenbird_sim.data.historydb import (
    HistoryRoles,
    effective_config,
    fill_outside,
    history_dataset,
    roles_from_config,
)
from ovenbird_sim.heishamon.reference import REFERENCE_BUILDING
from ovenbird_sim.identify.validate import HORIZONS_H, HorizonErrors
from ovenbird_sim.learn import models as store
from ovenbird_sim.learn import run
from ovenbird_sim.learn.proposal import CurveLimits, propose_curve, steady_state
from ovenbird_sim.learn.score import band, score
from ovenbird_sim.model.building import BuildingParams

history = pytest.importorskip("ovenbird.history")
from ovenbird.history import HistoryDatabase, Sample, SampleKind, open_history  # noqa: E402
from ovenbird.history.database import HEAT_SIGNAL  # noqa: E402
from ovenbird.history.forecast import ForecastRow, write_forecast  # noqa: E402
from ovenbird.history.journal import AlarmRow, write_journal  # noqa: E402
from ovenbird.insight.house import checked_insight  # noqa: E402

T0 = datetime(2026, 11, 10, tzinfo=UTC).timestamp()
ROOM = "ha/sensor.living_temperature"
HALL = "ha/sensor.hall_temperature"
TZ = "Europe/Amsterdam"
FLOW = 15.0
OFFSET = 0.3
W_PER_LPM_K = 0.996 * 4180.0 / 60.0
HOLD = 330.0
CURVE = [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]]
PARAMS = REFERENCE_BUILDING


def plant(ts: float) -> dict[str, float | None]:
    minute = int((ts - T0) // 60) % 60
    hour = int((ts - T0) // 3600)
    running = minute < 30
    dhw = hour == 4 and minute < 30
    inlet, outlet = (28.0, 32.0) if running else (27.0, 27.0 + OFFSET)
    heat = None if dhw else (FLOW * W_PER_LPM_K * (outlet - inlet) if running else 0.0)
    return {
        "main/Main_Inlet_Temp": inlet,
        "main/Main_Outlet_Temp": outlet,
        "main/Pump_Flow": FLOW,
        "main/Compressor_Freq": 30.0 if running else 0.0,
        "main/Main_Target_Temp": 32.0,
        "main/Outside_Temp": 5.0,
        "main/Defrosting_State": 0.0,
        "main/ThreeWay_Valve_State": 1.0 if dhw else 0.0,
        HEAT_SIGNAL: heat,
        ROOM: 21.0 + 0.5 * math.sin(2 * math.pi * (ts - T0) / 86400.0),
        HALL: 19.0,
    }


def write_history(path: Path, days: float = 2.0) -> Path:
    db = HistoryDatabase(open_history(path))
    samples: list[Sample] = []
    for ts in np.arange(T0, T0 + days * 86400.0, 30.0):
        for signal, value in plant(float(ts)).items():
            kind = SampleKind.ENUM if signal.endswith("State") else SampleKind.NUMBER
            samples.append(Sample(signal, None, kind, float(ts), value, HOLD))
    db.write_batch(samples)
    write_forecast(
        db.conn,
        [ForecastRow(T0, T0 + h * 3600.0, 5.0, 100.0, 50.0, 2.0) for h in range(int(days * 24) + 1)]
        + [
            ForecastRow(T0 + 12 * 3600.0, T0 + h * 3600.0, 6.0, 100.0, 50.0, 2.0)
            for h in range(int(days * 24) + 1)
        ],
    )
    write_journal(
        db.conn,
        [],
        [],
        [
            AlarmRow(T0 + 30 * 3600.0, "stove_mode", "info", "started", "on", "{}"),
            AlarmRow(T0 + 34 * 3600.0, "stove_mode", "info", "expired", "off", "{}"),
        ],
    )
    db.close()
    return path


@pytest.fixture(scope="module")
def history_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_history(tmp_path_factory.mktemp("history") / "history.db")


ROLES = HistoryRoles(ROOM, (HALL,), TZ)


def minute(ds: Any, offset_s: float) -> int:
    index: int = round((T0 + offset_s - ds.grid.start) / ds.grid.step)
    return index


def test_adapter_round_trip(history_db: Path) -> None:
    data = history_dataset(history_db, ROLES, step=60)
    ds = data.dataset
    assert data.step == 60
    assert ds.grid.start == T0
    assert ds.grid.n == pytest.approx(2 * 1440, abs=1)
    running, idle = minute(ds, 10 * 3600 + 600), minute(ds, 10 * 3600 + 2700)
    assert ds.col("inlet")[running] == pytest.approx(28.0)
    assert ds.col("outlet")[idle] == pytest.approx(27.0 + OFFSET)
    assert ds.col("compressor_frac")[running] == 1.0
    assert ds.col("compressor_frac")[idle] == 0.0
    assert ds.calibration.offset_k == pytest.approx(OFFSET, abs=0.01)
    expected = FLOW * W_PER_LPM_K * (4.0 - OFFSET)
    assert ds.col("heat_w")[running] == pytest.approx(expected, rel=0.01)
    assert ds.col("heat_w")[idle] == pytest.approx(0.0, abs=1.0)
    dhw = minute(ds, 4 * 3600 + 600)
    assert ds.flag("dhw")[dhw]
    assert not np.isfinite(ds.col("heat_w")[dhw])
    assert ds.col("room")[running] == pytest.approx(plant(T0 + 10 * 3600 + 630)[ROOM], abs=0.01)
    house = 0.5 * (ds.col("room")[running] + 19.0)
    assert ds.col("house_mean")[running] == pytest.approx(house, abs=0.01)
    assert ds.col("room_living")[running] == pytest.approx(ds.col("room")[running])
    assert ds.col("local_hour")[0] == pytest.approx(1.0)
    assert "stored" in data.notes["heat"]
    assert data.base.step == 60.0
    assert data.base.hz[running] == 30.0


def test_adapter_weather_uses_the_shortest_lead(history_db: Path) -> None:
    ds = history_dataset(history_db, ROLES, step=60).dataset
    assert ds.col("outside_wx")[minute(ds, 6 * 3600)] == pytest.approx(5.0)
    assert ds.col("outside_wx")[minute(ds, 20 * 3600)] == pytest.approx(6.0)
    assert ds.col("ghi")[minute(ds, 20 * 3600)] == pytest.approx(100.0)


def test_adapter_flags_the_stove_journal(history_db: Path) -> None:
    ds = history_dataset(history_db, ROLES, step=60).dataset
    journal = [e for e in ds.events if e.kind == ev.STOVE_MODE]
    assert len(journal) == 1
    assert journal[0].start == T0 + 30 * 3600.0
    assert journal[0].tail_end == T0 + 34 * 3600.0 + ev.TAIL_S
    assert ds.event_mask()[minute(ds, 31 * 3600)]
    assert not ds.event_mask()[minute(ds, 10 * 3600)]
    assert journal[0].to_json(TZ)["peak_k"] is None


def test_adapter_quarter_hour_and_span(history_db: Path) -> None:
    ds = history_dataset(history_db, ROLES, step=900, start=T0 + 86400.0).dataset
    assert ds.grid.step == 900.0
    assert ds.grid.start == T0 + 86400.0
    assert ds.grid.n == 96


def test_adapter_without_loop_signals_raises(tmp_path: Path) -> None:
    db = HistoryDatabase(open_history(tmp_path / "history.db"))
    db.write_batch(
        [Sample(ROOM, "°C", SampleKind.NUMBER, T0 + i * 30.0, 21.0, HOLD) for i in range(10)]
    )
    db.close()
    with pytest.raises(ValueError, match="loop signals"):
        history_dataset(tmp_path / "history.db", ROLES, step=60)


def test_roles_and_config_documents() -> None:
    flat = {
        "control_room_signal": ROOM,
        "control_stove_reference_signal": HALL,
        "control_timezone": TZ,
    }
    roles = roles_from_config(flat)
    assert roles == ROLES
    assert roles.room_roles().references == ("room_ref_1",)
    assert effective_config({"effective": flat}) == flat
    assert effective_config({"fields": {k: {"value": v} for k, v in flat.items()}}) == flat
    assert effective_config({"values": flat}) == flat
    assert roles_from_config({}).room is None


def test_fill_outside_bridges_short_runs_only() -> None:
    outside = np.array([1.0, np.nan, np.nan, 3.0, np.nan] + [np.nan] * 30 + [5.0])
    sensor = np.full(outside.size, -2.0)
    filled = fill_outside(outside, sensor, 3600.0)
    assert filled[1] == pytest.approx(5.0 / 3.0)
    assert filled[10] == -2.0


@pytest.mark.parametrize(
    ("challenger", "champion", "tolerance", "promoted"),
    [
        (0.5, None, 0.0, True),
        (0.5, 0.6, 0.0, True),
        (0.6, 0.6, 0.0, True),
        (0.61, 0.6, 0.0, False),
        (0.61, 0.6, 0.02, True),
        (math.nan, 0.6, 0.0, False),
        (0.5, math.nan, 0.0, True),
    ],
)
def test_promotion_rule(
    challenger: float, champion: float | None, tolerance: float, promoted: bool
) -> None:
    decision, rule = run.decide_promotion(challenger, champion, tolerance)
    assert decision is promoted
    assert rule


def test_score_bands_and_states() -> None:
    assert [band(w) for w in (10, 30, 45, 60, 80, 100, 125, 400)] == list("ABCDEFGG")
    ready = score(145.0, (136.0, 156.0), 130.0, credible=True)
    assert (ready["state"], ready["band"], ready["w_per_m2"]) == ("ready", "B", 33.5)
    assert ready["band_interval"] == ["B", "B"]
    assert score(145.0, None, None, credible=True)["state"] == "no_floor_area"
    assert score(145.0, None, 130.0, credible=False, needed="x")["message"] == "x"


def test_steady_state_heat_balance() -> None:
    heat, loop = steady_state(PARAMS, 21.0, -10.0)
    assert heat == pytest.approx(145.0 * 31.0 - 325.0)
    k = PARAMS.h_water_air + PARAMS.h_water_mass * PARAMS.h_mass_air / (
        PARAMS.h_water_mass + PARAMS.h_mass_air
    )
    assert loop == pytest.approx(21.0 + heat / k)
    assert steady_state(PARAMS, 21.0, 30.0)[0] == 0.0


def test_proposal_stays_within_limits() -> None:
    limits = CurveLimits(24.0, 37.0, tuple((o, w) for o, w in CURVE), 6.0, 5.0)
    proposal = propose_curve(
        PARAMS, 21.0, [(o, w) for o, w in CURVE], limits, flow_lpm=17.0, coldest_c=-2.0
    )
    waters = [w for _, w in proposal["curve"]]
    assert waters == sorted(waters, reverse=True)
    for row in proposal["points"]:
        lo, hi = limits.band(row["outside_c"])
        assert lo - 1e-9 <= row["water_c"] <= hi + 1e-9
        assert row["water_c"] * 2 == int(row["water_c"] * 2)
        assert row["change_k"] == pytest.approx(row["water_c"] - row["current_c"])
    cold, mild, warm = proposal["points"]
    assert cold["extrapolated"] is True
    assert (cold["water_c"], cold["limited_by"]) == (37.0, "max_supply")
    assert mild["limited_by"] is None
    assert mild["water_c"] == round(mild["model_c"] * 2) / 2
    assert warm["extrapolated"] is False
    assert proposal["based_on_curve"] == CURVE
    raised = CurveLimits(30.0, 40.0)
    floor = propose_curve(PARAMS, 21.0, [(15.0, 25.0), (20.0, 25.0)], raised)
    assert [p["limited_by"] for p in floor["points"]] == ["min_setpoint", "min_setpoint"]
    assert floor["curve"] == [[15.0, 30.0], [20.0, 30.0]]


def test_proposal_clamps_a_leaky_house_to_the_maximum() -> None:
    leaky = PARAMS.replace(h_air_out=900.0)
    limits = CurveLimits(20.0, 40.0)
    proposal = propose_curve(leaky, 21.0, [(-10.0, 39.0), (15.0, 25.0)], limits)
    assert proposal["points"][0]["water_c"] == 40.0
    assert proposal["points"][0]["limited_by"] == "max_supply"


CONFIG = {
    "control_room_signal": ROOM,
    "control_stove_reference_signal": HALL,
    "control_timezone": TZ,
    "control_comfort_c": 21.0,
    "control_min_setpoint_c": 24.0,
    "control_curve": CURVE,
    "house_floor_area_m2": 130.0,
}


def test_learner_waits_for_enough_history(history_db: Path, tmp_path: Path) -> None:
    status = run.learn(history_db, CONFIG, tmp_path / "models")
    assert status["outcome"] == "learning"
    assert any("more days of 1 min history" in item for item in status["missing"])
    written = json.loads((tmp_path / "models" / store.STATUS).read_text())
    assert written["outcome"] == "learning"
    assert not (tmp_path / "models" / store.CURRENT).exists()


def test_learner_needs_a_room_signal(history_db: Path, tmp_path: Path) -> None:
    status = run.learn(history_db, {}, tmp_path / "models")
    assert status["outcome"] == "learning"
    assert "control_room_signal" in status["missing"][0]


def fake_fit(split: float, end: float) -> run.FitOutcome:
    return run.FitOutcome(
        method="building_only",
        building=PARAMS,
        intervals={"h_air_out": (136.0, 156.0), "time_constant_h": (45.0, 60.0)},
        plant=None,
        split=split,
        end=end,
        train_building=PARAMS,
        folds=[],
        fit_rmse_room_k=0.2,
        windows=10,
    )


def iso_of(ts: float) -> str:
    return run.iso(ts)


def errors(room_24h: float) -> HorizonErrors:
    room = tuple(room_24h if h == 24.0 else 0.1 for h in HORIZONS_H)
    return HorizonErrors(HORIZONS_H, room, room, room, 5)


def test_champion_challenger_files(
    history_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    split, end = T0 + 86400.0, T0 + 2 * 86400.0
    monkeypatch.setattr(run, "_readiness", lambda ds, options: [])
    monkeypatch.setattr(run, "_fit", lambda ds, data, options, full: fake_fit(split, end))
    challenger_errors = iter([errors(0.40), errors(0.50), errors(0.45)])
    champion_errors = iter([errors(0.45)])

    def horizons(coarse: Any, p: BuildingParams, start: float, stop: float) -> HorizonErrors:
        if (start, stop) != (split, end):
            return errors(0.3)
        return next(challenger_errors) if p is PARAMS else next(champion_errors)

    monkeypatch.setattr(run, "horizon_errors", horizons)
    first = run.learn(history_db, CONFIG, models)
    assert first["outcome"] == "promoted", first
    current = json.loads((models / store.CURRENT).read_text())
    assert current["model"] == "house-20261111"
    insight = json.loads((models / "insight-20261111.json").read_text())
    assert insight["schema"] == store.INSIGHT_SCHEMA
    assert insight["ua"]["w_per_k"] == 145.0
    assert insight["ua"]["interval_90"] == [136.0, 156.0]
    assert insight["score"]["state"] == "learning"
    assert insight["credibility"]["credible"] is False
    assert insight["credibility"]["message"].startswith("insufficient data")
    assert insight["proposal"]["based_on_curve"] == CURVE
    assert insight["validation"]["promoted"] is True
    assert insight["provenance"]["config_hash"] == run.config_hash(CONFIG)
    assert any(e["kind"] == ev.STOVE_MODE for e in insight["events"])
    house = json.loads((models / "house-20261111.json").read_text())
    assert house["schema"] == "ovenbird.plant-params/1"
    assert house["params"]["building"]["h_air_out"] == 145.0
    series = json.loads((models / "series-20261111.json").read_text())
    assert series["schema"] == "ovenbird.house-series/1"
    assert series["model"] == "house-20261111"
    assert series["step_s"] == 900
    assert series["columns"] == ["ts", "room_measured", "room_predicted_24h"]
    assert series["to"] == series["rows"][-1][0]
    assert all(len(row) == 3 for row in series["rows"])
    assert series["predicted_from"] is None or series["predicted_from"] >= iso_of(split)
    measured = [row[1] for row in series["rows"] if row[1] is not None]
    assert measured
    assert all(20.0 < value < 22.0 for value in measured)
    assert store.index_runs(models)[0]["series"] == "series-20261111.json"

    monkeypatch.setattr(run, "horizon_errors", horizons)
    champion_errors = iter([errors(0.40)])
    second = run.learn(history_db, CONFIG, models)
    assert second["outcome"] == "kept_champion", second
    assert second["validation"]["champion_room_rmse_k"] == 0.40
    assert second["validation"]["challenger_room_rmse_k"] == 0.50
    assert second["model"] == "house-20261111-2"
    runs = store.index_runs(models)
    assert [(r["model"], r["promoted"]) for r in runs] == [
        ("house-20261111", True),
        ("house-20261111-2", False),
    ]
    assert json.loads((models / store.CURRENT).read_text())["model"] == "house-20261111"
    assert (models / "series-20261111-2.json").exists()
    assert store.series_name("house-20261111-2") == "series-20261111-2.json"
    kept = json.loads((models / "insight-20261111.json").read_text())
    assert kept["validation"]["promoted"] is True
    trend = json.loads((models / "insight-20261111-2.json").read_text())["error_trend"]
    assert [t["model"] for t in trend] == ["house-20261111", "house-20261111-2"]


def test_owner_excluded_days_are_masked_and_listed(history_db: Path) -> None:
    days = ev.excluded_days(["2026-11-10", "2026-11-10"], TZ)
    assert len(days) == 1
    ds = history_dataset(history_db, ROLES, step=60, excluded=days).dataset
    owner = [e for e in ds.events if e.kind == ev.EXCLUDED_DAY]
    assert len(owner) == 1
    assert (owner[0].start, owner[0].end) == (T0 - 3600.0, T0 + 23 * 3600.0)
    assert owner[0].tail_end == owner[0].end
    assert [e.kind for e in ds.events] == [ev.EXCLUDED_DAY, ev.STOVE_MODE]
    mask = ds.event_mask()
    assert mask[minute(ds, 10 * 3600)]
    assert not mask[minute(ds, 23 * 3600 + 120)]
    assert mask[minute(ds, 31 * 3600)]
    payload = owner[0].to_json(TZ)
    assert payload["kind"] == "excluded_day"
    assert payload["start_local"] == "2026-11-10T00:00+01:00"
    assert payload["end_local"] == payload["tail_end_local"] == "2026-11-11T00:00+01:00"
    assert payload["hours"] == payload["excluded_hours"] == 24.0
    assert payload["peak_k"] is None
    assert "house_learn_excluded_days" in str(payload["reason"])
    assert set(payload) == set(ds.events[1].to_json(TZ))
    scored = run.scoring_view(ds.coarsen(5))
    room = scored.col("room")
    assert not np.isfinite(room[round(10 * 3600 / 300)])
    assert np.isfinite(room[round(26 * 3600 / 300)])


def test_excluded_day_spans_a_daylight_saving_change() -> None:
    (spring,) = ev.excluded_days(["2026-03-29"], TZ)
    assert spring.hours == 23.0
    with pytest.raises(ValueError, match="month"):
        ev.excluded_days(["2026-13-01"], TZ)


def test_invalid_house_settings_stop_the_run(
    history_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: Any) -> run.FitOutcome:
        raise AssertionError("no fit with invalid settings")

    monkeypatch.setattr(run, "_fit", never)
    config = CONFIG | {"house_ua_min_w_per_k": 900.0, "house_ua_max_w_per_k": 300.0}
    status = run.learn(history_db, config, tmp_path / "models")
    assert status["outcome"] == "failed"
    assert status["setting"] == "house_ua_min_w_per_k"
    assert "house_ua_min_w_per_k" in status["error"]
    assert "house_ua_max_w_per_k" in status["error"]
    written = json.loads((tmp_path / "models" / store.STATUS).read_text())
    assert written["outcome"] == "failed"


FACTS = {
    "house_build_period": "1975_1991",
    "house_occupants": 2,
    "house_window_area_m2": 20.0,
    "house_ua_max_w_per_k": 400.0,
    "house_learn_excluded_days": ["2026-11-10"],
}


def test_changed_house_settings_promote_a_worse_model(
    history_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    split, end = T0 + 86400.0, T0 + 2 * 86400.0
    monkeypatch.setattr(run, "_readiness", lambda ds, options: [])
    seen: list[Any] = []

    def fit(ds: Any, data: Any, options: Any, full: bool) -> run.FitOutcome:
        seen.append((options.priors, [e.kind for e in ds.events]))
        return fake_fit(split, end)

    monkeypatch.setattr(run, "_fit", fit)
    challenger_errors = iter([errors(0.40), errors(0.50), errors(0.50)])
    champion_errors = iter([errors(0.40), errors(0.40)])

    def horizons(coarse: Any, p: BuildingParams, start: float, stop: float) -> HorizonErrors:
        if (start, stop) != (split, end):
            return errors(0.3)
        return next(challenger_errors) if p is PARAMS else next(champion_errors)

    monkeypatch.setattr(run, "horizon_errors", horizons)
    first = run.learn(history_db, CONFIG, models)
    assert first["outcome"] == "promoted"
    assert first["validation"]["settings_changed"] is False
    house = json.loads((models / "house-20261111.json").read_text())
    assert house["provenance"]["constraints"] == {}

    told = CONFIG | FACTS
    second = run.learn(history_db, told, models)
    assert second["outcome"] == "promoted", second
    assert second["message"].startswith(run.SETTINGS_CHANGED)
    validation = second["validation"]
    assert validation["settings_changed"] is True
    assert validation["rule"].startswith(run.SETTINGS_CHANGED)
    assert (validation["challenger_room_rmse_k"], validation["champion_room_rmse_k"]) == (
        0.50,
        0.40,
    )
    priors, kinds = seen[-1]
    assert priors.params["h_air_out"].upper == 400.0
    assert ev.EXCLUDED_DAY in kinds
    insight = json.loads((models / "insight-20261111.json").read_text())
    provenance = insight["provenance"]
    assert provenance["constraints"] == {
        "house_floor_area_m2": 130.0,
        "house_build_period": "1975_1991",
        "house_window_area_m2": 20.0,
        "house_occupants": 2,
        "house_ua_max_w_per_k": 400.0,
    }
    assert provenance["told"] == {
        "ua_w_per_k": pytest.approx(130.0 * 2.0434, abs=0.2),
        "solar_aperture_m2": 3.9,
        "internal_gain_w": 280.0,
    }
    assert provenance["learning"]["excluded_days"] == ["2026-11-10"]
    assert provenance["learning"]["excluded_days_in_fit"] == 1
    assert (provenance["learning"]["fit_days"], provenance["learning"]["test_days"]) == (60.0, 14)
    assert insight["data"]["owner_excluded_days"] == ["2026-11-10"]
    assert "2026-11-10" in insight["data"]["excluded_days"]
    owner = [e for e in insight["events"] if e["kind"] == ev.EXCLUDED_DAY]
    assert [e["start_local"] for e in owner] == ["2026-11-10T00:00+01:00"]
    assert insight["validation"]["settings_changed"] is True
    stored = json.loads((models / "house-20261111.json").read_text())
    assert stored["provenance"]["constraints"] == provenance["constraints"]
    served = checked_insight(insight)
    assert served["provenance"]["constraints"] == provenance["constraints"]
    assert served["provenance"]["told"] == provenance["told"]
    assert served["data"]["owner_excluded_days"] == ["2026-11-10"]

    third = run.learn(history_db, told, models)
    assert third["outcome"] == "kept_champion", third
    assert third["validation"]["settings_changed"] is False


def test_constraint_promotion_rule() -> None:
    promote, rule = run.decide_promotion(0.9, 0.4, settings_changed=True)
    assert promote
    assert "0.900 K" in rule
    assert "0.400 K" in rule
    assert run.decide_promotion(math.nan, 0.4, settings_changed=True)[0] is False
    assert run.decide_promotion(0.9, None, settings_changed=True)[0] is True
    assert run.decide_promotion(0.9, 0.4)[0] is False
    assert run.champion_constraints(None) is None
    assert run.champion_constraints({"house_payload": {"provenance": {}}}) == {}
