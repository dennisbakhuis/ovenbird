from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ovenbird.control import monitors
from ovenbird_harness.faults import SCENARIOS, Scheduler
from ovenbird_harness.fullrun import FullRun, main
from ovenbird_harness.sweep import single_span
from ovenbird_harness.testing import recorded_run, reference_config

HOURS = {
    "heishamon_restart": 6.0,
    "broker_drop": 6.0,
    "ha_link_down": 8.0,
    "room_sensor_silent": 40.0,
    "room_sensor_dies_warm": 40.0,
    "foreign_writer": 8.0,
    "ovenbird_restart": 8.0,
    "config_apply": 12.0,
    "pump_setting_write": 12.0,
    "command_lost": 12.0,
    "mode_change": 6.0,
    "topic_stale": 6.0,
    "dhw_run": 6.0,
    "setpoint_above_max": 6.0,
    "ha_reread_fails": 8.0,
    "stove_evening": 27.0,
    "envelope_correction": 6.0,
    "room_sensor_fails_high": 16.0,
}


SLOW_SCENARIOS = frozenset({"room_sensor_silent", "room_sensor_dies_warm", "stove_evening"})


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(name, marks=pytest.mark.slow) if name in SLOW_SCENARIOS else name
        for name in sorted(SCENARIOS)
    ],
)
def test_fault_scenario_behaves(name: str, tmp_path: Path) -> None:
    """Each scenario passes its checks with no invariant violation in its own short run."""
    recorded = recorded_run(reference_config(tmp_path, HOURS[name], faults=(name,)))
    summary = recorded.result.summary
    (outcome,) = summary["faults"]
    failed = [c for c in outcome["checks"] if c["status"] == "fail"]
    assert outcome["status"] == "pass", failed
    assert summary["invariants"]["violations"] == 0, summary["invariants"]["first"]
    assert recorded.result.passed


@pytest.mark.slow
@pytest.mark.parametrize("hour", [0, 6, 12, 18])
def test_a_sensor_dying_warm_keeps_comfort_at_any_hour(hour: int, tmp_path: Path) -> None:
    """The sensor dying warm at any hour of the day keeps the room above comfort minus 0.75 K."""
    name = "room_sensor_dies_warm"
    at = datetime(2025, 11, 12, tzinfo=UTC) + timedelta(hours=hour)
    start, end = single_span(at, (name,))
    config = reference_config(
        tmp_path, 0.0, start=start, end=end, faults=(name,), fault_at=((name, at),)
    )
    summary = recorded_run(config).result.summary
    (outcome,) = summary["faults"]
    failed = [c for c in outcome["checks"] if c["status"] == "fail"]
    assert outcome["status"] == "pass", failed
    assert outcome["notes"]["room_min_c"] > config.profile.comfort_c - 0.75
    assert summary["invariants"]["violations"] == 0, summary["invariants"]["first"]


def test_every_scenario_has_a_test_window() -> None:
    """Every scenario in the catalogue has a run length in ``HOURS``."""
    assert set(HOURS) == set(SCENARIOS)


def test_scheduler_refuses_a_short_span(tmp_path: Path) -> None:
    """A span too short for a scenario, or an unknown scenario name, is refused."""
    run = FullRun(reference_config(tmp_path, 10.0))
    try:
        with pytest.raises(ValueError, match="too short"):
            Scheduler.build(run, ("room_sensor_silent",))
        with pytest.raises(ValueError, match="unknown"):
            Scheduler.build(run, ("meteor",))
    finally:
        run.system.close()


def test_a_missing_alarm_fails_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fault run whose expected alarm never appears fails with that check and exit code 1."""

    def no_alarm(*_: Any) -> None:
        """Stand in for the link monitor, raising no alarm."""
        return

    monkeypatch.setattr(monitors, "_ha_link", no_alarm)
    code = main(
        [
            "--from",
            "2025-11-10T06:00",
            "--to",
            "2025-11-10T14:00",
            "--out",
            str(tmp_path),
            "--params",
            "",
            "--weather-dir",
            str(tmp_path / "none"),
            "--datalake",
            str(tmp_path / "none"),
            "--fault",
            "ha_link_down",
        ]
    )
    assert code == 1
    summary = json.loads((tmp_path / "faults" / "summary.json").read_text())
    (outcome,) = summary["faults"]
    failed = [c["check"] for c in outcome["checks"] if c["status"] == "fail"]
    assert failed == ["ha_link_down raised during the outage and cleared after it"]
    assert all(c["status"] in ("pass", "fail") for c in outcome["checks"])


def test_every_check_is_pass_or_fail(tmp_path: Path) -> None:
    """Scenario checks end as pass or fail, never pending."""
    recorded = recorded_run(reference_config(tmp_path, 8.0, faults=("ha_link_down",)))
    statuses = {c["status"] for o in recorded.result.summary["faults"] for c in o["checks"]}
    assert statuses <= {"pass", "fail"}


def test_explicit_start_times(tmp_path: Path) -> None:
    """A scenario placed at an explicit start keeps it; one that does not fit or run is refused."""
    run = FullRun(reference_config(tmp_path, 60.0))
    try:
        at = run.start_ts + 30 * 3600.0
        placed = Scheduler.build(run, ("config_apply", "dhw_run"), {"dhw_run": at})
        starts = {s.name: s.start for s in placed.scenarios}
        with pytest.raises(ValueError, match="does not fit"):
            Scheduler.build(run, ("dhw_run",), {"dhw_run": run.end_ts - 3600.0})
        with pytest.raises(ValueError, match="do not run"):
            Scheduler.build(run, ("dhw_run",), {"mode_change": at})
    finally:
        run.system.close()
    assert starts["dhw_run"] == at
    assert starts["config_apply"] == run.start_ts + 0.1 * 60 * 3600.0
