import gzip
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ovenbird_sim.data import capture as cap
from ovenbird_sim.data import datalake as dl
from ovenbird_sim.data.coverage import coverage
from ovenbird_sim.data.dataset import assemble, calibrate_offset, fuse_outside, heat_from_loop
from ovenbird_sim.data.grid import TimeGrid, bin_mean, hold, interpolate, time_since
from ovenbird_sim.data.series import Series, concat
from ovenbird_sim.data.weather import load_weather, merge_hourly

T0 = 1_789_999_200.0


def test_hold_returns_last_value_and_age() -> None:
    s = Series(np.array([10.0, 20.0]), np.array([1.0, 2.0]))
    values, ages = hold(s, np.array([5.0, 10.0, 15.0, 25.0]))
    assert np.isnan(values[0])
    assert values[1:].tolist() == [1.0, 1.0, 2.0]
    assert ages[1:].tolist() == [0.0, 5.0, 5.0]


def test_hold_marks_old_values_missing() -> None:
    s = Series(np.array([0.0]), np.array([3.0]))
    values, _ = hold(s, np.array([10.0, 400.0]), max_age=330.0)
    assert values[0] == 3.0
    assert np.isnan(values[1])


def test_interpolate_respects_gaps() -> None:
    s = Series(np.array([0.0, 10.0, 10_000.0]), np.array([0.0, 10.0, 20.0]))
    out = interpolate(s, np.array([5.0, 5_000.0]), max_gap=3600.0)
    assert out[0] == pytest.approx(5.0)
    assert np.isnan(out[1])


def test_bin_mean_is_time_weighted_and_needs_half_valid() -> None:
    base = np.array([1.0, 1.0, 3.0, 3.0, np.nan, np.nan, np.nan, 2.0])
    out = bin_mean(base, 4)
    assert out[0] == pytest.approx(2.0)
    assert np.isnan(out[1])


def test_time_since() -> None:
    flag = np.array([False, True, False, False, True, False])
    out = time_since(flag, 5.0)
    assert math.isinf(out[0])
    assert out[1:].tolist() == [0.0, 5.0, 10.0, 0.0, 5.0]


def test_grid_covering_aligns_to_step() -> None:
    grid = TimeGrid.covering(T0 + 7.0, T0 + 200.0, 60.0)
    assert grid.start % 60.0 == 0.0
    assert grid.end >= T0 + 200.0
    assert grid.refine(5.0).n == grid.n * 12


def test_series_requires_sorted_times_and_concat_sorts() -> None:
    with pytest.raises(ValueError, match="sorted"):
        Series(np.array([2.0, 1.0]), np.array([0.0, 0.0]))
    merged = concat(
        [Series(np.array([3.0]), np.array([1.0])), Series(np.array([1.0]), np.array([2.0]))]
    )
    assert merged.t.tolist() == [1.0, 3.0]


def test_decode_rejects_sentinels_and_parses_commands() -> None:
    assert cap.decode("panasonic_heat_pump/main/Main_Outlet_Temp", "34.5") == (
        "main/Main_Outlet_Temp",
        34.5,
    )
    assert cap.decode("panasonic_heat_pump/main/Outside_Temp", "-128") is None
    assert cap.decode("panasonic_heat_pump/main/Error", "No error") is None
    sp = cap.decode(
        "panasonic_heat_pump/commands/SetCurves", '{"zone1":{"heat":{"target":{"high":33}}}}'
    )
    assert sp == (cap.CMD_SETPOINT, 33.0)
    assert cap.decode("panasonic_heat_pump/commands/SetMaxPumpDuty", "159") == (
        cap.CMD_PUMP_DUTY,
        159.0,
    )
    assert cap.decode("panasonic_heat_pump/stats", "{}") == (cap.LIVENESS, 1.0)
    assert cap.decode("climate_manager_capture/room_temp", "21.7") == (cap.ROOM_MIRROR, 21.7)
    assert cap.decode("panasonic_heat_pump/1wire/abcd/alias", "x") is None


def _write_capture(path: Path, lines: list[dict[str, object]]) -> None:
    header = json.dumps({"v": 1, "name": "test"})
    body = "\n".join([header, *(json.dumps(x) for x in lines)]) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(body)


def test_load_capture_uses_cache(tmp_path: Path) -> None:
    day = tmp_path / "live"
    day.mkdir()
    lines = [
        {"t": T0 + i * 5.0, "k": "panasonic_heat_pump/stats", "p": "{}"} for i in range(10)
    ] + [{"t": T0 + 1.0, "k": "panasonic_heat_pump/main/Main_Inlet_Temp", "p": "25.5"}]
    _write_capture(day / "2026-09-20.jsonl.gz", lines)
    first = cap.load_capture(day)
    assert (tmp_path / "cache" / "live" / "2026-09-20.npz").exists()
    second = cap.load_capture(day)
    assert set(first) == set(second) == {cap.LIVENESS, "main/Main_Inlet_Temp"}
    assert second["main/Main_Inlet_Temp"].v.tolist() == [25.5]


def test_datalake_loads_states_and_attributes(tmp_path: Path) -> None:
    target = tmp_path / "states" / "entity_id=weather.home" / "year=2026" / "month=10"
    target.mkdir(parents=True)
    ts = pa.array([1_790_000_000_000_000, 1_790_000_060_000_000], type=pa.timestamp("us", tz="UTC"))
    table = pa.table(
        {
            "state": ["21.5", "unavailable"],
            "attributes": [json.dumps({"cloud_coverage": 40}), json.dumps({})],
            "last_changed": ts,
            "last_updated": ts,
            "ingested_at": ts,
        }
    )
    pq.write_table(table, target / "2026-10-01.parquet")
    state = dl.load_state(tmp_path, "weather.home")
    assert state.v[0] == 21.5
    assert np.isnan(state.v[1])
    cloud = dl.load_attribute(tmp_path, "weather.home", "cloud_coverage")
    assert cloud.v[0] == 40.0
    assert len(dl.load_state(tmp_path, "sensor.absent")) == 0


def test_weather_merge_prefers_archive_and_shifts_radiation(tmp_path: Path) -> None:
    times = ["2026-10-01T00:00", "2026-10-01T01:00"]
    primary: dict[str, list[Any]] = {"time": times, "temperature_2m": [5.0, None]}
    fallback: dict[str, list[Any]] = {"time": times, "temperature_2m": [6.0, 7.0]}
    for block in (primary, fallback):
        block["shortwave_radiation"] = [0.0, 100.0]
    merged = merge_hourly(primary, fallback)
    assert merged["temperature_2m"] == [5.0, 7.0]
    assert merged["source_is_archive"] == [1.0, 0.0]
    (tmp_path / "open_meteo_hourly.json").write_text(json.dumps({"hourly": merged}))
    loaded = load_weather(tmp_path)
    assert loaded["wx/shortwave_radiation"].t[1] == loaded["wx/temperature_2m"].t[1] - 1800.0


def test_calibrate_offset_recovers_dithered_offset() -> None:
    rng = np.random.default_rng(1)
    n = 20_000
    true_offset = 0.33
    inlet = np.full(n, 25.0)
    noisy = 25.0 + true_offset + rng.normal(0.0, 0.15, n)
    outlet = np.round(noisy * 4.0) / 4.0
    hz = np.zeros(n)
    hz[:100] = 30.0
    cal = calibrate_offset(inlet, outlet, np.full(n, 13.0), hz, np.zeros(n, dtype=bool))
    assert cal.offset_k == pytest.approx(true_offset, abs=0.01)
    assert cal.median_k in (0.25, 0.5)
    assert cal.n_samples == n - 100 - 240 + 1


def test_heat_from_loop_gating() -> None:
    flow = np.array([25.0, 25.0, 25.0, 25.0])
    inlet = np.array([30.0, 30.0, 30.0, 30.0])
    outlet = np.array([34.0, 34.0, 26.0, 34.0])
    hz = np.array([0.0, 40.0, 40.0, np.nan])
    dhw = np.array([False, False, False, False])
    out = heat_from_loop(flow, inlet, outlet, hz, dhw, 0.0)
    assert out[0] == 0.0
    assert out[1] == pytest.approx(25.0 / 60.0 * 0.996 * 4180.0 * 4.0)
    assert out[2] < 0
    assert np.isnan(out[3])
    assert np.isnan(heat_from_loop(flow, inlet, outlet, hz, ~dhw, 0.0)[1])


def _synthetic_capture() -> dict[str, Series]:
    t = T0 + np.arange(0.0, 7200.0, 5.0)
    live = t[(t < T0 + 3000.0) | (t > T0 + 3120.0)]
    running = (t >= T0 + 1800) & (t < T0 + 3600)

    def dense(values: np.ndarray | float) -> Series:
        return Series(t, np.broadcast_to(np.asarray(values, dtype=float), t.shape).copy())

    return {
        cap.LIVENESS: Series(live, np.ones(live.size)),
        "main/Compressor_Freq": dense(np.where(running, 30.0, 0.0)),
        "main/Main_Inlet_Temp": dense(28.0),
        "main/Main_Outlet_Temp": dense(np.where(running, 32.0, 28.25)),
        "main/Pump_Flow": dense(np.where(running, 25.0, 13.0)),
        "main/Main_Target_Temp": dense(31.0),
        "main/Outside_Temp": dense(4.0),
        "main/Defrosting_State": dense(((t >= T0 + 2400) & (t < T0 + 2700)).astype(float)),
        "main/ThreeWay_Valve_State": dense(0.0),
        cap.ROOM_MIRROR: Series(np.array([T0 - 10.0]), np.array([21.5])),
    }


def test_assemble_flags_and_heat() -> None:
    ds = assemble(_synthetic_capture(), step=60.0, start=T0, end=T0 + 7200.0)
    assert ds.grid.n == 120
    gap_bins = np.flatnonzero(ds.flags["gap"])
    assert gap_bins.min() >= 49
    assert gap_bins.max() <= 52
    assert ds.flags["compressor_on"][30:49].all()
    assert ds.flags["compressor_on"][53:60].all()
    assert not ds.flags["compressor_on"][:30].any()
    assert ds.flags["defrost"][40:45].all()
    assert not ds.flags["dhw"].any()
    assert ds.calibration.offset_k == pytest.approx(0.25)
    assert (ds.columns["heat_w"][:30] == 0.0).all()
    expected = 25.0 / 60.0 * 0.996 * 4180.0 * (4.0 - 0.25)
    assert ds.columns["heat_w"][35] == pytest.approx(expected)
    assert ds.columns["room"][0] == 21.5
    assert not ds.flags["room_stale"].any()
    cov = coverage(ds)
    assert cov.gap_events == 1
    assert cov.columns["outlet"] > 0.95
    coarse = ds.coarsen(5)
    assert coarse.grid.n == 24
    assert coarse.flags["defrost"][8]


def test_fuse_outside_debiases_weather() -> None:
    n = 2880
    weather = 5.0 + 3.0 * np.sin(np.arange(n) / 200.0)
    sensor = np.round(weather - 1.0)
    fused = fuse_outside(sensor, weather, np.ones(n, dtype=bool), 60.0)
    assert np.nanmean(fused - weather) == pytest.approx(-1.0, abs=0.15)
    no_wx = fuse_outside(sensor, None, np.ones(n, dtype=bool), 60.0)
    assert np.nanmean(np.abs(no_wx - (weather - 1.0))) < 0.3
