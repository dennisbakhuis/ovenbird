from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from ovenbird_harness.fullrun import DEFAULT_WEATHER, FITTED_PARAMS, FullRun, main
from ovenbird_harness.settings import Profile
from ovenbird_harness.testing import RecordedRun, recorded_run, reference_config
from ovenbird_harness.validate import mqtt_config

pytestmark = pytest.mark.slow

LONG_ENV = "OVENBIRD_HARNESS_LONG"


def test_short_run_passes_and_writes_its_outputs(short_run: RecordedRun) -> None:
    summary = short_run.result.summary
    out = short_run.run.config.out
    assert short_run.result.passed, summary["invariants"]
    assert (out / "summary.json").exists()
    assert "<title>ovenbird full run</title>" in (out / "summary.html").read_text()
    stored = json.loads((out / "summary.json").read_text())
    assert stored["passed"] is True
    history = summary["history"]
    assert history["consistent"]
    assert history["decision_rows"] == 720
    with sqlite3.connect(out / "history.db") as db:
        assert db.execute("SELECT count(*) FROM decision").fetchone()[0] == 720
        assert db.execute("SELECT count(*) FROM control_state").fetchone()[0] == 1
    kpis = summary["kpis"]
    assert kpis["decisions"] == 720
    assert set(kpis["ladder_shares"]) <= {"schedule_curve_feedback", "curve_only", "refuse", "hold"}
    assert kpis["commands"]["events"]["sent"] == kpis["commands"]["events"]["verified"]
    assert summary["board"]["commands_applied"] == kpis["commands"]["events"]["sent"]
    assert 20.0 < kpis["room"]["mean_c"] < 23.0
    assert summary["wall_time_s"] > 0


def test_the_room_arrives_through_home_assistant(short_run: RecordedRun) -> None:
    run = short_run.run
    assert run.ha is not None
    assert run.ha.refreshes >= 12 * 12 - 1
    assert run.ha.events > 0
    room = json.loads(short_run.decisions[-1].record)
    refs = [r for r in room["inputs_used"] if r["source"] == "room"]
    assert refs[0]["signal"] == "ha/sensor.living_room_temperature"
    assert short_run.result.summary["kpis"]["room_fresh_share"] > 0.9


def test_room_via_mqtt_with_a_periodic_sensor(tmp_path: Path) -> None:
    config = reference_config(
        tmp_path, 3.0, profile=Profile(room_via="mqtt", room_profile="periodic")
    )
    recorded = recorded_run(config)
    assert recorded.result.passed
    assert recorded.run.ha is None
    assert recorded.result.summary["kpis"]["ladder_shares"].get("schedule_curve_feedback", 0) > 0.9


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--from",
            "2025-11-10T06:00",
            "--to",
            "2025-11-10T08:00",
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
    assert code == 0
    printed = capsys.readouterr().out
    assert '"passed": true' in printed
    assert (tmp_path / "plain" / "summary.html").exists()


def test_mqtt_config_for_validation(tmp_path: Path) -> None:
    config = mqtt_config(reference_config(tmp_path, 1.0).start, None, None, tmp_path)
    run = FullRun(config)
    assert run.settings.control_room_signal == "room_temperature"
    run.system.close()


@pytest.mark.skipif(
    not (FITTED_PARAMS.exists() and DEFAULT_WEATHER.exists()),
    reason="local capture data (capture/captures) not available",
)
@pytest.mark.skipif(os.environ.get(LONG_ENV) != "1", reason=f"long variant: set {LONG_ENV}=1")
def test_full_span_on_the_recorded_data(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path), "--params", str(FITTED_PARAMS)]) == 0
