from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.control.loop import ControlLoop
from ovenbird.history import open_history
from ovenbird.history.forecast import ForecastRow, write_forecast
from ovenbird.history.journal import AlarmRow, write_journal
from ovenbird.insight import house, whatif
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock
from ovenbird.weather import OpenMeteoProvider, WeatherService
from ovenbird_core import HeishaSignal, Reading, SourceKind
from ovenbird_core.housemodel import HouseModel

TOKEN = "operate-token-" + "x" * 24
MODEL = "house-20261113"
ROOM = "room_temperature"
NOW = datetime(2026, 11, 13, 12, 20, tzinfo=UTC).timestamp()
HOUR = datetime(2026, 11, 13, 12, 0, tzinfo=UTC).timestamp()
BUILDING = {
    "c_water": 2.5e6,
    "c_mass": 4.0e7,
    "c_air": 1.0e7,
    "h_water_mass": 400.0,
    "h_water_air": 150.0,
    "h_mass_air": 800.0,
    "h_air_out": 200.0,
    "solar_aperture_m2": 3.0,
    "solar_mass_fraction": 0.5,
    "q_int_w": 300.0,
    "q_int_modulation": 0.0,
    "q_int_peak_hour": 19.0,
}
FACTS = {"house_build_period": "1992_2005", "house_floor_area_m2": 130.0}


def series_rows(count: int = 96) -> list[list[Any]]:
    start = datetime(2026, 11, 12, 0, 0, tzinfo=UTC).timestamp()
    return [
        [
            datetime.fromtimestamp(start + 900 * k, UTC).isoformat(timespec="seconds"),
            20.0 + 0.01 * k,
            None if k < 10 else 20.1 + 0.01 * k,
        ]
        for k in range(count)
    ]


def series_file(model: str = MODEL, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": "ovenbird.house-series/1",
        "model": model,
        "step_s": 900,
        "horizon_h": 24.0,
        "predicted_from": "2026-11-12T02:30:00+00:00",
        "columns": ["ts", "room_measured", "room_predicted_24h"],
        "rows": series_rows(),
    }
    return body | changes


def write_models(
    root: Path,
    *,
    credible: bool = True,
    building: dict[str, Any] | None = None,
    series: bool = True,
) -> Path:
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    house_file = {"schema": "ovenbird.plant-params/1", "params": {"building": building or BUILDING}}
    (models / f"{MODEL}.json").write_text(json.dumps(house_file))
    insight = {
        "schema": "ovenbird.house-insight/1",
        "model": MODEL,
        "ua": {"w_per_k": 200.0, "interval_90": [180.0, 220.0]},
        "credibility": {"credible": credible, "message": None},
    }
    (models / "insight-20261113.json").write_text(json.dumps(insight))
    (models / "current.json").write_text(
        json.dumps(
            {
                "model": MODEL,
                "house": f"{MODEL}.json",
                "insight": "insight-20261113.json",
                "promoted_at": "2026-11-13T09:00:00+00:00",
            }
        )
    )
    if series:
        (models / "series-20261113.json").write_text(json.dumps(series_file()))
    return models


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        operate_token=TOKEN,
        control_room_signal=ROOM,
        mqtt_inputs=[{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
        weather_enabled=True,
        weather_latitude=52.09,
        weather_longitude=5.12,
        weather_location_source="manual",
    )


class Rig:
    def __init__(self, settings: Settings, control: Any = None, *, forecast: bool = True) -> None:
        self.clock = FakeClock(NOW)
        self.runtime = Runtime(clock=self.clock)
        self.manager = ConfigManager.open(settings, self.clock, locked={})
        self.settings = self.manager.settings
        if forecast:
            conn = open_history(self.settings.history_path)
            rows = [
                ForecastRow(HOUR - 3600.0, HOUR + h * 3600.0, 4.0, 150.0 + h, 50.0, 2.0)
                for h in range(-1, 5)
            ]
            write_forecast(conn, rows)
            conn.close()
        self.weather = WeatherService(
            self.settings,
            self.clock,
            OpenMeteoProvider(lambda _: b"{}"),
            history_path=self.settings.history_path,
        )
        app = create_app(
            self.runtime,
            self.settings,
            config=self.manager,
            weather=self.weather,
            control=control,
        )
        self.client = TestClient(app)

    def feed(
        self, signal: str, value: float | int, unit: str | None = None, *, mqtt: bool = False
    ) -> None:
        source = SourceKind.MQTT if mqtt else SourceKind.HEISHAMON
        self.runtime.apply(Reading(signal, value, unit, self.clock(), source))

    def live(
        self,
        *,
        room: float | None = 20.5,
        outside: float | None = 4.0,
        hz: float = 30.0,
        dhw: int = 0,
    ) -> None:
        if room is not None:
            self.feed(ROOM, room, "°C", mqtt=True)
        if outside is not None:
            self.feed(HeishaSignal.OUTSIDE_TEMP, outside, "°C")
        self.feed(HeishaSignal.COMPRESSOR_FREQ, hz, "Hz")
        self.feed(HeishaSignal.THREEWAY_VALVE_STATE, dhw)
        self.feed(HeishaSignal.PUMP_FLOW, 15.0, "l/min")
        self.feed(HeishaSignal.INLET_TEMP, 28.0, "°C")
        self.feed(HeishaSignal.OUTLET_TEMP, 32.0, "°C")


def stub_control(config: Any, *, stove: bool = False) -> ControlLoop:
    return cast(
        ControlLoop,
        SimpleNamespace(
            controller=SimpleNamespace(config=config),
            stove_status=lambda: {"active": stove},
        ),
    )


def test_series_is_read_strictly_and_shaped(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    body = rig.client.get("/api/v1/insight/house/series").json()
    assert list(body) == [
        "model",
        "step_s",
        "from",
        "to",
        "points",
        "events",
        "out_of_sample_from",
        "rmse_k",
        "bias_k",
        "compared_points",
    ]
    assert (body["events"], body["out_of_sample_from"], body["rmse_k"]) == ([], None, None)
    assert body["compared_points"] == 0
    assert body["model"] == MODEL
    assert body["step_s"] == 900
    assert body["from"] == "2026-11-12T00:00:00Z"
    assert body["to"] == "2026-11-12T23:45:00Z"
    assert len(body["points"]) == 96
    assert body["points"][0] == ["2026-11-12T00:00:00Z", 20.0, None]
    assert body["points"][10][2] == 20.2


def test_series_is_missing_without_a_champion_or_file(settings: Settings) -> None:
    rig = Rig(settings)
    first = rig.client.get("/api/v1/insight/house/series")
    assert first.status_code == 404
    assert first.json()["detail"]["code"] == "house_series_missing"
    assert first.json()["detail"]["params"] == {}
    write_models(settings.data_dir, series=False)
    second = rig.client.get("/api/v1/insight/house/series")
    assert second.status_code == 404
    assert second.json()["detail"]["code"] == "house_series_missing"
    assert "series-20261113.json" in second.json()["detail"]["message"]


EVENT = {
    "kind": "stove_mode",
    "from": "2026-11-12T03:00:00+00:00",
    "to": "2026-11-12T05:00:00+00:00",
    "tail_to": "2026-11-12T17:00:00+00:00",
}


def test_series_passes_events_and_its_error_summary(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir, series=False)
    put_series(
        settings,
        series_file(
            events=[EVENT],
            out_of_sample_from="2026-11-11T16:30:00+00:00",
            rmse_k=0.396,
            bias_k=-0.252,
            points=80,
        ),
    )
    body = rig.client.get("/api/v1/insight/house/series").json()
    assert body["events"] == [
        {
            "kind": "stove_mode",
            "from": "2026-11-12T03:00:00Z",
            "to": "2026-11-12T05:00:00Z",
            "tail_to": "2026-11-12T17:00:00Z",
        }
    ]
    assert body["out_of_sample_from"] == "2026-11-11T16:30:00Z"
    assert (body["rmse_k"], body["bias_k"], body["compared_points"]) == (0.396, -0.252, 80)


def put_series(settings: Settings, payload: Any) -> None:
    path = settings.data_dir / "models" / "series-20261113.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s | {"schema": "other"},
        lambda s: s | {"model": "house-20260101"},
        lambda s: s | {"columns": ["ts"]},
        lambda s: s | {"step_s": "900"},
        lambda s: s | {"step_s": 5},
        lambda s: s | {"rows": []},
        lambda s: s | {"rows": series_rows(whatif.SERIES_MAX_ROWS + 1)},
        lambda s: s | {"rows": [["2026-11-12T00:00:00Z", 20.0]]},
        lambda s: s | {"rows": [["yesterday", 20.0, 20.0]]},
        lambda s: s | {"rows": [["2026-11-12T00:00:00", 20.0, 20.0]]},
        lambda s: s | {"rows": [["2026-11-12T00:00:00Z", "warm", 20.0]]},
        lambda s: s | {"rows": [["2026-11-12T00:00:00Z", True, 20.0]]},
        lambda s: s | {"rows": [["2026-11-12T00:00:00Z", 999.0, 20.0]]},
        lambda s: (
            s
            | {"rows": [["2026-11-12T01:00:00Z", 20.0, None], ["2026-11-12T00:00:00Z", 20.0, None]]}
        ),
        lambda s: s | {"events": "fire"},
        lambda s: s | {"events": [EVENT] * (whatif.SERIES_MAX_EVENTS + 1)},
        lambda s: s | {"events": [EVENT | {"kind": "party"}]},
        lambda s: s | {"events": [EVENT | {"to": "2026-11-12T01:00:00+00:00"}]},
        lambda s: s | {"events": [EVENT | {"tail_to": None}]},
        lambda s: s | {"out_of_sample_from": "soon"},
        lambda s: s | {"rmse_k": -0.1},
        lambda s: s | {"bias_k": 25.0},
        lambda s: s | {"rmse_k": "0.2"},
        lambda s: s | {"points": 97},
        lambda s: s | {"points": True},
    ],
)
def test_a_malformed_series_is_refused(settings: Settings, mutate: Callable[[Any], Any]) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    put_series(settings, mutate(series_file()))
    response = rig.client.get("/api/v1/insight/house/series")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "house_series_missing"


def test_series_refuses_nan_oversize_links_and_garbage(settings: Settings) -> None:
    rig = Rig(settings)
    models = write_models(settings.data_dir)
    path = models / "series-20261113.json"
    for text in (
        '{"schema": NaN}',
        "not json",
        " " * (whatif.SERIES_MAX_BYTES + 10),
    ):
        path.write_text(text)
        assert rig.client.get("/api/v1/insight/house/series").status_code == 404
    path.unlink()
    target = models / "elsewhere.json"
    target.write_text(json.dumps(series_file()))
    os.symlink(target, path)
    assert rig.client.get("/api/v1/insight/house/series").status_code == 404


def test_series_fits_the_service_limits() -> None:
    assert whatif.SERIES_MAX_BYTES <= house.MAX_FILE_BYTES
    full = json.dumps(series_file(rows=series_rows(14 * 96)))
    assert len(full) < whatif.SERIES_MAX_BYTES
    assert whatif.SERIES_MAX_ROWS >= 14 * 96


def test_whatif_defaults_come_from_the_model_and_the_measured_outside(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    rig.live(outside=4.0)
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    comfort = rig.settings.control_comfort_c
    assert list(body) == [
        "source",
        "model",
        "credible",
        "inputs",
        "heat_demand_w",
        "free_heat_w",
        "loss_w",
        "loop_mean_c",
        "supply_c",
        "curve_c",
        "max_supply_c",
        "limited_by",
        "balance_outside_c",
        "drift",
        "time_constant_h",
    ]
    assert body["source"] == "model"
    assert body["model"] == MODEL
    assert body["credible"] is True
    assert body["inputs"] == {
        "outside_c": 4.0,
        "comfort_c": comfort,
        "sun_wm2": 0.0,
        "stove_w": 0.0,
    }
    assert body["loss_w"] == round(200.0 * (comfort - 4.0))
    assert body["free_heat_w"] == 300
    assert body["heat_demand_w"] == body["loss_w"] - 300
    assert body["balance_outside_c"] == pytest.approx(comfort - 1.5, abs=0.05)
    assert body["drift"]["hours"] == 8
    assert body["drift"]["step_s"] == 900
    assert len(body["drift"]["room_c"]) == 33
    assert body["drift"]["room_c"][0] == comfort
    assert body["drift"]["room_c"][-1] < comfort
    assert body["time_constant_h"] == pytest.approx(
        HouseModel.from_json(BUILDING).time_constant_h, abs=0.05
    )
    assert body["supply_c"] > body["loop_mean_c"] > comfort
    assert body["curve_c"] == rig.settings.controller_config().base_water(4.0)
    assert body["max_supply_c"] == rig.settings.controller_config().safety.max_supply_c


def test_whatif_without_a_measured_outside_uses_zero(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    assert body["inputs"]["outside_c"] == 0.0


def test_whatif_takes_the_scenario_from_the_query(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    base = rig.client.get(
        "/api/v1/insight/house/whatif", params={"outside_c": -5, "comfort_c": 21}
    ).json()
    sunny = rig.client.get(
        "/api/v1/insight/house/whatif",
        params={"outside_c": -5, "comfort_c": 21, "sun_wm2": 200, "stove_w": 1000},
    ).json()
    assert base["inputs"] == {"outside_c": -5.0, "comfort_c": 21.0, "sun_wm2": 0.0, "stove_w": 0.0}
    assert base["heat_demand_w"] == 200 * 26 - 300
    assert sunny["free_heat_w"] == 300 + 600 + 1000
    assert sunny["heat_demand_w"] == 200 * 26 - 1900
    assert sunny["loss_w"] == base["loss_w"]
    assert sunny["balance_outside_c"] < base["balance_outside_c"]


@pytest.mark.parametrize(
    "params",
    [
        {"outside_c": -31},
        {"outside_c": 31},
        {"comfort_c": 4.9},
        {"comfort_c": 30.1},
        {"sun_wm2": -1},
        {"sun_wm2": 1001},
        {"stove_w": -1},
        {"stove_w": 15001},
        {"outside_c": "nan"},
        {"stove_w": "inf"},
        {"comfort_c": "warm"},
    ],
)
def test_whatif_validates_ranges(settings: Settings, params: dict[str, Any]) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    assert rig.client.get("/api/v1/insight/house/whatif", params=params).status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"outside_c": -30, "comfort_c": 5, "sun_wm2": 0, "stove_w": 0},
        {"outside_c": 30, "comfort_c": 30, "sun_wm2": 1000, "stove_w": 15000},
    ],
)
def test_whatif_accepts_the_range_limits(settings: Settings, params: dict[str, Any]) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    assert rig.client.get("/api/v1/insight/house/whatif", params=params).status_code == 200


def test_whatif_limited_by(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    mild = rig.client.get("/api/v1/insight/house/whatif", params={"outside_c": 25}).json()
    assert mild["limited_by"] == ["no_heat_needed"]
    assert mild["heat_demand_w"] == 0
    assert mild["loop_mean_c"] == mild["inputs"]["comfort_c"]
    cold = rig.client.get(
        "/api/v1/insight/house/whatif", params={"outside_c": -30, "comfort_c": 30}
    ).json()
    assert cold["limited_by"] == ["max_supply"]
    assert cold["supply_c"] > cold["max_supply_c"]
    normal = rig.client.get("/api/v1/insight/house/whatif", params={"outside_c": 5}).json()
    assert normal["limited_by"] == []


def test_whatif_uses_the_model_even_when_it_is_not_credible(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir, credible=False)
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    assert body["source"] == "model"
    assert body["credible"] is False


def test_whatif_falls_back_to_the_facts_estimate(make_settings: Callable[..., Settings]) -> None:
    rig = Rig(make_settings(operate_token=TOKEN, **FACTS))
    body = rig.client.get("/api/v1/insight/house/whatif", params={"outside_c": 0}).json()
    assert body["source"] == "estimate"
    assert body["model"] is None
    assert body["credible"] is False
    assert body["loss_w"] > 0
    assert body["time_constant_h"] is not None


def test_whatif_without_a_model_or_facts_names_the_missing_facts(settings: Settings) -> None:
    rig = Rig(settings)
    response = rig.client.get("/api/v1/insight/house/whatif")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "house_model_missing"
    assert "house_build_period" in detail["message"]
    assert "house_floor_area_m2" in detail["message"]
    assert rig.client.get("/api/v1/insight/house/balance").status_code == 404


def test_a_refused_champion_falls_back_to_the_estimate(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(operate_token=TOKEN, **FACTS)
    rig = Rig(settings)
    write_models(settings.data_dir, building=BUILDING | {"h_air_out": -1.0})
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    assert body["source"] == "estimate"


def test_a_refused_champion_without_facts_is_missing(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir, building={"c_water": 1.0})
    assert rig.client.get("/api/v1/insight/house/whatif").status_code == 404


def test_balance_with_weather(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    rig.live(room=20.5, outside=4.0)
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert list(body) == [
        "at",
        "source",
        "credible",
        "room_c",
        "outside_c",
        "sun_wm2",
        "flows",
        "ua_w_per_k",
        "notes",
    ]
    assert body["at"] == "2026-11-13T12:20:00Z"
    assert body["source"] == "model"
    assert body["room_c"] == 20.5
    assert body["outside_c"] == 4.0
    assert body["sun_wm2"] == 150.0
    flows = body["flows"]
    heat = 15.0 / 60.0 * 0.996 * 4180.0 * 4.0
    assert flows["heat_pump_w"] == round(heat)
    assert flows["loss_w"] == round(200.0 * 16.5)
    assert flows["sun_w"] == 450
    assert flows["internal_w"] == 300
    assert flows["stove_active"] is False
    assert flows["storage_w"] == round(round(heat) + 450 + 300 - 3300)
    assert body["ua_w_per_k"] == 200.0
    assert body["notes"] == []


def test_balance_without_weather_has_no_sun_and_no_storage(settings: Settings) -> None:
    rig = Rig(settings, forecast=False)
    write_models(settings.data_dir)
    rig.live()
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert body["sun_wm2"] is None
    assert body["flows"]["sun_w"] is None
    assert body["flows"]["storage_w"] is None
    assert body["flows"]["heat_pump_w"] is not None
    assert "sun_unknown" in body["notes"]


def test_balance_with_the_compressor_off_delivers_nothing(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    rig.live(hz=0.0)
    flows = rig.client.get("/api/v1/insight/house/balance").json()["flows"]
    assert flows["heat_pump_w"] == 0
    assert flows["storage_w"] == 450 + 300 - 3300


def test_balance_during_hot_water_has_no_heat_and_no_storage(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    rig.live(dhw=1)
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert body["flows"]["heat_pump_w"] is None
    assert body["flows"]["storage_w"] is None
    assert "dhw_active" in body["notes"]


def test_balance_with_unknown_inputs(settings: Settings) -> None:
    rig = Rig(settings)
    write_models(settings.data_dir)
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert body["room_c"] is None
    assert body["outside_c"] is None
    assert body["flows"]["loss_w"] is None
    assert body["flows"]["heat_pump_w"] is None
    assert body["flows"]["storage_w"] is None
    assert {"room_unknown", "outside_unknown", "heat_unknown"} <= set(body["notes"])


def test_balance_with_a_stove_burning_has_no_storage(settings: Settings) -> None:
    config = settings.controller_config()
    rig = Rig(settings, control=stub_control(config, stove=True))
    write_models(settings.data_dir)
    rig.live()
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert body["flows"]["stove_active"] is True
    assert body["flows"]["storage_w"] is None
    assert body["flows"]["heat_pump_w"] is not None
    assert "stove_active" in body["notes"]


def test_balance_after_a_stove_episode_has_no_storage_for_the_tail(settings: Settings) -> None:
    config = settings.controller_config()
    rig = Rig(settings, control=stub_control(config))
    write_models(settings.data_dir)
    rig.live()
    conn = open_history(rig.settings.history_path)
    write_journal(
        conn,
        [],
        [],
        [
            AlarmRow(NOW - 5 * 3600.0, "stove_mode", "info", "started", "on", "{}"),
            AlarmRow(NOW - 2 * 3600.0, "stove_mode", "info", "expired", "off", "{}"),
        ],
    )
    conn.close()
    body = rig.client.get("/api/v1/insight/house/balance").json()
    assert "stove_tail" in body["notes"]
    assert "stove_active" not in body["notes"]
    assert body["flows"]["storage_w"] is None
    assert body["flows"]["stove_active"] is False
    assert whatif.stove_tail(rig.settings.history_path, NOW + whatif.STOVE_TAIL_S) is False


def test_balance_from_the_estimate_and_a_model_that_is_not_credible(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        operate_token=TOKEN,
        control_room_signal=ROOM,
        mqtt_inputs=[{"topic": "sim/room", "signal": ROOM, "unit": "°C"}],
        **FACTS,
    )
    rig = Rig(settings, forecast=False)
    rig.live()
    estimated = rig.client.get("/api/v1/insight/house/balance").json()
    assert estimated["source"] == "estimate"
    assert estimated["credible"] is False
    assert "estimate" in estimated["notes"]
    write_models(settings.data_dir, credible=False)
    model = rig.client.get("/api/v1/insight/house/balance").json()
    assert model["source"] == "model"
    assert "not_credible" in model["notes"]


def test_balance_internal_gains_follow_the_local_hour() -> None:
    model = HouseModel.from_json(BUILDING | {"q_int_modulation": 0.5})
    choice = whatif.ModelChoice(model, "model", MODEL, True)
    live = whatif.LiveReading(
        datetime(2026, 11, 13, 19, 0, tzinfo=UTC), 20.0, 5.0, None, 0.0, False, False, 19.0
    )
    assert whatif.balance_payload(choice, live)["flows"]["internal_w"] == 450
    night = whatif.LiveReading(
        datetime(2026, 11, 13, 7, 0, tzinfo=UTC), 20.0, 5.0, None, 0.0, False, False, 7.0
    )
    assert whatif.balance_payload(choice, night)["flows"]["internal_w"] == 150


def test_the_new_routes_are_open_to_every_role_and_need_login_when_one_is_set(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(operate_token=TOKEN, admin_password="pw-123", **FACTS)
    rig = Rig(settings)
    write_models(settings.data_dir)
    for path in ("series", "whatif", "balance"):
        url = f"/api/v1/insight/house/{path}"
        assert rig.client.get(url).status_code == 401
        assert rig.client.get(url, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_insight_keeps_what_the_learner_records_about_its_inputs(settings: Settings) -> None:
    rig = Rig(settings)
    models = write_models(settings.data_dir)
    insight = json.loads((models / "insight-20261113.json").read_text())
    insight["provenance"] = {
        "constraints": {"h_air_out": [150.0, 250.0]},
        "told": {"ua_w_per_k": 310.0, "solar_aperture_m2": 4.5, "internal_gain_w": 440.0},
        "learning": {"fit_days": 60, "test_days": 14, "excluded_days": ["2026-11-03"]},
    }
    insight["validation"] = {"settings_changed": True, "rule": "promoted: settings changed"}
    (models / "insight-20261113.json").write_text(json.dumps(insight))
    body = rig.client.get("/api/v1/insight/house").json()
    assert body["provenance"] == insight["provenance"]
    assert body["validation"] == insight["validation"]


def test_the_whatif_modules_load_without_numpy_or_scipy() -> None:
    code = textwrap.dedent(
        """
        import sys
        import ovenbird.insight.whatif
        import ovenbird.api.insight_api
        import ovenbird_core.housemodel
        loaded = [m for m in ("numpy", "scipy") if m in sys.modules]
        assert not loaded, loaded
        """
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, result.stderr


def test_error_codes_are_registered() -> None:
    assert whatif.ERROR_CODES == ("house_series_missing", "house_model_missing")
    assert math.isfinite(whatif.SERIES_MAX_BYTES)


REVALIDATION = {
    "model": MODEL,
    "at": "2026-11-13T10:00:00+00:00",
    "source": "revalidated",
    "data_to": "2026-11-13T09:30:00+00:00",
    "fitted_to": "2026-11-06T09:30:00+00:00",
    "from": "2026-11-06T09:30:00+00:00",
    "to": "2026-11-13T00:00:00+00:00",
    "origins": 40,
    "in_sample": False,
    "room_rmse_k": 0.72,
    "persistence_room_rmse_k": 0.5,
    "skill_horizon_h": 6.0,
    "skill": -0.1,
    "series_rmse_k": 0.8,
    "series_bias_k": -0.4,
    "credible": False,
    "reasons": ["on the newest held-out days the model does not predict the room 6 h ahead"],
}


def write_status(models: Path, **status: Any) -> None:
    (models / "status.json").write_text(json.dumps({"outcome": "kept_champion"} | status))


def insight_with_validation(models: Path, **validation: Any) -> None:
    path = models / "insight-20261113.json"
    insight = json.loads(path.read_text())
    insight["validation"] = validation
    path.write_text(json.dumps(insight))


def test_the_champion_prefers_its_latest_revalidation(settings: Settings) -> None:
    models = write_models(settings.data_dir, credible=True)
    insight_with_validation(
        models, challenger_room_rmse_k=0.3, held_out_room_rmse_k=0.28, skill_at_horizon=0.2
    )
    frozen = whatif.champion_model(models)
    assert frozen is not None
    assert (frozen.credible, frozen.rmse_k, frozen.skill, frozen.checked_at) == (
        True,
        0.28,
        0.2,
        None,
    )
    write_status(models, champion_revalidation=REVALIDATION)
    checked = whatif.champion_model(models)
    assert checked is not None
    assert (checked.credible, checked.rmse_k, checked.skill) == (False, 0.72, -0.1)
    assert checked.checked_at == REVALIDATION["at"]
    write_status(models, champion_revalidation=REVALIDATION | {"model": "house-20261106"})
    other = whatif.champion_model(models)
    assert other is not None
    assert (other.credible, other.rmse_k, other.checked_at) == (True, 0.28, None)
    write_status(models, champion_revalidation=REVALIDATION | {"credible": True})
    passed = whatif.champion_model(models)
    assert passed is not None
    assert passed.credible is True


def test_an_old_insight_falls_back_to_the_challenger_error(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    insight_with_validation(models, challenger_room_rmse_k=0.3)
    choice = whatif.champion_model(models)
    assert choice is not None
    assert (choice.rmse_k, choice.skill) == (0.3, None)


def test_the_house_score_follows_the_revalidation(settings: Settings) -> None:
    rig = Rig(settings)
    models = write_models(settings.data_dir, credible=True)
    ready = rig.client.get("/api/v1/insight/house").json()
    assert (ready["credible"], ready["revalidation"]) == (True, None)
    write_status(models, champion_revalidation=REVALIDATION)
    body = rig.client.get("/api/v1/insight/house").json()
    assert body["credible"] is False
    assert body["revalidation"]["room_rmse_k"] == 0.72
    assert body["score"]["state"] == "learning"
    assert body["score"]["message"] == cast(list[str], REVALIDATION["reasons"])[0]
    assert body["last_run"]["champion_revalidation"]["model"] == MODEL
    assert body["credibility"]["credible"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"origins": "40"},
        {"origins": -1},
        {"source": "guess"},
        {"credible": "yes"},
        {"in_sample": None},
        {"room_rmse_k": "0.3"},
        {"reasons": "bad"},
        {"reasons": ["x"] * (house.MAX_REASONS + 1)},
        {"model": None},
    ],
)
def test_a_malformed_revalidation_is_ignored_but_the_status_kept(
    settings: Settings, change: dict[str, Any]
) -> None:
    models = write_models(settings.data_dir, credible=True)
    write_status(models, champion_revalidation=REVALIDATION | change, message="ok")
    run = house.last_run(models)
    assert run is not None
    assert run["champion_revalidation"] is None
    assert run["message"] == "ok"
    choice = whatif.champion_model(models)
    assert choice is not None
    assert choice.credible is True


def test_status_warnings_are_read_strictly(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    write_status(models, warnings=["1 wood-stove episode(s) without a recorded end capped"])
    run = house.last_run(models)
    assert run is not None
    assert run["warnings"] == ["1 wood-stove episode(s) without a recorded end capped"]
    write_status(models, warnings=[1])
    assert house.last_run(models) is None
    write_status(models, warnings=["x"] * (house.MAX_WARNINGS + 1))
    assert house.last_run(models) is None


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"credibility": {"credible": True, "checks": {"signature": "yes"}}}, "checks"),
        ({"excitation": {"excited": 1}}, "excitation"),
        ({"excitation": []}, "excitation"),
        ({"at_bound": {"parameter": "x"}}, "at_bound"),
        ({"at_bound": [1]}, "at_bound"),
        ({"validation": {"held_out_room_rmse_k": "0.3"}}, "held_out_room_rmse_k"),
        ({"validation": {"skill_at_horizon": True}}, "skill_at_horizon"),
    ],
)
def test_new_insight_fields_are_type_checked(change: dict[str, Any], says: str) -> None:
    insight = {"schema": "ovenbird.house-insight/1", "credibility": {"credible": True}}
    with pytest.raises(ValueError, match=says):
        house.checked_insight(insight | change)


def gate(ok: bool, needed: list[str] | None = None, message: str | None = None) -> dict[str, Any]:
    return {
        "ok": ok,
        "uses": ["x"],
        "checks": {"one": {"ok": ok, "value": 1.0, "limit": 2.0}},
        "needed": needed or [],
        "reasons": [] if ok else [message or "fails"],
        "message": None if ok else message or "fails",
    }


FITTED = {
    "heat_loss": gate(True),
    "dynamics": gate(True),
    "sun": gate(False, ["more_sunny_days"], "2 more sunny days needed"),
}


def insight_with_gates(models: Path, gates: dict[str, Any]) -> None:
    path = models / "insight-20261113.json"
    insight = json.loads(path.read_text())
    insight["credibility"] = {
        "credible": gates["heat_loss"]["ok"],
        "message": gates["heat_loss"]["message"],
        "gates": gates,
    }
    path.write_text(json.dumps(insight))


def test_each_view_reads_its_own_gate(settings: Settings) -> None:
    rig = Rig(settings)
    models = write_models(settings.data_dir)
    slow = FITTED | {"dynamics": gate(False, ["no_dynamics_skill"], "no 6 h skill")}
    insight_with_gates(models, slow)
    choice = whatif.champion_model(models)
    assert choice is not None
    assert (choice.gate_heat_loss, choice.gate_dynamics, choice.gate_sun) == (True, False, False)
    assert choice.credible is False
    ready = rig.client.get("/api/v1/insight/house").json()
    assert ready["credible"] is True
    assert ready["score"]["state"] != "learning"
    assert ready["gates"]["dynamics"] == {
        "ok": False,
        "needed": ["no_dynamics_skill"],
        "message": "no 6 h skill",
        "source": "fitted",
    }
    assert ready["gates"]["sun"]["needed"] == ["more_sunny_days"]
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    assert body["credible"] is True
    assert body["drift"]["credible"] is False
    loose = FITTED | {"heat_loss": gate(False, ["ua_unstable"], "the UA moves")}
    insight_with_gates(models, loose)
    body = rig.client.get("/api/v1/insight/house/whatif").json()
    assert (body["credible"], body["drift"]["credible"]) == (False, True)
    ready = rig.client.get("/api/v1/insight/house").json()
    assert ready["score"]["state"] == "learning"
    assert ready["score"]["message"] == "the UA moves"


def test_the_revalidated_gates_win_over_the_fitted_ones(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    insight_with_gates(models, FITTED)
    revalidated = {
        "heat_loss": gate(True),
        "dynamics": gate(False, ["no_dynamics_skill"], "no 6 h skill on the newest days"),
        "sun": gate(True),
    }
    write_status(
        models, champion_revalidation=REVALIDATION | {"credible": True, "gates": revalidated}
    )
    choice = whatif.champion_model(models)
    assert choice is not None
    assert (choice.gate_heat_loss, choice.gate_dynamics, choice.gate_sun) == (True, False, True)
    run = house.last_run(models)
    insight = json.loads((models / "insight-20261113.json").read_text())
    gates = house.effective_gates(insight, run["champion_revalidation"] if run else None)
    assert {name: g["source"] for name, g in gates.items()} == dict.fromkeys(
        house.GATES, "revalidated"
    )
    assert gates["dynamics"]["message"] == "no 6 h skill on the newest days"


def test_an_old_revalidation_without_gates_still_bounds_the_heat_loss_gate(
    settings: Settings,
) -> None:
    models = write_models(settings.data_dir)
    insight_with_gates(models, FITTED)
    write_status(models, champion_revalidation=REVALIDATION)
    run = house.last_run(models)
    assert run is not None
    assert run["champion_revalidation"]["gates"] is None
    insight = json.loads((models / "insight-20261113.json").read_text())
    gates = house.effective_gates(insight, run["champion_revalidation"])
    assert gates["heat_loss"]["ok"] is False
    assert gates["heat_loss"]["source"] == "revalidated"
    assert gates["dynamics"]["source"] == "fitted"


def test_a_model_fitted_before_the_gates_has_legacy_gates(settings: Settings) -> None:
    models = write_models(settings.data_dir, credible=True)
    insight = json.loads((models / "insight-20261113.json").read_text())
    gates = house.effective_gates(insight, None)
    assert [gates[g]["ok"] for g in house.GATES] == [True, True, False]
    assert gates["sun"]["needed"] == ["legacy_model"]
    assert {g["source"] for g in gates.values()} == {"legacy"}
    insight["credibility"]["checks"] = {"predictive": False}
    assert house.effective_gates(insight, None)["dynamics"]["needed"] == ["no_dynamics_skill"]
    choice = whatif.champion_model(models)
    assert choice is not None
    assert (choice.credible, choice.gate_sun) == (True, False)


def test_a_bare_choice_follows_credible_for_every_gate() -> None:
    bare = whatif.ModelChoice(HouseModel(), "estimate", None, False)
    assert [bare.gate(g) for g in house.GATES] == [False, False, False]
    told = whatif.ModelChoice(HouseModel(), "model", MODEL, True, gate_sun=False)
    assert [told.gate(g) for g in house.GATES] == [True, True, False]


@pytest.mark.parametrize(
    ("gates", "says"),
    [
        ({"heat_loss": gate(True), "dynamics": gate(True)}, "exactly the gates"),
        (FITTED | {"sun": gate(True) | {"ok": "yes"}}, "sun.ok"),
        (FITTED | {"sun": gate(True) | {"needed": "more"}}, "sun.needed"),
        (FITTED | {"sun": gate(True) | {"message": 3}}, "sun.message"),
        (FITTED | {"sun": gate(True) | {"checks": {"a": {"ok": 1}}}}, "sun.checks"),
        (FITTED | {"sun": gate(True) | {"checks": {"a": True}}}, "sun.checks"),
        (FITTED | {"heat_loss": gate(False)}, "not the heat-loss gate"),
        ([], "gates"),
    ],
)
def test_the_gates_are_read_strictly(gates: Any, says: str) -> None:
    insight = {
        "schema": "ovenbird.house-insight/1",
        "credibility": {"credible": True, "gates": gates},
    }
    with pytest.raises(ValueError, match=says):
        house.checked_insight(insight)


def test_unknown_need_codes_are_dropped(caplog: pytest.LogCaptureFixture) -> None:
    newer = FITTED | {"sun": gate(False, ["more_sunny_days", "new_code"], "x")}
    insight = {
        "schema": "ovenbird.house-insight/1",
        "credibility": {"credible": True, "gates": newer},
    }
    checked = house.checked_insight(insight)
    assert checked["credibility"]["gates"]["sun"]["needed"] == ["more_sunny_days"]
    assert "new_code" in caplog.text


def test_a_revalidation_with_bad_gates_is_ignored(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    insight_with_gates(models, FITTED)
    write_status(
        models,
        champion_revalidation=REVALIDATION | {"credible": True, "gates": {"sun": gate(True)}},
    )
    run = house.last_run(models)
    assert run is not None
    assert run["champion_revalidation"] is None
    disagree = REVALIDATION | {"credible": True, "gates": FITTED | {"heat_loss": gate(False)}}
    with pytest.raises(ValueError, match="heat-loss gate"):
        house.checked_revalidation(disagree)
