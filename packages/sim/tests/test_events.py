"""Known-event detection (wood stove) and its use in the building fit."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from ovenbird_sim import local
from ovenbird_sim.data import events
from ovenbird_sim.data.capture import load_capture
from ovenbird_sim.data.dataset import assemble, load_datalake
from ovenbird_sim.data.weather import load_weather
from ovenbird_sim.identify.building import FitConfig, make_windows

DT = 60.0
T0 = datetime(2026, 11, 1, tzinfo=UTC).timestamp()
DAYS = 14
CAPTURES = Path(
    os.environ.get("CAPTURES_DIR") or Path(__file__).resolve().parents[3] / "capture" / "captures"
)


def _house(seed: int = 0) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Two weeks of a living room 2.5 K above hall and bedroom, with sensor-like noise."""
    t = T0 + DT * np.arange(DAYS * 1440)
    rng = np.random.default_rng(seed)
    hour = (t % 86400.0) / 3600.0
    hall = 19.5 + 0.2 * np.sin(2 * np.pi * hour / 24.0) + 0.05 * rng.standard_normal(t.size)
    bed = 20.0 + 0.1 * np.cos(2 * np.pi * hour / 24.0) + 0.05 * rng.standard_normal(t.size)
    living = 22.0 + 0.3 * np.sin(2 * np.pi * (hour - 3.0) / 24.0)
    living = living + 0.05 * rng.standard_normal(t.size)
    return t, living, [hall, bed]


def _fire(t: np.ndarray, start: float, hours: float, peak: float) -> np.ndarray:
    """Living-room heat of a fire: a 1 h rise, a plateau, an exponential decay."""
    rise = np.clip((t - start) / 3600.0, 0.0, 1.0)
    burning = (t >= start) & (t < start + hours * 3600.0)
    after = t >= start + hours * 3600.0
    decay = np.exp(-np.clip(t - (start + hours * 3600.0), 0.0, None) / (4 * 3600.0))
    return peak * np.where(burning, rise, np.where(after, decay, 0.0))


def test_a_fire_is_found_with_its_extent_and_recovery_tail() -> None:
    t, living, refs = _house()
    start = T0 + 9 * 86400.0 + 12 * 3600.0
    found = events.detect_stove(t, living + _fire(t, start, 8.0, 3.5), refs)
    assert len(found) == 1
    event = found[0]
    assert event.kind == events.STOVE
    assert start - 1800.0 <= event.start <= start + 900.0
    assert start + 8 * 3600.0 < event.end < start + 20 * 3600.0
    assert event.tail_end == pytest.approx(event.end + events.TAIL_S)
    assert event.peak_k > 3.0
    assert event.rise_k_per_h > events.RISE_K_PER_H
    assert "wood stove" in event.reason


def test_a_quiet_house_flags_nothing() -> None:
    t, living, refs = _house()
    assert events.detect_stove(t, living, refs) == ()


def test_a_slow_warm_spell_without_a_rise_is_not_a_fire() -> None:
    t, living, refs = _house()
    centre = T0 + 7 * 86400.0
    slow = 2.5 * np.exp(-(((t - centre) / (14 * 3600.0)) ** 2))
    assert events.detect_stove(t, living + slow, refs) == ()


def test_a_fast_but_small_warming_is_not_a_fire() -> None:
    t, living, refs = _house()
    start = T0 + 9 * 86400.0 + 12 * 3600.0
    assert events.detect_stove(t, living + _fire(t, start, 3.0, 1.5), refs) == ()


def test_warming_the_whole_house_is_not_a_fire() -> None:
    t, living, refs = _house()
    start = T0 + 9 * 86400.0 + 12 * 3600.0
    heat = _fire(t, start, 6.0, 3.0)
    assert events.detect_stove(t, living + heat, [r + heat for r in refs]) == ()


def test_two_fires_on_one_evening_merge() -> None:
    t, living, refs = _house()
    first = T0 + 9 * 86400.0 + 12 * 3600.0
    second = first + 10 * 3600.0
    heat = np.maximum(_fire(t, first, 3.0, 3.0), _fire(t, second, 3.0, 3.0))
    found = events.detect_stove(t, living + heat, refs)
    assert len(found) == 1
    assert found[0].start < first + 3600.0
    assert found[0].end > second + 3 * 3600.0


def test_masks_and_days() -> None:
    event = events.Event(
        events.STOVE,
        T0 + 86400.0 + 20 * 3600.0,
        T0 + 2 * 86400.0 + 2 * 3600.0,
        T0 + 2 * 86400.0 + 14 * 3600.0,
        4.0,
        3.0,
    )
    t = T0 + 3600.0 * np.arange(4 * 24, dtype=np.float64)
    inside = events.mask(t, (event,))
    assert inside.sum() == 18
    assert events.mask(t, (event,), tail=False).sum() == 6
    assert events.days_touched((event,)) == ("2026-11-02", "2026-11-03")
    assert events.day_mask(t, (event,)).sum() == 48
    payload = event.to_json()
    assert payload["utc_days"] == ["2026-11-02", "2026-11-03"]
    assert payload["hours"] == 6.0
    assert payload["excluded_hours"] == 18.0


def test_building_windows_overlapping_an_event_are_left_out() -> None:
    from ovenbird_sim.data.synthetic import simulated_dataset
    from ovenbird_sim.model.building import BuildingParams
    from ovenbird_sim.model.heatpump import HeatPumpParams
    from ovenbird_sim.model.plant import PlantParams, PlantState

    n = 3 * 288
    params = PlantParams(HeatPumpParams(), BuildingParams())
    ds = simulated_dataset(
        params,
        PlantState(t_water=30.0, t_mass=22.0, t_air=21.0),
        np.full(n, 32.0),
        np.full(n, 5.0),
        np.zeros(n),
        start=T0,
        dt=300.0,
    )
    clean = make_windows(ds, FitConfig())
    flag = np.zeros(n, dtype=np.bool_)
    flag[300:340] = True
    flagged = type(ds)(
        ds.grid, ds.columns, ds.flags | {"event": flag}, ds.calibration, ds.notes, ()
    )
    windows = make_windows(flagged, FitConfig())
    assert windows.n == clean.n - 1
    assert windows.event_starts == (float(ds.t[288]),)


STOVE_DAYS = tuple(
    day.strip()
    for day in local.settings(CAPTURES / local.SETTINGS_FILE).get("STOVE_DAYS", "").split(",")
    if day.strip()
)


@pytest.mark.skipif(
    not any((CAPTURES / "live").glob("*.jsonl*"))
    or not (CAPTURES / "datalake").is_dir()
    or not STOVE_DAYS,
    reason="local capture or its STOVE_DAYS setting not present (data is never committed)",
)
def test_the_recording_has_exactly_the_known_stove_fire() -> None:
    first = datetime.fromisoformat(STOVE_DAYS[0]).replace(tzinfo=UTC)
    last = datetime.fromisoformat(STOVE_DAYS[-1]).replace(tzinfo=UTC)
    capture = load_capture(CAPTURES / "live")
    ds = assemble(
        capture,
        datalake=load_datalake(CAPTURES / "datalake"),
        weather=load_weather(CAPTURES / "weather"),
        step=60.0,
        end=(last + timedelta(days=3)).timestamp(),
    )
    assert len(ds.events) == 1
    assert events.days_touched(ds.events) == STOVE_DAYS
    event = ds.events[0]
    assert event.start >= (first + timedelta(hours=10)).timestamp()
    assert event.start <= (first + timedelta(hours=13)).timestamp()
    assert ds.flags["event"].any()
