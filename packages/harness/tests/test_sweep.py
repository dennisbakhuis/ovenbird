from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ovenbird_harness.faults import SCENARIOS, TAIL_S, WARMUP_S
from ovenbird_harness.fullrun import DEFAULT_WEATHER, FITTED_PARAMS, main
from ovenbird_harness.sweep import matrix, plan, run_sweep, single_span, sweep_dates
from ovenbird_harness.testing import REFERENCE_START, reference_config

pytestmark = pytest.mark.slow

LONG_ENV = "OVENBIRD_HARNESS_LONG"
SPAN_FROM = datetime(2025, 10, 6, 2, tzinfo=UTC)
SPAN_TO = datetime(2025, 11, 15, 18, tzinfo=UTC)
CHEAP = ("mode_change", "ovenbird_restart", "pump_setting_write")
CHEAP_DATES = (
    REFERENCE_START.replace(hour=0) + timedelta(days=1),
    REFERENCE_START.replace(hour=13) + timedelta(days=1),
)
CHEAP_WARMUP_S = 2 * 3600.0


def test_sweep_dates_cover_the_span_and_the_day() -> None:
    """Sweep dates are sorted, fit inside the span and cover all eight start hours."""
    window = 32 * 3600.0
    dates = sweep_dates(SPAN_FROM, SPAN_TO, window, 8)
    assert len(dates) == 8
    assert dates == sorted(dates)
    assert dates[0].timestamp() >= SPAN_FROM.timestamp() + WARMUP_S
    assert dates[-1].timestamp() <= SPAN_TO.timestamp() - window - TAIL_S
    assert {d.hour for d in dates} == {0, 3, 6, 9, 12, 15, 18, 21}
    assert (dates[-1] - dates[0]).days >= 30


def test_sweep_dates_refuse_a_span_without_room() -> None:
    """Sweep dates are refused for a span without room for the window or for a zero count."""
    with pytest.raises(ValueError, match="too short"):
        sweep_dates(SPAN_FROM, SPAN_FROM + timedelta(hours=30), 8 * 3600.0, 2)
    with pytest.raises(ValueError, match="at least one"):
        sweep_dates(SPAN_FROM, SPAN_TO, 3600.0, 0)


def test_single_span_holds_the_warmup_window_and_tail() -> None:
    """A single span is the warm-up before the start and the longest window plus the tail after."""
    at = datetime(2026, 10, 21, 3, tzinfo=UTC)
    start, end = single_span(at, ("dhw_run", "room_sensor_silent"))
    assert at - start == timedelta(seconds=WARMUP_S)
    assert end - at == timedelta(seconds=SCENARIOS["room_sensor_silent"]().window_s + TAIL_S)


def test_each_scenario_runs_alone_at_its_start(tmp_path: Path) -> None:
    """Each scenario gets its own run at each start, and the runs pass and write a matrix."""
    base = reference_config(tmp_path, 48.0)
    runs = plan(base, CHEAP, 0, tmp_path / "sweep", dates=CHEAP_DATES, warmup_s=CHEAP_WARMUP_S)
    assert [(name, at) for name, at, _ in runs] == [
        (name, at) for name in CHEAP for at in CHEAP_DATES
    ]
    for name, at, config in runs:
        assert config.faults == (name,)
        assert config.fault_at == ((name, at),)
        assert config.start == at - timedelta(seconds=CHEAP_WARMUP_S)
    rows = run_sweep(runs, jobs=1)
    failed = [(r["name"], r["at"], r.get("failed_checks"), r.get("violations")) for r in rows]
    assert all(r["status"] == "pass" for r in rows), failed
    assert not (runs[0][2].out / "history.db").exists()
    text = matrix(rows)
    assert "mode_change" in text
    assert "FAIL" not in text


def test_at_places_one_scenario_with_its_own_span(tmp_path: Path) -> None:
    """``--at`` places one scenario at its start in a span of its own, and the run passes."""
    at = CHEAP_DATES[0]
    code = main(
        [
            "--fault",
            "mode_change",
            "--at",
            at.isoformat(),
            "--out",
            str(tmp_path),
            "--params",
            "",
            "--weather-dir",
            str(tmp_path / "none"),
            "--datalake",
            str(tmp_path / "none"),
        ]
    )
    summary = json.loads((tmp_path / "faults" / "summary.json").read_text())
    (outcome,) = summary["faults"]
    assert outcome["at"] == at.isoformat().replace("+00:00", "Z")
    assert summary["span"]["from"] == (at - timedelta(seconds=WARMUP_S)).isoformat()
    assert code == 0, outcome


@pytest.mark.skipif(
    not (FITTED_PARAMS.exists() and DEFAULT_WEATHER.exists()),
    reason="local capture data (capture/captures) not available",
)
@pytest.mark.skipif(os.environ.get(LONG_ENV) != "1", reason=f"long variant: set {LONG_ENV}=1")
def test_every_scenario_at_eight_dates_on_the_recorded_data(tmp_path: Path) -> None:
    """Every scenario at eight dates on the recorded data passes (opt-in, slow)."""
    assert main(["--sweep", "8", "--out", str(tmp_path), "--params", str(FITTED_PARAMS)]) == 0
    report = json.loads((tmp_path / "sweep" / "sweep.json").read_text())
    assert len(report["runs"]) == 8 * len(SCENARIOS)
    assert report["passed"]
