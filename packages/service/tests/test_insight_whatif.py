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
    assert list(body) == ["model", "step_s", "from", "to", "points"]
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
